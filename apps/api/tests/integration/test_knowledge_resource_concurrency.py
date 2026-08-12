import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.knowledge.models import (
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobStatus,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
)
from cairn_api.projects.models import OutboxEvent
from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project


@pytest.mark.integration
def test_concurrent_manual_retry_creates_one_attempt_and_one_event(
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    resource_id = uuid4()
    version_id = uuid4()
    job_id = uuid4()
    now = datetime.now(UTC)
    with database.session_factory.begin() as session:
        resource = KnowledgeResource(
            id=resource_id,
            org_id=actor.organization_id,
            project_id=project_id,
            title="retry.pdf",
            source_type="upload",
            source_id=str(uuid4()),
            external_id="retry.pdf",
            current_version_id=None,
        )
        session.add(resource)
        session.flush()
        session.add(
            KnowledgeResourceVersion(
                id=version_id,
                org_id=actor.organization_id,
                project_id=project_id,
                resource_id=resource_id,
                source_type="upload",
                source_id=resource.source_id,
                external_id="retry.pdf",
                source_version="a" * 64,
                object_key=f"retry/{version_id}",
                media_type="application/pdf",
                size_bytes=1,
                sha256="a" * 64,
                parser_profile="default-v1",
                chunking_profile="default-v1",
                status=ResourceVersionStatus.FAILED,
                error_code="embedding_unavailable",
            )
        )
        session.flush()
        resource.current_version_id = version_id
        session.add(
            IngestionJob(
                id=job_id,
                org_id=actor.organization_id,
                project_id=project_id,
                job_kind=JobKind.INDEX_RESOURCE_VERSION,
                target_id=version_id,
                profile_version="default-v1",
                status=IngestionJobStatus.FAILED,
                attempt=5,
                max_attempts=5,
                next_attempt_at=now,
                last_error_code="embedding_unavailable",
                completed_at=now,
            )
        )

    settings = knowledge_settings(test_database_url)
    first_locked = threading.Event()
    release_first = threading.Event()
    lock_count = 0
    count_lock = threading.Lock()
    original = AuthorizationPolicy.require_project

    def pause_first_lock(*args: object, **kwargs: object) -> object:
        nonlocal lock_count
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        if kwargs.get("for_update"):
            with count_lock:
                lock_count += 1
                current = lock_count
            if current == 1:
                first_locked.set()
                assert release_first.wait(timeout=10)
        return result

    monkeypatch.setattr(AuthorizationPolicy, "require_project", pause_first_lock)
    path = (
        f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
        f"{version_id}/retry"
    )
    with (
        knowledge_client(settings, database, actor, MemoryObjectStore()) as first_client,
        knowledge_client(settings, database, actor, MemoryObjectStore()) as second_client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first_future = executor.submit(first_client.post, path)
        assert first_locked.wait(timeout=10)
        second_future = executor.submit(second_client.post, path)
        release_first.set()
        first = first_future.result(timeout=10)
        second = second_future.result(timeout=10)

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionJobAttempt)
                .where(IngestionJobAttempt.job_id == job_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "knowledge.version_retried")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "knowledge.version_retried")
            )
            == 1
        )


@pytest.mark.integration
def test_resource_list_acl_filter_blocks_page_after_concurrent_revocation(
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, owner, permission=None)
    reader = seed_actor(database, MembershipRole.MEMBER, org_id=owner.organization_id)
    resource_id = uuid4()
    with database.session_factory.begin() as session:
        acl = ResourceAclEntry(
            org_id=owner.organization_id,
            resource_type="project",
            resource_id=project_id,
            principal_type="user",
            principal_id=str(reader.user_id),
            permission="read",
            granted_by_type="system",
        )
        session.add_all(
            [
                acl,
                KnowledgeResource(
                    id=resource_id,
                    org_id=owner.organization_id,
                    project_id=project_id,
                    title="不可泄露.pdf",
                    source_type="upload",
                    source_id=str(uuid4()),
                    external_id="不可泄露.pdf",
                ),
            ]
        )

    filter_ready = threading.Event()
    release_filter = threading.Event()
    original = AuthorizationPolicy.project_filter

    def pause_acl_filter(
        self: AuthorizationPolicy,
        identity: IdentityContextResponse,
        required: ProjectPermission,
        resource_column: ColumnElement[UUID],
    ) -> ColumnElement[bool]:
        clause = original(self, identity, required, resource_column)
        filter_ready.set()
        assert release_filter.wait(timeout=10)
        return clause

    monkeypatch.setattr(AuthorizationPolicy, "project_filter", pause_acl_filter)
    with (
        knowledge_client(
            knowledge_settings(test_database_url),
            database,
            reader,
            MemoryObjectStore(),
        ) as client,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        future = executor.submit(
            client.get,
            f"/api/v1/projects/{project_id}/knowledge/resources",
        )
        assert filter_ready.wait(timeout=10)
        with database.session_factory.begin() as session:
            entry = session.scalar(select(ResourceAclEntry).where(ResourceAclEntry.id == acl.id))
            assert entry is not None
            entry.revoked_at = datetime.now(UTC)
            entry.revoked_by_type = "system"
        release_filter.set()
        response = future.result(timeout=10)

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["capabilities"] == {"canWrite": False}
