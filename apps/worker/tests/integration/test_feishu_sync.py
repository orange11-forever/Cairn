import hashlib
from datetime import UTC, datetime
from typing import Any, Self
from uuid import uuid4

import pytest
from cairn_api.auth.models import User
from cairn_api.knowledge.models import (
    EmbeddingProfile,
    EmbeddingProfileStatus,
    IngestionJob,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
)
from cairn_api.knowledge.object_store import ObjectStoreUnavailable
from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_worker.feishu import FeishuDocumentSnapshot
from cairn_worker.feishu_sync import build_feishu_sync_handler
from cairn_worker.leases import ClaimedJob
from cairn_worker.runner import run_once
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from .conftest import seed_job


class _Client:
    def __init__(self, after_read: Any = None) -> None:
        self.after_read = after_read

    def read_document(self, document_id: str) -> FeishuDocumentSnapshot:
        content = "Durable Feishu snapshot"
        snapshot = FeishuDocumentSnapshot(
            document_id=document_id,
            revision_id=12,
            title="Synced handbook",
            content=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        )
        if self.after_read is not None:
            self.after_read()
        return snapshot


class _Resolver:
    def __init__(self, after_read: Any = None) -> None:
        self.calls = 0
        self.after_read = after_read

    def create_client(self, *, org_id: object, credential_ref: str) -> _Client:
        assert org_id and credential_ref == "sync_credential"
        self.calls += 1
        return _Client(self.after_read)


class _Store:
    def __init__(self, *, fail_after_write: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_after_write = fail_after_write

    def put_object(self, *, object_key: str, source: Any, **_kwargs: Any) -> None:
        self.objects[object_key] = source.read()
        if self.fail_after_write:
            raise ObjectStoreUnavailable()

    def delete_object(self, *, object_key: str) -> None:
        self.objects.pop(object_key, None)


class _Heartbeat:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def ensure_owned(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback


@pytest.mark.integration
@pytest.mark.parametrize(
    "scenario", ["success", "disabled", "disable_during_read", "store_failure"]
)
def test_feishu_sync_persists_snapshot_and_rejects_disabled_before_io(
    migrated_engine: Engine,
    scenario: str,
) -> None:
    disabled = scenario == "disabled"
    now = datetime.now(UTC)
    sync_id, user_id, source_id = uuid4(), uuid4(), uuid4()
    job_id, org_id, project_id = seed_job(
        migrated_engine,
        job_kind=JobKind.SYNC_FEISHU_SOURCE,
        target_id=sync_id,
        now=now,
    )
    with Session(migrated_engine) as session, session.begin():
        sync_job = session.get(IngestionJob, job_id)
        assert sync_job is not None
        sync_job.profile_version = "feishu-sync-v1"
        session.add(
            User(
                id=user_id,
                email=f"sync-{user_id}@example.com",
                normalized_email=f"sync-{user_id}@example.com",
                password_hash="test-only",
            )
        )
        session.add(
            KnowledgeSource(
                id=source_id,
                org_id=org_id,
                project_id=project_id,
                name="Fallback",
                external_id="DocSync1",
                credential_ref="sync_credential",
                access_policy="project_members",
                status="disabled" if disabled else "configured",
                disabled_at=now if disabled else None,
            )
        )
        session.flush()
        session.add(
            KnowledgeSourceSync(
                id=sync_id,
                org_id=org_id,
                project_id=project_id,
                source_id=source_id,
                requested_by=user_id,
            )
        )
        profile = session.scalar(
            select(EmbeddingProfile).where(
                EmbeddingProfile.org_id.is_(None),
                EmbeddingProfile.status == EmbeddingProfileStatus.ACTIVE,
            )
        )
        if profile is None:
            session.add(
                EmbeddingProfile(
                    id=uuid4(),
                    org_id=None,
                    provider_key="default",
                    model="text-embedding-v4",
                    dimensions=1024,
                    distance_metric="cosine",
                    chunking_config={"maxCodepoints": 1800, "overlapCodepoints": 180},
                    index_config={"strategy": "exact", "candidateLimit": 50},
                    version="default-v1",
                    status=EmbeddingProfileStatus.ACTIVE,
                )
            )
    store = _Store(fail_after_write=scenario == "store_failure")
    def disable_during_read() -> None:
        with Session(migrated_engine) as callback_session, callback_session.begin():
            source = callback_session.get(KnowledgeSource, source_id)
            assert source is not None
            source.status = "disabled"
            source.disabled_at = now

    resolver = _Resolver(disable_during_read if scenario == "disable_during_read" else None)
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    handler = build_feishu_sync_handler(
        object_store=store,
        resolver=resolver,  # type: ignore[arg-type]
        now=lambda: now,
    )

    def noop(_session: Any, _claim: ClaimedJob, _heartbeat: Any) -> None:
        return None

    assert run_once(
        session_factory=factory,
        worker_id="sync-worker:1",
        handlers={
            JobKind.SYNC_FEISHU_SOURCE: handler,
            JobKind.EXPAND_ARCHIVE: noop,
            JobKind.INDEX_RESOURCE_VERSION: noop,
        },
        now=lambda: now,
        heartbeat_factory=_Heartbeat,
    )

    with Session(migrated_engine) as session:
        sync = session.get(KnowledgeSourceSync, sync_id)
        sync_job = session.get(IngestionJob, job_id)
        if disabled:
            assert sync_job is not None and sync_job.status == "failed"
            assert sync_job.last_error_code == "parser_failed"
            assert resolver.calls == 0
            assert store.objects == {}
            return
        if scenario == "disable_during_read":
            assert sync_job is not None and sync_job.status == "failed"
            assert sync_job.last_error_code == "parser_failed"
            assert resolver.calls == 1
            assert store.objects == {}
            return
        if scenario == "store_failure":
            assert sync_job is not None and sync_job.status == "queued"
            assert sync_job.last_error_code == "object_store_unavailable"
            assert resolver.calls == 1
            assert store.objects == {}
            assert session.scalar(select(KnowledgeResource)) is None
            assert session.scalar(select(KnowledgeResourceVersion)) is None
            return
        resource = session.scalar(select(KnowledgeResource))
        version = session.scalar(select(KnowledgeResourceVersion))
        index_job = session.scalar(
            select(IngestionJob).where(IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION)
        )
    assert resource is not None and version is not None
    assert sync_job is not None and sync_job.status == "completed"
    assert sync is not None and sync.resource_id == resource.id
    assert sync.resource_version_id == version.id
    assert index_job is not None and index_job.target_id == version.id
    assert next(iter(store.objects.values())) == b"Durable Feishu snapshot"
