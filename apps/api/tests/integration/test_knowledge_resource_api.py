import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from cairn_api.app import create_app
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.knowledge import repository, resource_service
from cairn_api.knowledge.models import (
    IngestionBatch,
    IngestionBatchStatus,
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobStatus,
    JobKind,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
    UploadSession,
)
from cairn_api.knowledge.object_store import ObjectStat, ObjectStoreUnavailable
from cairn_api.maintenance.upload_cleanup import run_upload_cleanup
from cairn_api.projects.models import OutboxEvent, Project
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .authorization_helpers import seed_actor
from .knowledge_helpers import (
    MemoryObjectStore,
    knowledge_client,
    knowledge_settings,
    seed_project,
)


def _seed_ready_resource(
    database: Database,
    *,
    org_id: UUID,
    project_id: UUID,
    title: str,
    created_at: datetime,
) -> tuple[UUID, UUID, list[UUID]]:
    resource_id = uuid4()
    version_id = uuid4()
    chunk_ids = [uuid4() for _ in range(3)]
    with database.session_factory.begin() as session:
        resource = KnowledgeResource(
            id=resource_id,
            org_id=org_id,
            project_id=project_id,
            title=title,
            source_type="upload",
            source_id=str(uuid4()),
            external_id=title,
            created_at=created_at,
        )
        session.add(resource)
        session.flush()
        version = KnowledgeResourceVersion(
            id=version_id,
            org_id=org_id,
            project_id=project_id,
            resource_id=resource_id,
            source_type="upload",
            source_id=resource.source_id,
            external_id=title,
            source_version=uuid4().hex,
            object_key=f"orgs/{org_id}/projects/{project_id}/resources/{version_id}",
            media_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            parser_profile="default-v1",
            chunking_profile="default-v1",
            status=ResourceVersionStatus.READY,
            created_at=created_at,
            processing_started_at=created_at,
            ready_at=created_at,
        )
        session.add(version)
        session.flush()
        resource.current_version_id = version_id
        for ordinal, chunk_id in enumerate(chunk_ids):
            session.add(
                KnowledgeChunk(
                    id=chunk_id,
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    resource_version_id=version_id,
                    ordinal=ordinal,
                    kind="text",
                    text=f"第 {ordinal + 1} 段",
                    normalized_text=f"第 {ordinal + 1} 段",
                    locator={"type": "pdf", "page": ordinal + 1},
                )
            )
        session.add(
            IngestionJob(
                org_id=org_id,
                project_id=project_id,
                job_kind=JobKind.INDEX_RESOURCE_VERSION,
                target_id=version_id,
                profile_version="default-v1",
                status=IngestionJobStatus.COMPLETED,
                attempt=1,
                max_attempts=5,
                next_attempt_at=created_at,
                completed_at=created_at,
            )
        )
    return resource_id, version_id, chunk_ids


@pytest.mark.integration
def test_resource_list_cursor_capability_detail_context_and_download(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    now = datetime(2026, 8, 13, 11, 0, tzinfo=UTC)
    first = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="甲.pdf",
        created_at=now,
    )
    second = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="乙.pdf",
        created_at=now,
    )
    store = MemoryObjectStore()
    with database.session_factory() as session:
        version = session.get(KnowledgeResourceVersion, first[1])
        assert version is not None
        store.objects[version.object_key] = ObjectStat(10, "application/pdf", "a" * 64)
    with knowledge_client(
        knowledge_settings(test_database_url, download_url_ttl_seconds=137),
        database,
        actor,
        store,
    ) as client:
        page_one = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources",
            params={"limit": 1},
        )
        page_two = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources",
            params={"limit": 1, "cursor": page_one.json()["nextCursor"]},
        )
        resource_id = UUID(page_one.json()["items"][0]["id"])
        detail = client.get(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}")
        middle_chunk_id = first[2][1] if resource_id == first[0] else second[2][1]
        context = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/"
            f"{middle_chunk_id}"
        )
        download = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download",
            follow_redirects=False,
        )
        invalid_cursor = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources",
            params={"cursor": "not-a-cursor"},
            headers={"X-Request-ID": "req-resource-invalid-cursor"},
        )
        invalid_limit = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources",
            params={"limit": 101},
            headers={"X-Request-ID": "req-resource-invalid-limit"},
        )

    assert page_one.status_code == page_two.status_code == 200
    assert page_one.json()["capabilities"] == {"canWrite": False}
    assert page_one.json()["nextCursor"] is not None
    assert page_two.json()["nextCursor"] is None
    assert page_one.json()["items"][0]["id"] != page_two.json()["items"][0]["id"]
    assert "objectKey" not in str(page_one.json())
    assert detail.status_code == 200
    assert context.status_code == 200
    assert context.json()["before"]["ordinal"] == 0
    assert context.json()["hit"]["ordinal"] == 1
    assert context.json()["after"]["ordinal"] == 2
    assert download.status_code == 307
    assert download.headers["location"].startswith("https://objects.example/")
    assert store.presigned_get_ttls == [timedelta(seconds=137)]
    assert invalid_cursor.status_code == invalid_limit.status_code == 422
    assert invalid_cursor.json() == {
        "message": "分页游标无效",
        "code": "invalid_cursor",
        "traceId": "req-resource-invalid-cursor",
    }
    assert invalid_limit.json()["traceId"] == "req-resource-invalid-limit"
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "knowledge.downloaded")
            )
            == 1
        )


@pytest.mark.integration
def test_uploaded_draft_status_is_observable_and_exhausted_failure_is_retryable(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    payload = b"%PDF-1.7\nprocessing"
    checksum = hashlib.sha256(payload).hexdigest()
    store = MemoryObjectStore()
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        created = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            json={
                "files": [
                    {
                        "fileName": "processing.pdf",
                        "mediaType": "application/pdf",
                        "sizeBytes": len(payload),
                        "sha256": checksum,
                    }
                ]
            },
        )
        assert created.status_code == 201
        upload_id = created.json()["uploads"][0]["uploadId"]
        object_key = store.presigned_keys[0]
        store.objects[object_key] = ObjectStat(
            len(payload),
            "application/pdf",
            checksum,
        )
        completed = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete"
        )
        assert completed.status_code == 200
        resource_id = UUID(completed.json()["resourceId"])
        version_id = UUID(completed.json()["resourceVersionId"])

        queued_list = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources"
        )
        queued_detail = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}"
        )
        queued_download = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download",
            follow_redirects=False,
        )
        queued_context = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{uuid4()}"
        )

        with database.session_factory.begin() as session:
            resource = session.get(KnowledgeResource, resource_id)
            version = session.get(KnowledgeResourceVersion, version_id)
            job = session.scalar(
                select(IngestionJob).where(IngestionJob.target_id == version_id)
            )
            assert resource is not None and resource.current_version_id is None
            assert version is not None and job is not None
            version.status = ResourceVersionStatus.FAILED
            version.error_code = "ingestion_retry_exhausted"
            job.status = IngestionJobStatus.FAILED
            job.attempt = job.max_attempts
            job.last_error_code = "ingestion_retry_exhausted"
            job.completed_at = datetime.now(UTC)

        failed_detail = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}"
        )
        retried = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
            f"{version_id}/retry"
        )

    assert queued_list.status_code == queued_detail.status_code == 200
    assert queued_list.json()["items"][0]["latestVersion"] == queued_detail.json()[
        "latestVersion"
    ]
    assert queued_detail.json()["latestVersion"]["id"] == str(version_id)
    assert queued_detail.json()["latestVersion"]["status"] == "queued"
    assert queued_download.status_code == queued_context.status_code == 404
    assert failed_detail.status_code == 200
    failed_version = failed_detail.json()["latestVersion"]
    assert failed_version["id"] == str(version_id)
    assert failed_version["status"] == "failed"
    assert failed_version["errorCode"] == "ingestion_retry_exhausted"
    assert failed_version["retryable"] is True
    assert retried.status_code == 200
    assert retried.json()["latestVersion"]["status"] == "queued"
    with database.session_factory() as session:
        resource = session.get(KnowledgeResource, resource_id)
        job = session.scalar(select(IngestionJob).where(IngestionJob.target_id == version_id))
        assert job is not None
        attempts = list(
            session.scalars(
                select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
            )
        )
        assert resource is not None and resource.current_version_id is None
        assert job.attempt == 0
        assert [(attempt.trigger, attempt.status) for attempt in attempts] == [
            ("manual", "queued")
        ]


@pytest.mark.integration
def test_batch_detail_contains_zip_children_and_resource_delete_is_immediate(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    batch_id = uuid4()
    parent_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            IngestionBatch(
                id=batch_id,
                org_id=actor.organization_id,
                project_id=project_id,
                created_by=actor.user_id,
                status=IngestionBatchStatus.COMPLETED_WITH_ERRORS,
                item_count=2,
                ready_count=1,
                failed_count=1,
                completed_at=datetime.now(UTC),
            )
        )
        session.flush()
        session.add_all(
            [
                IngestionItem(
                    id=parent_id,
                    org_id=actor.organization_id,
                    project_id=project_id,
                    batch_id=batch_id,
                    normalized_path="bundle.zip",
                    media_type="application/zip",
                    size_bytes=10,
                    sha256="a" * 64,
                    status=IngestionItemStatus.READY,
                    completed_at=datetime.now(UTC),
                ),
                IngestionItem(
                    org_id=actor.organization_id,
                    project_id=project_id,
                    batch_id=batch_id,
                    parent_item_id=parent_id,
                    normalized_path="unsafe.exe",
                    media_type="application/octet-stream",
                    size_bytes=1,
                    sha256="b" * 64,
                    status=IngestionItemStatus.FAILED,
                    error_code="unsupported_media_type",
                    error_detail="不支持的归档条目",
                    completed_at=datetime.now(UTC),
                ),
            ]
        )
    resource_id, _version_id, chunk_ids = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="待删除.pdf",
        created_at=datetime.now(UTC),
    )
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        batch = client.get(f"/api/v1/projects/{project_id}/knowledge/batches/{batch_id}")
        deleted = client.delete(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}")
        deleted_again = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}"
        )
        listing = client.get(f"/api/v1/projects/{project_id}/knowledge/resources")
        detail = client.get(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}")
        context = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_ids[1]}"
        )
        download = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download",
            follow_redirects=False,
        )

    assert batch.status_code == 200
    children = [item for item in batch.json()["items"] if item["parentItemId"] is not None]
    assert children[0]["errorCode"] == "unsupported_media_type"
    assert children[0]["errorDetail"] == "不支持的归档条目"
    assert deleted.status_code == deleted_again.status_code == 204
    assert listing.json()["items"] == []
    assert detail.status_code == context.status_code == download.status_code == 404


@pytest.mark.integration
@pytest.mark.parametrize(
    ("role", "permission", "can_read", "can_write"),
    [
        (MembershipRole.OWNER, None, True, True),
        (MembershipRole.ADMIN, None, True, True),
        (MembershipRole.MEMBER, "write", True, True),
        (MembershipRole.MEMBER, "read", True, False),
        (MembershipRole.MEMBER, None, False, False),
        (MembershipRole.VIEWER, "write", True, False),
    ],
)
def test_resource_routes_enforce_live_read_write_matrix(
    role: MembershipRole,
    permission: str | None,
    can_read: bool,
    can_write: bool,
    database: Database,
    test_database_url: str,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, owner, permission=None)
    actor = seed_actor(database, role, org_id=owner.organization_id)
    if permission is not None:
        with database.session_factory.begin() as session:
            session.add(
                ResourceAclEntry(
                    org_id=owner.organization_id,
                    resource_type="project",
                    resource_id=project_id,
                    principal_type="user",
                    principal_id=str(actor.user_id),
                    permission=permission,
                    granted_by_type="system",
                )
            )
    resource_id, version_id, chunk_ids = _seed_ready_resource(
        database,
        org_id=owner.organization_id,
        project_id=project_id,
        title="权限矩阵.pdf",
        created_at=datetime.now(UTC),
    )
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        listing = client.get(f"/api/v1/projects/{project_id}/knowledge/resources")
        detail = client.get(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}")
        context = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_ids[1]}"
        )
        download = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download",
            follow_redirects=False,
        )
        retry = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
            f"{version_id}/retry"
        )
        deleted = client.delete(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}")

    expected_read = 200 if can_read else 404
    assert listing.status_code == detail.status_code == context.status_code == expected_read
    assert download.status_code == (307 if can_read else 404)
    if can_read:
        assert listing.json()["capabilities"] == {"canWrite": can_write}
    expected_mutation = 409 if can_write else 404
    assert retry.status_code == expected_mutation
    assert deleted.status_code == (204 if can_write else 404)


@pytest.mark.integration
def test_resource_routes_conceal_cross_organization_identifiers(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    other = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, other, permission=None)
    resource_id, version_id, chunk_ids = _seed_ready_resource(
        database,
        org_id=other.organization_id,
        project_id=project_id,
        title="另一个租户.pdf",
        created_at=datetime.now(UTC),
    )
    batch_id = uuid4()
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        responses = [
            client.get(f"/api/v1/projects/{project_id}/knowledge/batches/{batch_id}"),
            client.get(f"/api/v1/projects/{project_id}/knowledge/resources"),
            client.get(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}"),
            client.get(
                f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/"
                f"{chunk_ids[1]}"
            ),
            client.get(
                f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download",
                follow_redirects=False,
            ),
            client.post(
                f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
                f"{version_id}/retry"
            ),
            client.delete(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}"),
        ]

    assert {response.status_code for response in responses} == {404}
    assert {response.json()["code"] for response in responses} == {"not_found"}


@pytest.mark.integration
def test_resource_routes_conceal_same_organization_cross_project_identifiers(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    route_project_id = seed_project(database, actor, permission=None)
    hidden_project_id = seed_project(database, actor, permission=None)
    hidden_batch_id = uuid4()
    with database.session_factory.begin() as session:
        session.add(
            IngestionBatch(
                id=hidden_batch_id,
                org_id=actor.organization_id,
                project_id=hidden_project_id,
                created_by=actor.user_id,
                status=IngestionBatchStatus.PENDING,
                item_count=0,
            )
        )
    resource_id, version_id, chunk_ids = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=hidden_project_id,
        title="另一个项目.pdf",
        created_at=datetime.now(UTC),
    )
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        responses = [
            client.get(
                f"/api/v1/projects/{route_project_id}/knowledge/batches/{hidden_batch_id}"
            ),
            client.get(
                f"/api/v1/projects/{route_project_id}/knowledge/resources/{resource_id}"
            ),
            client.get(
                f"/api/v1/projects/{route_project_id}/knowledge/resources/{resource_id}/chunks/"
                f"{chunk_ids[1]}"
            ),
            client.get(
                f"/api/v1/projects/{route_project_id}/knowledge/resources/{resource_id}/download",
                follow_redirects=False,
            ),
            client.post(
                f"/api/v1/projects/{route_project_id}/knowledge/resources/{resource_id}/versions/"
                f"{version_id}/retry"
            ),
            client.delete(
                f"/api/v1/projects/{route_project_id}/knowledge/resources/{resource_id}"
            ),
        ]
        route_listing = client.get(
            f"/api/v1/projects/{route_project_id}/knowledge/resources"
        )

    assert {response.status_code for response in responses} == {404}
    assert {response.json()["code"] for response in responses} == {"not_found"}
    assert route_listing.status_code == 200
    assert route_listing.json()["items"] == []
    with database.session_factory() as session:
        hidden_resource = session.get(KnowledgeResource, resource_id)
        assert hidden_resource is not None and hidden_resource.deleted_at is None


@pytest.mark.integration
def test_resource_routes_require_session_and_mutation_csrf(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    resource_id, version_id, _chunk_ids = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="安全边界.pdf",
        created_at=datetime.now(UTC),
    )
    settings = knowledge_settings(test_database_url)
    with TestClient(
        create_app(settings, database, MemoryObjectStore()),
        raise_server_exceptions=False,
    ) as client:
        unauthenticated = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources",
            headers={"X-Request-ID": "req-resource-session"},
        )
    with knowledge_client(settings, database, actor, MemoryObjectStore()) as client:
        client.headers.pop("Origin")
        client.headers.pop("X-CSRF-Token")
        retry = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
            f"{version_id}/retry",
            headers={"X-Request-ID": "req-resource-csrf-retry"},
        )
        deleted = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={"X-Request-ID": "req-resource-csrf-delete"},
        )

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["traceId"] == "req-resource-session"
    for response, trace_id in (
        (retry, "req-resource-csrf-retry"),
        (deleted, "req-resource-csrf-delete"),
    ):
        assert response.status_code == 403
        assert response.json() == {
            "message": "请求来源或 CSRF 令牌无效",
            "code": "csrf_failed",
            "traceId": trace_id,
        }
        assert response.headers["x-request-id"] == trace_id


@pytest.mark.integration
@pytest.mark.parametrize("entry_point", ["batch", "detail", "context", "download"])
def test_resource_reads_conceal_acl_revoked_between_check_and_protected_query(
    entry_point: str,
    database: Database,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, owner, permission=None)
    reader = seed_actor(database, MembershipRole.MEMBER, org_id=owner.organization_id)
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
        session.add(acl)
    resource_id, _version_id, chunk_ids = _seed_ready_resource(
        database,
        org_id=owner.organization_id,
        project_id=project_id,
        title="撤权.pdf",
        created_at=datetime.now(UTC),
    )
    with database.session_factory.begin() as session:
        batch = repository.create_batch(
            session,
            org_id=owner.organization_id,
            project_id=project_id,
            created_by=owner.user_id,
            item_count=0,
        )
        batch_id = batch.id

    original_require = AuthorizationPolicy.require_project
    revoked = False

    def require_then_revoke(
        policy: AuthorizationPolicy,
        identity: IdentityContextResponse,
        requested_project_id: UUID,
        required: ProjectPermission,
        *,
        for_update: bool = False,
    ) -> Project:
        nonlocal revoked
        project = original_require(
            policy,
            identity,
            requested_project_id,
            required,
            for_update=for_update,
        )
        if not revoked:
            with database.session_factory.begin() as session:
                entry = session.scalar(
                    select(ResourceAclEntry).where(ResourceAclEntry.id == acl.id)
                )
                assert entry is not None
                entry.revoked_at = datetime.now(UTC)
                entry.revoked_by_type = "system"
            revoked = True
        return project

    monkeypatch.setattr(
        AuthorizationPolicy,
        "require_project",
        require_then_revoke,
    )
    path = {
        "batch": f"/api/v1/projects/{project_id}/knowledge/batches/{batch_id}",
        "detail": f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
        "context": (
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/"
            f"{chunk_ids[1]}"
        ),
        "download": (
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download"
        ),
    }[entry_point]
    trace_id = f"req-acl-race-{entry_point}"
    with knowledge_client(
        knowledge_settings(test_database_url), database, reader, MemoryObjectStore()
    ) as client:
        response = client.get(
            path,
            headers={"X-Request-ID": trace_id},
            follow_redirects=False,
        )

    assert response.status_code == 404
    assert response.json() == {
        "message": "资源不存在",
        "code": "not_found",
        "traceId": trace_id,
    }
    assert response.headers["x-request-id"] == trace_id
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"


@pytest.mark.integration
def test_upload_cleanup_expires_pending_and_preserves_completed_or_referenced_objects(
    database: Database,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    now = datetime(2026, 8, 13, 15, 0, tzinfo=UTC)
    store = MemoryObjectStore(now=now)
    with database.session_factory.begin() as session:
        expired_batch = repository.create_batch(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            created_by=actor.user_id,
            item_count=1,
        )
        expired = repository.create_upload_session(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            batch_id=expired_batch.id,
            file_name="expired.pdf",
            normalized_path="expired.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256="a" * 64,
            object_key="uploads/expired",
            expires_at=now.replace(hour=14),
        )
        completed_batch = repository.create_batch(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            created_by=actor.user_id,
            item_count=1,
        )
        completed = repository.create_upload_session(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            batch_id=completed_batch.id,
            file_name="completed.pdf",
            normalized_path="completed.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256="b" * 64,
            object_key="uploads/completed",
            expires_at=now.replace(hour=14),
        )
        completed.upload.completed_at = now
        completed.item.status = IngestionItemStatus.READY
        completed.item.completed_at = now
        repository.refresh_batch_summary(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            batch_id=completed_batch.id,
            now=now,
        )
        referenced_batch = repository.create_batch(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            created_by=actor.user_id,
            item_count=1,
        )
        referenced = repository.create_upload_session(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            batch_id=referenced_batch.id,
            file_name="referenced.pdf",
            normalized_path="referenced.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256="c" * 64,
            object_key="uploads/referenced",
            expires_at=now.replace(hour=14),
        )
        repository.mark_item_failed(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            upload=referenced.upload,
            item=referenced.item,
            error_code="upload_expired",
            failed_at=now,
            abandon_upload=True,
        )
        resource_id, version_id, _chunk_ids = _seed_ready_resource(
            database,
            org_id=actor.organization_id,
            project_id=project_id,
            title="引用.pdf",
            created_at=now,
        )
        del resource_id
        version = session.get(KnowledgeResourceVersion, version_id)
        assert version is not None
        version.object_key = referenced.upload.object_key

    for object_key, checksum in (
        (expired.upload.object_key, "a" * 64),
        (completed.upload.object_key, "b" * 64),
        (referenced.upload.object_key, "c" * 64),
    ):
        store.objects[object_key] = ObjectStat(1, "application/pdf", checksum)

    result = run_upload_cleanup(
        database=database,
        object_store=store,
        now=lambda: now,
        limit=10,
    )

    assert result.uploads_expired == 1
    assert result.objects_deleted == 1
    assert result.objects_preserved == 1
    assert set(store.objects) == {"uploads/completed", "uploads/referenced"}
    with database.session_factory() as session:
        expired_upload = session.get(UploadSession, expired.upload.id)
        expired_item = session.get(IngestionItem, expired.item.id)
        refreshed_batch = session.get(IngestionBatch, expired_batch.id)
        assert expired_upload is None
        assert expired_item is not None
        assert expired_item.status == IngestionItemStatus.FAILED
        assert expired_item.error_code == "upload_expired"
        assert refreshed_batch is not None
        assert refreshed_batch.status == IngestionBatchStatus.FAILED
        assert refreshed_batch.failed_count == 1
        audits = list(
            session.scalars(
                select(AuditLog).where(AuditLog.action == "knowledge.upload_expired")
            )
        )
        events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "knowledge.upload_expired"
                )
            )
        )
        assert len(audits) == len(events) == 1
        assert audits[0].actor_type == "system"
        assert audits[0].actor_id is None
        assert audits[0].resource_id == expired.upload.id
        assert events[0].aggregate_id == project_id

    repeated = run_upload_cleanup(
        database=database,
        object_store=store,
        now=lambda: now,
        limit=10,
    )
    assert repeated.uploads_expired == 0
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "knowledge.upload_expired")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "knowledge.upload_expired")
            )
            == 1
        )


@pytest.mark.integration
def test_upload_expiry_rolls_back_state_and_audit_when_outbox_write_fails(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    now = datetime(2026, 8, 13, 15, 30, tzinfo=UTC)
    with database.session_factory.begin() as session:
        batch = repository.create_batch(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            created_by=actor.user_id,
            item_count=1,
        )
        record = repository.create_upload_session(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            batch_id=batch.id,
            file_name="rollback.pdf",
            normalized_path="rollback.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256="d" * 64,
            object_key="uploads/rollback",
            expires_at=now - timedelta(minutes=1),
        )
        upload_id = record.upload.id
        item_id = record.item.id
        batch_id = batch.id

    monkeypatch.setattr(
        repository,
        "add_project_outbox_event",
        Mock(side_effect=RuntimeError("outbox unavailable")),
    )
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        run_upload_cleanup(
            database=database,
            object_store=MemoryObjectStore(now=now),
            now=lambda: now,
        )

    with database.session_factory() as session:
        upload = session.get(UploadSession, upload_id)
        item = session.get(IngestionItem, item_id)
        batch = session.get(IngestionBatch, batch_id)
        assert upload is not None and upload.abandoned_at is None
        assert item is not None and item.status == IngestionItemStatus.AWAITING_UPLOAD
        assert batch is not None and batch.status == IngestionBatchStatus.PENDING
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "knowledge.upload_expired")
            )
            == 0
        )


@pytest.mark.integration
def test_upload_cleanup_advances_past_each_bounded_orphan_window(
    database: Database,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    now = datetime(2026, 8, 13, 16, 0, tzinfo=UTC)
    store = MemoryObjectStore(now=now)
    upload_ids: list[UUID] = []
    with database.session_factory.begin() as session:
        for index in range(2):
            batch = repository.create_batch(
                session,
                org_id=actor.organization_id,
                project_id=project_id,
                created_by=actor.user_id,
                item_count=1,
            )
            record = repository.create_upload_session(
                session,
                org_id=actor.organization_id,
                project_id=project_id,
                batch_id=batch.id,
                file_name=f"orphan-{index}.pdf",
                normalized_path=f"orphan-{index}.pdf",
                media_type="application/pdf",
                size_bytes=1,
                sha256=f"{index + 1:x}" * 64,
                object_key=f"uploads/orphan-{index}",
                expires_at=now + timedelta(minutes=15),
            )
            repository.mark_item_failed(
                session,
                org_id=actor.organization_id,
                project_id=project_id,
                upload=record.upload,
                item=record.item,
                error_code="upload_expired",
                failed_at=now + timedelta(seconds=index),
                abandon_upload=True,
            )
            upload_ids.append(record.upload.id)
            store.objects[record.upload.object_key] = ObjectStat(
                1,
                "application/pdf",
                record.upload.sha256,
            )

    first = run_upload_cleanup(
        database=database,
        object_store=store,
        now=lambda: now,
        limit=1,
    )
    second = run_upload_cleanup(
        database=database,
        object_store=store,
        now=lambda: now,
        limit=1,
    )

    assert first.objects_deleted == second.objects_deleted == 1
    assert store.objects == {}
    with database.session_factory() as session:
        assert [session.get(UploadSession, upload_id) for upload_id in upload_ids] == [
            None,
            None,
        ]
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionItem)
                .where(IngestionItem.project_id == project_id)
            )
            == 2
        )


@pytest.mark.integration
def test_download_maps_object_store_outage_without_audit_side_effect(
    database: Database,
    test_database_url: str,
) -> None:
    class UnavailableStore(MemoryObjectStore):
        def presign_get(
            self,
            *,
            object_key: str,
            download_name: str,
            expires_in: timedelta,
        ) -> str:
            del object_key, download_name, expires_in
            raise ObjectStoreUnavailable()

    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    resource_id, _version_id, _chunk_ids = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="存储故障.pdf",
        created_at=datetime.now(UTC),
    )
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, UnavailableStore()
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download",
            headers={"X-Request-ID": "req-download-store-down"},
            follow_redirects=False,
        )

    assert response.status_code == 503
    assert response.json() == {
        "message": "对象存储暂时不可用",
        "code": "object_store_unavailable",
        "traceId": "req-download-store-down",
    }
    assert response.headers["x-request-id"] == "req-download-store-down"
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "knowledge.downloaded")
            )
            == 0
        )


@pytest.mark.integration
def test_delete_unexpected_audit_failure_rolls_back_and_returns_traced_500(
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    resource_id, _version_id, _chunk_ids = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="回滚.pdf",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        resource_service,
        "add_audit_log",
        Mock(side_effect=RuntimeError("audit unavailable")),
    )
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={"X-Request-ID": "req-delete-audit-failure"},
        )

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器内部错误",
        "code": "internal_error",
        "traceId": "req-delete-audit-failure",
    }
    assert response.headers["x-request-id"] == "req-delete-audit-failure"
    with database.session_factory() as session:
        resource = session.get(KnowledgeResource, resource_id)
        assert resource is not None and resource.deleted_at is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "knowledge.resource_deleted")
            )
            == 0
        )
