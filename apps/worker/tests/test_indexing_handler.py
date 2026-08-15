import hashlib
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any, BinaryIO, cast
from uuid import uuid4

import cairn_worker.indexing as indexing_module
import pytest
from cairn_api.knowledge.models import JobKind
from cairn_api.knowledge.object_store import ObjectNotFound, ObjectStoreUnavailable
from cairn_api.knowledge.schemas import TextLocator
from cairn_worker.chunking import ChunkDraft
from cairn_worker.errors import WorkerFailure
from cairn_worker.indexing import IndexingContext, build_index_handler
from cairn_worker.leases import ClaimedJob
from cairn_worker.parsers import BlockKind

NOW = datetime(2026, 8, 15, 8, tzinfo=UTC)


class _Heartbeat:
    def __init__(self) -> None:
        self.checks = 0

    def ensure_owned(self) -> None:
        self.checks += 1


class _Store:
    def __init__(self, value: bytes | Exception) -> None:
        self.value = value
        self.opened: list[str] = []

    @contextmanager
    def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:
        self.opened.append(object_key)
        if isinstance(self.value, Exception):
            raise self.value
        yield BytesIO(self.value)


class _EmbeddingClient:
    provider_key = "configured-provider"
    model = "configured-model"
    dimensions = 1024

    def __init__(self, maximum_batch_size: int = 2) -> None:
        self.maximum_batch_size = maximum_batch_size
        self.calls: list[list[str]] = []
        self.failure: WorkerFailure | None = None

    def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(inputs))
        if self.failure is not None:
            raise self.failure
        return [[float(len(self.calls) + index)] * 1024 for index in range(len(inputs))]


def _claim(*, kind: JobKind = JobKind.INDEX_RESOURCE_VERSION) -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        attempt_id=uuid4(),
        org_id=uuid4(),
        project_id=uuid4(),
        job_kind=kind,
        target_id=uuid4(),
        lease_owner="worker-a:1",
        lease_expires_at=NOW,
    )


def _version(content: bytes, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "object_key": "orgs/o/projects/p/source.txt",
        "media_type": "text/plain",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _profile(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "provider_key": "configured-provider",
        "model": "configured-model",
        "dimensions": 1024,
        "distance_metric": "cosine",
        "chunking_config": {"maxCodepoints": 8, "overlapCodepoints": 0},
        "index_config": {"strategy": "exact", "candidateLimit": 50},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _context(store: _Store, client: _EmbeddingClient) -> IndexingContext:
    return IndexingContext(
        session=object(),
        heartbeat=_Heartbeat(),
        object_store=store,
        embedding_client=client,
        now=lambda: NOW,
    )


def test_handler_factory_passes_runner_owned_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: runtime registration must not construct per-attempt stores or clients."""
    store = _Store(b"source")
    client = _EmbeddingClient()
    heartbeat = _Heartbeat()
    session = object()
    claim = _claim()
    observed: list[tuple[ClaimedJob, IndexingContext]] = []

    def handle(value: ClaimedJob, context: IndexingContext) -> None:
        observed.append((value, context))

    monkeypatch.setattr(indexing_module, "handle_index_resource_version", handle)

    build_index_handler(store, client, lambda: NOW)(session, claim, heartbeat)

    assert len(observed) == 1
    assert observed[0][0] is claim
    assert observed[0][1].session is session
    assert observed[0][1].object_store is store
    assert observed[0][1].embedding_client is client
    assert observed[0][1].heartbeat is heartbeat


def test_prepare_document_selects_parser_and_task_10_chunk_configuration() -> None:
    """Break caught: indexing must preserve parser locators and active-profile chunk limits."""
    content = b"Alpha beta gamma"
    store = _Store(content)
    context = _context(store, _EmbeddingClient())

    drafts = indexing_module._prepare_document(  # pyright: ignore[reportPrivateUsage]
        cast(Any, _version(content)), cast(Any, _profile()), context
    )

    assert [draft.text for draft in drafts] == ["Alpha", "beta", "gamma"]
    assert [draft.ordinal for draft in drafts] == [0, 1, 2]
    assert all(draft.kind == BlockKind.TEXT for draft in drafts)
    assert [draft.locator.model_dump(by_alias=True) for draft in drafts] == [
        {"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 1},
    ] * 3
    assert store.opened == ["orgs/o/projects/p/source.txt"]
    assert cast(_Heartbeat, context.heartbeat).checks >= 2


@pytest.mark.parametrize(
    ("store_value", "overrides", "expected_code", "retryable"),
    [
        (ObjectNotFound("secret"), {}, "upload_object_missing", True),
        (ObjectStoreUnavailable("secret"), {}, "object_store_unavailable", True),
        (b"actual", {"size_bytes": 1}, "upload_size_mismatch", False),
        (b"actual", {"sha256": "0" * 64}, "upload_checksum_mismatch", False),
    ],
)
def test_prepare_document_translates_object_integrity_failures(
    store_value: bytes | Exception,
    overrides: dict[str, object],
    expected_code: str,
    retryable: bool,
) -> None:
    """Break caught: immutable-object failures must use stable bounded classifications."""
    expected_content = b"actual"
    context = _context(_Store(store_value), _EmbeddingClient())

    with pytest.raises(WorkerFailure) as raised:
        indexing_module._prepare_document(  # pyright: ignore[reportPrivateUsage]
            cast(Any, _version(expected_content, **overrides)),
            cast(Any, _profile()),
            context,
        )

    assert (raised.value.code, raised.value.retryable) == (expected_code, retryable)
    assert "secret" not in repr(raised.value)
    assert "actual" not in repr(raised.value)


@pytest.mark.parametrize(
    "override",
    [
        {"provider_key": "wrong"},
        {"model": "wrong"},
        {"dimensions": 3},
        {"distance_metric": "euclidean"},
        {"chunking_config": {"maxCodepoints": 0, "overlapCodepoints": 0}},
        {"index_config": {"strategy": "hnsw", "candidateLimit": 50}},
    ],
)
def test_profile_contract_is_validated_before_object_or_provider_work(
    override: dict[str, object],
) -> None:
    """Break caught: a switched or incompatible Profile must not index with deployed settings."""
    store = _Store(b"source")
    client = _EmbeddingClient()

    with pytest.raises(WorkerFailure) as raised:
        indexing_module._validate_profile(  # pyright: ignore[reportPrivateUsage]
            cast(Any, _profile(**override)), client
        )

    assert (raised.value.code, raised.value.retryable) == ("parser_failed", True)
    assert store.opened == []
    assert client.calls == []


def test_embedding_batches_are_bounded_ordered_and_heartbeat_checked() -> None:
    """Break caught: all chunks must receive vectors in ordinal order without oversized calls."""
    client = _EmbeddingClient(maximum_batch_size=2)
    heartbeat = _Heartbeat()
    drafts = [
        ChunkDraft(
            ordinal=index,
            kind=BlockKind.TEXT,
            text=f"source-{index}",
            normalized_text=f"source-{index}",
            locator=TextLocator(type="text", lineStart=1, lineEnd=1),
        )
        for index in range(5)
    ]

    batches = list(
        indexing_module._embedding_batches(  # pyright: ignore[reportPrivateUsage]
            drafts, client, heartbeat
        )
    )

    assert client.calls == [["source-0", "source-1"], ["source-2", "source-3"], ["source-4"]]
    assert [offset for offset, _vectors in batches] == [0, 2, 4]
    vectors = [vector for _offset, batch in batches for vector in batch]
    assert [vector[0] for vector in vectors] == [1.0, 2.0, 2.0, 3.0, 3.0]
    assert heartbeat.checks == 6


def test_provider_failure_propagates_without_source_or_secret_echo() -> None:
    """Break caught: Provider classification must survive orchestration without leaking input."""
    client = _EmbeddingClient()
    client.failure = WorkerFailure.for_code("embedding_unavailable", "Bearer secret-source")
    heartbeat = _Heartbeat()
    drafts = [
        ChunkDraft(
            ordinal=0,
            kind=BlockKind.TEXT,
            text="private source text",
            normalized_text="private source text",
            locator=TextLocator(type="text", lineStart=1, lineEnd=1),
        )
    ]

    with pytest.raises(WorkerFailure) as raised:
        list(
            indexing_module._embedding_batches(  # pyright: ignore[reportPrivateUsage]
                drafts, client, heartbeat
            )
        )

    assert raised.value.code == "embedding_unavailable"
    assert "secret-source" not in repr(raised.value)
    assert "private source text" not in repr(raised.value)


@pytest.mark.parametrize(
    ("vector", "expected_code", "retryable"),
    [
        ([0.0] * 3, "embedding_dimension_mismatch", False),
        ([0.0] * 1023 + [True], "embedding_unavailable", True),
    ],
    ids=["dimension", "boolean"],
)
def test_orchestration_revalidates_vectors_from_any_embedding_client(
    vector: list[float], expected_code: str, retryable: bool
) -> None:
    """Break caught: alternate protocol implementations must not bypass vector persistence safety."""

    class VectorClient(_EmbeddingClient):
        def embed(self, inputs: Sequence[str]) -> list[list[float]]:
            del inputs
            return [vector]

    client = VectorClient()
    drafts = [
        ChunkDraft(
            ordinal=0,
            kind=BlockKind.TEXT,
            text="source",
            normalized_text="source",
            locator=TextLocator(type="text", lineStart=1, lineEnd=1),
        )
    ]

    with pytest.raises(WorkerFailure) as raised:
        list(
            indexing_module._embedding_batches(  # pyright: ignore[reportPrivateUsage]
                drafts, client, _Heartbeat()
            )
        )

    assert (raised.value.code, raised.value.retryable) == (expected_code, retryable)


def test_wrong_job_kind_fails_before_database_or_external_work() -> None:
    """Break caught: an index handler must reject a cross-kind claim before side effects."""
    context = _context(_Store(b"source"), _EmbeddingClient())

    with pytest.raises(WorkerFailure) as raised:
        indexing_module.handle_index_resource_version(_claim(kind=JobKind.EXPAND_ARCHIVE), context)

    assert raised.value.code == "parser_failed"
    assert cast(_Store, context.object_store).opened == []
    assert cast(_EmbeddingClient, context.embedding_client).calls == []
