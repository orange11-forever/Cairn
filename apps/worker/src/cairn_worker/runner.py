import json
import os
import re
import signal
import socket
import sys
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread, current_thread, main_thread
from types import FrameType
from typing import Any, Protocol, Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cairn_api.db.session import Database
from cairn_api.knowledge.models import EmbeddingProfile, EmbeddingProfileStatus, JobKind
from cairn_api.knowledge.object_store import Boto3ObjectStore, ObjectStore
from cairn_api.settings import Settings
from sqlalchemy import select

from cairn_worker.errors import WorkerFailure
from cairn_worker.leases import (
    HEARTBEAT_INTERVAL,
    ClaimedJob,
    claim_next_job,
    fail_job,
    renew_lease,
)

REQUIRED_JOB_KINDS = frozenset({JobKind.EXPAND_ARCHIVE, JobKind.INDEX_RESOURCE_VERSION})
_WORKER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_POLL_INTERVAL_SECONDS = 1.0

SessionFactory = Callable[[], Any]


@contextmanager
def _transaction(session_factory: SessionFactory) -> Generator[Any]:
    session = session_factory()
    try:
        with session.begin():
            yield session
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


class Heartbeat(Protocol):
    def __enter__(self) -> Self: ...

    def ensure_owned(self) -> None: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None: ...


JobHandler = Callable[[Any, ClaimedJob, Heartbeat], None]
HeartbeatFactory = Callable[..., Heartbeat]
Now = Callable[[], datetime]


def validate_worker_id(worker_id: str) -> str:
    if _WORKER_ID_PATTERN.fullmatch(worker_id) is None:
        raise ValueError("worker_id must be 1-128 safe owner characters")
    return worker_id


def ensure_complete_handlers(handlers: Mapping[JobKind, JobHandler]) -> None:
    missing = REQUIRED_JOB_KINDS.difference(handlers)
    if missing:
        names = ", ".join(sorted(kind.value for kind in missing))
        raise ValueError(f"missing worker handlers: {names}")


class HeartbeatController:
    def __init__(
        self,
        session_factory: SessionFactory,
        claim: ClaimedJob,
        now: Now,
        *,
        interval: timedelta = HEARTBEAT_INTERVAL,
    ) -> None:
        if interval <= timedelta(0):
            raise ValueError("heartbeat interval must be positive")
        self._session_factory = session_factory
        self._claim = claim
        self._now = now
        self._interval_seconds = interval.total_seconds()
        self._stop = Event()
        self._failure_lock = Lock()
        self._failure: WorkerFailure | None = None
        self._thread = Thread(
            target=self._heartbeat_loop,
            name=f"cairn-heartbeat-{claim.job_id}",
            daemon=True,
        )

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def _set_failure(self, failure: WorkerFailure) -> None:
        with self._failure_lock:
            if self._failure is None:
                self._failure = failure
        self._stop.set()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                with _transaction(self._session_factory) as session:
                    owned = renew_lease(
                        session,
                        job_id=self._claim.job_id,
                        worker_id=self._claim.lease_owner,
                        now=self._now(),
                    )
            except Exception:  # noqa: BLE001 -- infrastructure failures must stop publication.
                self._set_failure(
                    WorkerFailure(
                        "database_unavailable",
                        "heartbeat database operation failed",
                        retryable=True,
                    )
                )
                return
            if not owned:
                self._set_failure(
                    WorkerFailure("lease_lost", "worker no longer owns the job lease", retryable=True)
                )
                return

    def ensure_owned(self) -> None:
        with self._failure_lock:
            failure = self._failure
        if failure is not None:
            raise failure

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self._stop.set()
        self._thread.join(timeout=5)


def run_once(
    *,
    session_factory: SessionFactory,
    worker_id: str,
    handlers: Mapping[JobKind, JobHandler],
    now: Now | None = None,
    heartbeat_factory: HeartbeatFactory = HeartbeatController,
) -> bool:
    ensure_complete_handlers(handlers)
    owner = validate_worker_id(worker_id)
    current_time = now or (lambda: datetime.now(UTC))
    with _transaction(session_factory) as session:
        claim = claim_next_job(session, worker_id=owner, now=current_time())
    if claim is None:
        return False

    try:
        with (
            heartbeat_factory(session_factory, claim, current_time) as heartbeat,
            _transaction(session_factory) as session,
        ):
            handlers[claim.job_kind](session, claim, heartbeat)
            heartbeat.ensure_owned()
    except WorkerFailure as failure:
        with _transaction(session_factory) as session:
            fail_job(session, claim=claim, failure=failure, now=current_time())
    except Exception:  # noqa: BLE001 -- persist a bounded fact for unexpected handler failures.
        failure = WorkerFailure(
            "parser_failed",
            "unexpected worker handler failure",
            retryable=True,
        )
        with _transaction(session_factory) as session:
            fail_job(session, claim=claim, failure=failure, now=current_time())
    return True


def _validate_profile(profile: EmbeddingProfile, settings: Settings) -> None:
    chunking = profile.chunking_config
    index = profile.index_config
    maximum = chunking.get("maxCodepoints")
    overlap = chunking.get("overlapCodepoints")
    candidate_limit = index.get("candidateLimit")
    if (
        profile.provider_key not in {"default", settings.embedding_provider_key}
        or profile.model != settings.embedding_model
        or profile.dimensions != settings.embedding_dimensions
        or profile.distance_metric != "cosine"
        or not isinstance(maximum, int)
        or maximum <= 0
        or not isinstance(overlap, int)
        or overlap < 0
        or overlap >= maximum
        or index.get("strategy") != "exact"
        or not isinstance(candidate_limit, int)
        or candidate_limit <= 0
    ):
        raise RuntimeError("active embedding profile is incompatible with worker settings")


def check_embedding_ready(settings: Settings) -> None:
    endpoint = f"{str(settings.embedding_base_url).rstrip('/')}/embeddings"
    payload = json.dumps(
        {
            "input": ["cairn readiness probe"],
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {settings.embedding_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.embedding_timeout_seconds) as response:
            body: object = json.load(response)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, TypeError):
        raise RuntimeError("embedding provider is not ready") from None
    if not isinstance(body, dict):
        raise RuntimeError(  # noqa: TRY004 -- malformed provider response is runtime failure.
            "embedding provider returned an invalid readiness response"
        )
    body_values = cast(dict[str, object], body)
    data = body_values.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise RuntimeError("embedding provider returned an invalid readiness response")
    first_record = cast(dict[str, object], data[0])
    vector = first_record.get("embedding")
    if not isinstance(vector, list):
        raise RuntimeError(  # noqa: TRY004 -- malformed provider response is runtime failure.
            "embedding provider returned an invalid readiness dimension"
        )
    vector_values = cast(list[object], vector)
    if len(vector_values) != settings.embedding_dimensions:
        raise RuntimeError("embedding provider returned an invalid readiness dimension")


class Runtime:
    def preflight(self) -> None:
        raise NotImplementedError

    def run_once(self) -> bool:
        raise NotImplementedError

    def serve(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


class WorkerRuntime(Runtime):
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        object_store: ObjectStore,
        handlers: Mapping[JobKind, JobHandler],
        worker_id: str,
        embedding_readiness: Callable[[Settings], None] = check_embedding_ready,
    ) -> None:
        self._settings = settings
        self._database = database
        self._object_store = object_store
        self._handlers = dict(handlers)
        self._worker_id = validate_worker_id(worker_id)
        self._embedding_readiness = embedding_readiness
        self._stop = Event()

    def preflight(self) -> None:
        ensure_complete_handlers(self._handlers)
        self._database.check_ready()
        self._object_store.check_ready()
        with self._database.session_factory() as session:
            profiles = list(
                session.scalars(
                    select(EmbeddingProfile).where(
                        EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE
                    )
                )
            )
        if not profiles or not any(profile.org_id is None for profile in profiles):
            raise RuntimeError("a global active embedding profile is required")
        for profile in profiles:
            _validate_profile(profile, self._settings)
        self._embedding_readiness(self._settings)

    def run_once(self) -> bool:
        return run_once(
            session_factory=self._database.session_factory,
            worker_id=self._worker_id,
            handlers=self._handlers,
        )

    def _request_stop(self, _signum: int, _frame: FrameType | None) -> None:
        self._stop.set()

    def serve(self) -> None:
        previous_handlers: dict[signal.Signals, Any] = {}
        signals = (signal.SIGINT, signal.SIGTERM)
        if current_thread() is main_thread():
            for current_signal in signals:
                previous_handlers[current_signal] = signal.signal(
                    current_signal, self._request_stop
                )
        try:
            while not self._stop.is_set():
                if not self.run_once():
                    self._stop.wait(_POLL_INTERVAL_SECONDS)
        finally:
            for current_signal, previous in previous_handlers.items():
                signal.signal(current_signal, previous)

    def close(self) -> None:
        try:
            self._object_store.close()
        finally:
            self._database.dispose()


HANDLERS: dict[JobKind, JobHandler] = {}


def register_handler(job_kind: JobKind, handler: JobHandler) -> None:
    if job_kind in HANDLERS:
        raise ValueError(f"worker handler already registered: {job_kind.value}")
    HANDLERS[job_kind] = handler


def build_runtime() -> WorkerRuntime:
    settings = Settings()
    database = Database(settings.database_url)
    try:
        object_store = Boto3ObjectStore.from_settings(settings)
    except Exception:
        database.dispose()
        raise
    return WorkerRuntime(
        settings=settings,
        database=database,
        object_store=object_store,
        handlers=HANDLERS,
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
    )


def main(argv: list[str] | None = None, *, runtime: Runtime | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments not in (["serve"], ["--once"], ["preflight"]):
        print("Usage: cairn-worker [serve|--once|preflight]", file=sys.stderr)
        return 2
    owns_runtime = runtime is None
    current_runtime = runtime
    try:
        current_runtime = current_runtime or build_runtime()
        current_runtime.preflight()
        if arguments == ["serve"]:
            current_runtime.serve()
        elif arguments == ["--once"]:
            current_runtime.run_once()
        return 0
    except Exception:  # noqa: BLE001 -- CLI converts configuration/infrastructure failure to exit 1.
        print("worker startup failed", file=sys.stderr)
        return 1
    finally:
        if owns_runtime and current_runtime is not None:
            current_runtime.close()


__all__ = [
    "HANDLERS",
    "REQUIRED_JOB_KINDS",
    "HeartbeatController",
    "Runtime",
    "WorkerRuntime",
    "build_runtime",
    "check_embedding_ready",
    "ensure_complete_handlers",
    "main",
    "register_handler",
    "run_once",
    "validate_worker_id",
]
