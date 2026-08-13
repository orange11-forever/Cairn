import json
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.client import HTTPMessage
from io import BytesIO
from typing import Self, cast
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request
from uuid import uuid4

import pytest
from cairn_api.db.session import Database
from cairn_api.knowledge.models import (
    EmbeddingProfile,
    EmbeddingProfileStatus,
    JobKind,
)
from cairn_api.knowledge.object_store import ObjectStore
from cairn_api.settings import Settings
from cairn_worker.errors import WorkerFailure
from cairn_worker.leases import ClaimedJob
from cairn_worker.runner import (
    REQUIRED_JOB_KINDS,
    Runtime,
    WorkerRuntime,
    check_embedding_ready,
    ensure_complete_handlers,
    main,
    run_once,
    validate_worker_id,
)
from pydantic import AnyHttpUrl, SecretStr


class _EmbeddingOpener:
    def __init__(self, response: BytesIO | Exception) -> None:
        self.response = response
        self.requests: list[Request] = []

    def open(self, request: Request, *, timeout: float) -> BytesIO:
        assert timeout > 0
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _embedding_settings(*, base_url: str = "https://embedding.example/v1") -> Settings:
    return Settings(
        embedding_base_url=AnyHttpUrl(base_url),
        embedding_api_key=SecretStr("quality-fix-secret-token"),
    )


def test_embedding_readiness_accepts_a_valid_2xx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: redirect protection must preserve the normal authenticated readiness probe."""
    response = json.dumps({"data": [{"embedding": [0.1] * 1024}]}).encode()
    opener = _EmbeddingOpener(BytesIO(response))
    handlers: list[HTTPRedirectHandler] = []

    def build(*values: HTTPRedirectHandler) -> _EmbeddingOpener:
        handlers.extend(values)
        return opener

    monkeypatch.setattr("cairn_worker.runner.build_opener", build)

    check_embedding_ready(_embedding_settings())

    assert len(handlers) == 1
    assert len(opener.requests) == 1
    request = opener.requests[0]
    assert request.full_url == "https://embedding.example/v1/embeddings"
    assert request.get_header("Authorization") == "Bearer quality-fix-secret-token"


@pytest.mark.parametrize(
    "redirect_target",
    [
        "https://embedding.example/v1/other",
        "https://attacker.example/collect",
        "http://embedding.example/collect",
    ],
    ids=["same-origin", "cross-origin", "https-downgrade"],
)
def test_embedding_readiness_refuses_every_redirect_without_forwarding_authorization(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    redirect_target: str,
) -> None:
    """Break caught: bearer credentials must never cross any provider redirect."""
    requests: list[Request] = []
    raw_body = b'{"error":"private provider response"}'

    class RedirectingOpener:
        def open(self, request: Request, *, timeout: float) -> BytesIO:
            del timeout
            requests.append(request)
            redirected = handlers[0].redirect_request(
                request,
                BytesIO(raw_body),
                302,
                "token quality-fix-secret-token",
                HTTPMessage(),
                redirect_target,
            )
            if redirected is not None:
                requests.append(redirected)
            raise HTTPError(
                request.full_url,
                302,
                "token quality-fix-secret-token",
                HTTPMessage(),
                BytesIO(raw_body),
            )

    handlers: list[HTTPRedirectHandler] = []

    def build(*values: HTTPRedirectHandler) -> RedirectingOpener:
        handlers.extend(values)
        return RedirectingOpener()

    monkeypatch.setattr("cairn_worker.runner.build_opener", build)

    with pytest.raises(RuntimeError) as raised:
        check_embedding_ready(_embedding_settings())

    assert str(raised.value) == "embedding provider is not ready"
    assert len(requests) == 1
    assert requests[0].get_header("Authorization") == "Bearer quality-fix-secret-token"
    captured = capsys.readouterr()
    exposed = str(raised.value) + captured.out + captured.err
    assert redirect_target not in exposed
    assert "quality-fix-secret-token" not in exposed
    assert "private provider response" not in exposed


@pytest.mark.parametrize(
    "provider_error",
    [
        URLError("token quality-fix-secret-token at https://private.example"),
        HTTPError(
            "https://private.example",
            503,
            "token quality-fix-secret-token",
            HTTPMessage(),
            BytesIO(b"private provider response"),
        ),
    ],
)
def test_embedding_readiness_reports_bounded_network_and_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider_error: Exception,
) -> None:
    """Break caught: readiness failures must not expose tokens, targets, or response bodies."""
    opener = _EmbeddingOpener(provider_error)

    def build(*_handlers: HTTPRedirectHandler) -> _EmbeddingOpener:
        return opener

    monkeypatch.setattr("cairn_worker.runner.build_opener", build)

    with pytest.raises(RuntimeError) as raised:
        check_embedding_ready(_embedding_settings())

    captured = capsys.readouterr()
    exposed = str(raised.value) + captured.out + captured.err
    assert exposed == "embedding provider is not ready"
    assert "quality-fix-secret-token" not in exposed
    assert "private.example" not in exposed
    assert "private provider response" not in exposed


@pytest.mark.parametrize(
    "worker_id",
    ["", " leading", "trailing ", "worker/id", "worker\nnewline", "x" * 129],
)
def test_worker_id_validation_rejects_values_that_are_unsafe_for_leases(worker_id: str) -> None:
    """Break caught: ambiguous or oversized owner IDs must not be stored in lease columns."""
    with pytest.raises(ValueError, match="worker_id"):
        validate_worker_id(worker_id)


def test_worker_id_validation_accepts_host_process_style_ids() -> None:
    """Break caught: normal generated owner IDs must remain usable."""
    assert validate_worker_id("indexer-01.example:4242") == "indexer-01.example:4242"


def test_complete_handler_mapping_is_required_before_any_claim() -> None:
    """Break caught: a worker must refuse startup rather than claim an unhandled job kind."""
    def handler(*_: object) -> None:
        return None

    with pytest.raises(ValueError, match="missing worker handlers"):
        ensure_complete_handlers({JobKind.EXPAND_ARCHIVE: handler})


@dataclass
class _RuntimeProbe(Runtime):
    calls: list[str] = field(default_factory=lambda: list[str]())

    def preflight(self) -> None:
        self.calls.append("preflight")

    def run_once(self) -> bool:
        self.calls.append("once")
        return False

    def serve(self) -> None:
        self.calls.append("serve")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [(["serve"], ["preflight", "serve"]), (["--once"], ["preflight", "once"]), (["preflight"], ["preflight"])],
)
def test_cli_dispatches_each_lifecycle_mode(argv: list[str], expected: list[str]) -> None:
    """Break caught: lifecycle flags must dispatch to the requested worker operation."""
    runtime = _RuntimeProbe()

    assert main(argv, runtime=runtime) == 0
    assert runtime.calls == expected


@pytest.mark.parametrize("failure", [RuntimeError("not ready"), OSError("secret endpoint")])
def test_cli_returns_one_for_configuration_or_preflight_failure(
    failure: Exception,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Break caught: supervisors must observe startup refusal as a nonzero exit."""
    class BrokenRuntime(_RuntimeProbe):
        def preflight(self) -> None:
            raise failure

    assert main(["--once"], runtime=BrokenRuntime()) == 1
    assert "secret endpoint" not in capsys.readouterr().err


class _ProfileSession:
    def __init__(self, profiles: list[EmbeddingProfile]) -> None:
        self._profiles = profiles

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback

    def scalars(self, _statement: object) -> list[EmbeddingProfile]:
        return self._profiles


class _DatabaseProbe:
    def __init__(self, profiles: list[EmbeddingProfile], events: list[str]) -> None:
        self._profiles = profiles
        self._events = events

    def check_ready(self) -> None:
        self._events.append("database")

    def session_factory(self) -> _ProfileSession:
        return _ProfileSession(self._profiles)

    def dispose(self) -> None:
        self._events.append("database-close")


class _ObjectStoreProbe:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def check_ready(self) -> None:
        self._events.append("object-store")

    def close(self) -> None:
        self._events.append("object-store-close")


def _active_profile(*, provider_key: str = "default", dimensions: int = 1024) -> EmbeddingProfile:
    return EmbeddingProfile(
        id=uuid4(),
        org_id=None,
        provider_key=provider_key,
        model="text-embedding-v4",
        dimensions=dimensions,
        distance_metric="cosine",
        chunking_config={"maxCodepoints": 1800, "overlapCodepoints": 180},
        index_config={"strategy": "exact", "candidateLimit": 50},
        version="default-v1",
        status=EmbeddingProfileStatus.ACTIVE,
    )


def _runtime_with_profile(profile: EmbeddingProfile, events: list[str]) -> WorkerRuntime:
    def handler(*_: object) -> None:
        return None

    def embedding_ready(_settings: Settings) -> None:
        events.append("embedding")

    return WorkerRuntime(
        settings=Settings(),
        database=cast(Database, _DatabaseProbe([profile], events)),
        object_store=cast(ObjectStore, _ObjectStoreProbe(events)),
        handlers={kind: handler for kind in REQUIRED_JOB_KINDS},
        worker_id="worker-a:1",
        embedding_readiness=embedding_ready,
    )


def test_preflight_checks_database_store_profile_and_embedding_readiness() -> None:
    """Break caught: startup must not claim work before every dependency is ready."""
    events: list[str] = []

    _runtime_with_profile(_active_profile(), events).preflight()

    assert events == ["database", "object-store", "embedding"]


@pytest.mark.parametrize(
    "profile",
    [_active_profile(dimensions=3), _active_profile(provider_key="unconfigured")],
)
def test_preflight_rejects_incompatible_active_profile_before_embedding_probe(
    profile: EmbeddingProfile,
) -> None:
    """Break caught: profile dimensions and provider binding must match deployment config."""
    events: list[str] = []

    with pytest.raises(RuntimeError, match="active embedding profile"):
        _runtime_with_profile(profile, events).preflight()

    assert "embedding" not in events


class _Transaction:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __enter__(self) -> None:
        self.events.append("begin")

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.events.append("rollback" if exc_type else "commit")


class _Session:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def begin(self) -> _Transaction:
        return _Transaction(self.events)

class _Heartbeat:
    def __init__(self, *_: object, events: list[str], **__: object) -> None:
        self.events = events

    def __enter__(self) -> Self:
        self.events.append("heartbeat-start")
        return self

    def ensure_owned(self) -> None:
        self.events.append("ownership-check")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self.events.append("heartbeat-stop")


def _heartbeat_factory(events: list[str]) -> Callable[..., _Heartbeat]:
    def factory(_session_factory: object, _claim: ClaimedJob, _now: object) -> _Heartbeat:
        return _Heartbeat(events=events)

    return factory


def _claim() -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        attempt_id=uuid4(),
        org_id=uuid4(),
        project_id=uuid4(),
        job_kind=JobKind.INDEX_RESOURCE_VERSION,
        target_id=uuid4(),
        lease_owner="worker-a:1",
        lease_expires_at=datetime(2026, 8, 13, tzinfo=UTC) + timedelta(minutes=5),
    )


def test_run_once_commits_claim_before_starting_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Break caught: a claim hidden in the work transaction cannot be recovered after a crash."""
    events: list[str] = []
    claim = _claim()
    sessions = iter([_Session(events), _Session(events)])

    def claim_next_job(*_: object, **__: object) -> ClaimedJob:
        events.append("claim")
        return claim

    def handler(_session: object, _claim: ClaimedJob, _heartbeat: object) -> None:
        events.append("handler")
        events.append("finish-job")

    def finalized(*_: object, **__: object) -> None:
        events.append("finalization-check")

    monkeypatch.setattr("cairn_worker.runner.claim_next_job", claim_next_job)
    monkeypatch.setattr("cairn_worker.runner.ensure_claim_finalized", finalized)

    assert run_once(
        session_factory=lambda: next(sessions),
        worker_id=claim.lease_owner,
        handlers={kind: handler for kind in REQUIRED_JOB_KINDS},
        now=lambda: datetime(2026, 8, 13, tzinfo=UTC),
        heartbeat_factory=_heartbeat_factory(events),
    )
    assert events.index("commit") < events.index("heartbeat-start") < events.index("handler")
    assert events[-4:] == ["ownership-check", "finalization-check", "commit", "heartbeat-stop"]


def test_run_once_records_classified_handler_failure_after_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: partial handler writes must roll back before durable failure scheduling."""
    events: list[str] = []
    claim = _claim()
    sessions = iter([_Session(events), _Session(events), _Session(events)])

    def claimed(*_: object, **__: object) -> ClaimedJob:
        return claim

    monkeypatch.setattr("cairn_worker.runner.claim_next_job", claimed)

    def fail_handler(*_: object) -> None:
        events.append("handler")
        raise WorkerFailure("object_store_unavailable", "temporarily unavailable", retryable=True)

    def record_failure(*_: object, **__: object) -> None:
        events.append("fail-job")

    monkeypatch.setattr("cairn_worker.runner.fail_job", record_failure)

    assert run_once(
        session_factory=lambda: next(sessions),
        worker_id=claim.lease_owner,
        handlers={kind: fail_handler for kind in REQUIRED_JOB_KINDS},
        now=lambda: datetime(2026, 8, 13, tzinfo=UTC),
        heartbeat_factory=_heartbeat_factory(events),
    )
    assert events.index("rollback") < events.index("fail-job") < events[-1:].index("commit") + len(events) - 1


def test_run_once_records_a_bounded_failure_for_unexpected_handler_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: unexpected exceptions must not leave work leased with no failure fact."""
    events: list[str] = []
    claim = _claim()
    sessions = iter([_Session(events), _Session(events), _Session(events)])

    def claimed(*_: object, **__: object) -> ClaimedJob:
        return claim

    def broken_handler(*_: object) -> None:
        raise RuntimeError("secret provider body")

    failures: list[WorkerFailure] = []

    def record_failure(*_: object, failure: WorkerFailure, **__: object) -> None:
        failures.append(failure)

    monkeypatch.setattr("cairn_worker.runner.claim_next_job", claimed)
    monkeypatch.setattr("cairn_worker.runner.fail_job", record_failure)

    assert run_once(
        session_factory=lambda: next(sessions),
        worker_id=claim.lease_owner,
        handlers={kind: broken_handler for kind in REQUIRED_JOB_KINDS},
        now=lambda: datetime(2026, 8, 13, tzinfo=UTC),
        heartbeat_factory=_heartbeat_factory(events),
    )
    assert [(failure.code, failure.safe_detail) for failure in failures] == [
        ("parser_failed", "worker handler or parser failed")
    ]


class _StopProbe:
    def __init__(self) -> None:
        self.stopped = False
        self.waits: list[float | None] = []

    def is_set(self) -> bool:
        return self.stopped

    def set(self) -> None:
        self.stopped = True

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        self.stopped = True
        return True


def test_serve_uses_bounded_idle_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Break caught: an idle worker must re-poll promptly without spinning."""
    runtime = _runtime_with_profile(_active_profile(), [])
    stop = _StopProbe()

    def ignore_signal(_current: signal.Signals, _handler: object) -> signal.Handlers:
        return signal.SIG_DFL

    monkeypatch.setattr(runtime, "_stop", stop)
    monkeypatch.setattr(runtime, "run_once", lambda: False)
    monkeypatch.setattr("cairn_worker.runner.signal.signal", ignore_signal)

    runtime.serve()

    assert stop.waits == [1.0]
    assert stop.waits[0] is not None and 0 < stop.waits[0] <= 5


@pytest.mark.parametrize("shutdown_signal", [signal.SIGINT, signal.SIGTERM])
def test_serve_stops_on_process_shutdown_signals_and_restores_handlers(
    monkeypatch: pytest.MonkeyPatch,
    shutdown_signal: signal.Signals,
) -> None:
    """Break caught: container shutdown must stop the loop and restore process handlers."""
    runtime = _runtime_with_profile(_active_profile(), [])
    installed: dict[signal.Signals, object] = {}
    restored: list[tuple[signal.Signals, object]] = []
    previous = {signal.SIGINT: object(), signal.SIGTERM: object()}

    def set_signal(current: signal.Signals, handler: object) -> object:
        if current not in installed:
            installed[current] = handler
            return previous[current]
        restored.append((current, handler))
        return previous[current]

    def poll() -> bool:
        handler = installed[shutdown_signal]
        assert callable(handler)
        handler(shutdown_signal, None)
        return False

    monkeypatch.setattr("cairn_worker.runner.signal.signal", set_signal)
    monkeypatch.setattr(runtime, "run_once", poll)

    runtime.serve()

    assert set(installed) == {signal.SIGINT, signal.SIGTERM}
    assert restored == [
        (signal.SIGINT, previous[signal.SIGINT]),
        (signal.SIGTERM, previous[signal.SIGTERM]),
    ]
