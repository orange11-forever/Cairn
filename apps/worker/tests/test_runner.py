from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Self, cast
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
    ensure_complete_handlers,
    main,
    run_once,
    validate_worker_id,
)


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

    def handler(*_: object) -> None:
        events.append("handler")

    monkeypatch.setattr("cairn_worker.runner.claim_next_job", claim_next_job)

    assert run_once(
        session_factory=lambda: next(sessions),
        worker_id=claim.lease_owner,
        handlers={kind: handler for kind in REQUIRED_JOB_KINDS},
        now=lambda: datetime(2026, 8, 13, tzinfo=UTC),
        heartbeat_factory=_heartbeat_factory(events),
    )
    assert events.index("commit") < events.index("heartbeat-start") < events.index("handler")
    assert events[-3:] == ["ownership-check", "commit", "heartbeat-stop"]


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
        ("parser_failed", "unexpected worker handler failure")
    ]
