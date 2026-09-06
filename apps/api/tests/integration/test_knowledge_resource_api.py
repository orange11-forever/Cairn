import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from cairn_api.app import create_app
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.errors import ErrorBody
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
from cairn_api.knowledge.schemas import KnowledgeResourceResponse, KnowledgeVersionResponse
from cairn_api.maintenance.upload_cleanup import run_upload_cleanup
from cairn_api.projects.models import OutboxEvent, Project
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from .authorization_helpers import APP_ORIGIN, seed_actor
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


def _assert_detail_boundary(
    response: Response,
    *,
    request_id: str,
    status_code: int,
) -> None:
    assert response.status_code == status_code
    assert response.headers["x-request-id"] == request_id
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["access-control-allow-origin"] == APP_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert {
        value.strip().lower()
        for value in response.headers["access-control-expose-headers"].split(",")
    } == {"retry-after", "x-request-id"}


def _assert_detail_error(
    response: Response,
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
) -> None:
    _assert_detail_boundary(response, request_id=request_id, status_code=status_code)
    body = response.json()
    assert set(body) == {"message", "code", "traceId"}
    assert ErrorBody.model_validate({
        "message": body["message"],
        "code": body["code"],
        "trace_id": body["traceId"],
    }).model_dump(by_alias=True, mode="json") == body
    assert body == {"message": message, "code": code, "traceId": request_id}


@pytest.mark.integration
def test_resource_detail_get_matches_schema_and_protected_headers(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, version_id, _chunk_ids = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="详情边界.pdf",
        created_at=datetime(2026, 9, 6, 1, 0, tzinfo=UTC),
    )
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={"X-Request-ID": "req-resource-detail-success"},
        )

    _assert_detail_boundary(
        response,
        request_id="req-resource-detail-success",
        status_code=200,
    )
    body = response.json()
    assert set(body) == {"id", "title", "sourceType", "createdAt", "updatedAt", "latestVersion"}
    assert body["id"] == str(resource_id)
    assert isinstance(body["latestVersion"], dict)
    version_body = body["latestVersion"]
    assert set(version_body) == {
        "id", "sourceType", "mediaType", "sizeBytes", "sha256", "status", "errorCode",
        "retryable", "createdAt", "processingStartedAt", "readyAt",
    }
    version = KnowledgeVersionResponse.model_validate({
        "id": version_body["id"],
        "source_type": version_body["sourceType"],
        "media_type": version_body["mediaType"],
        "size_bytes": version_body["sizeBytes"],
        "sha256": version_body["sha256"],
        "status": version_body["status"],
        "error_code": version_body["errorCode"],
        "retryable": version_body["retryable"],
        "created_at": version_body["createdAt"],
        "processing_started_at": version_body["processingStartedAt"],
        "ready_at": version_body["readyAt"],
    })
    parsed = KnowledgeResourceResponse.model_validate({
        "id": body["id"],
        "title": body["title"],
        "source_type": body["sourceType"],
        "created_at": body["createdAt"],
        "updated_at": body["updatedAt"],
        "latest_version": version,
    })
    assert parsed.id == resource_id
    assert version.id == version_id
    assert "objectKey" not in response.text


@pytest.mark.integration
def test_resource_detail_validation_auth_and_not_found_are_safe_and_traced(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    settings = knowledge_settings(test_database_url)
    with knowledge_client(settings, database, actor, MemoryObjectStore()) as client:
        validation = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/not-a-uuid",
            headers={"X-Request-ID": "req-resource-detail-validation"},
        )
        missing = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{uuid4()}",
            headers={"X-Request-ID": "req-resource-detail-missing"},
        )
    with TestClient(
        create_app(settings, database, MemoryObjectStore()), raise_server_exceptions=False
    ) as client:
        unauthenticated = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{uuid4()}",
            headers={"Origin": APP_ORIGIN, "X-Request-ID": "req-resource-detail-auth"},
        )

    _assert_detail_error(
        validation,
        request_id="req-resource-detail-validation",
        status_code=422,
        code="validation_error",
        message="请求参数无效",
    )
    _assert_detail_error(
        missing,
        request_id="req-resource-detail-missing",
        status_code=404,
        code="not_found",
        message="资源不存在",
    )
    _assert_detail_error(
        unauthenticated,
        request_id="req-resource-detail-auth",
        status_code=401,
        code="session_invalid",
        message="会话无效或已过期",
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure", "status_code", "code", "message"),
    [
        (OperationalError("SELECT resource", {}, Exception("database offline")), 503,
         "database_unavailable", "数据库暂时不可用"),
        (RuntimeError("private resource failure"), 500, "internal_error", "服务器内部错误"),
    ],
)
def test_resource_detail_database_and_unexpected_failures_are_safe_and_traced(
    failure: Exception,
    status_code: int,
    code: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(repository, "get_resource_observation", fail)
    request_id = f"req-resource-detail-{status_code}"
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{uuid4()}",
            headers={"X-Request-ID": request_id},
        )

    _assert_detail_error(
        response,
        request_id=request_id,
        status_code=status_code,
        code=code,
        message=message,
    )
    assert "private resource failure" not in response.text


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
    for response in (page_one, page_two, detail, context, download):
        assert response.headers["cache-control"] == "private, no-store"
    assert invalid_cursor.status_code == invalid_limit.status_code == 422
    assert invalid_cursor.json() == {
        "message": "分页游标无效",
        "code": "invalid_cursor",
        "traceId": "req-resource-invalid-cursor",
    }
    assert invalid_limit.json()["traceId"] == "req-resource-invalid-limit"
    assert invalid_cursor.headers["cache-control"] == "private, no-store"
    assert invalid_limit.headers["cache-control"] == "private, no-store"
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
            f"{version_id}/retry",
            headers={"X-Request-ID": "req-resource-retry-success"},
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
    _assert_detail_boundary(
        retried,
        request_id="req-resource-retry-success",
        status_code=200,
    )
    retried_body = retried.json()
    assert set(retried_body) == {
        "id", "title", "sourceType", "createdAt", "updatedAt", "latestVersion"
    }
    retried_version_body = retried_body["latestVersion"]
    assert isinstance(retried_version_body, dict)
    retried_version = KnowledgeVersionResponse.model_validate({
        "id": retried_version_body["id"],
        "source_type": retried_version_body["sourceType"],
        "media_type": retried_version_body["mediaType"],
        "size_bytes": retried_version_body["sizeBytes"],
        "sha256": retried_version_body["sha256"],
        "status": retried_version_body["status"],
        "error_code": retried_version_body["errorCode"],
        "retryable": retried_version_body["retryable"],
        "created_at": retried_version_body["createdAt"],
        "processing_started_at": retried_version_body["processingStartedAt"],
        "ready_at": retried_version_body["readyAt"],
    })
    retried_resource = KnowledgeResourceResponse.model_validate({
        "id": retried_body["id"],
        "title": retried_body["title"],
        "source_type": retried_body["sourceType"],
        "created_at": retried_body["createdAt"],
        "updated_at": retried_body["updatedAt"],
        "latest_version": retried_version,
    })
    assert retried_resource.id == resource_id
    assert retried_version.id == version_id
    assert retried_version_body["status"] == "queued"
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
        deleted = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={"X-Request-ID": "req-resource-delete-success"},
        )
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
    _assert_detail_boundary(
        deleted,
        request_id="req-resource-delete-success",
        status_code=204,
    )
    assert deleted.content == b""
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
    matrix_case = f"{role.value}-{permission or 'none'}"
    retry_request_id = f"req-resource-matrix-retry-{matrix_case}"
    delete_request_id = f"req-resource-matrix-delete-{matrix_case}"
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
            f"{version_id}/retry",
            headers={"X-Request-ID": retry_request_id},
        )
        deleted = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={"X-Request-ID": delete_request_id},
        )

    expected_read = 200 if can_read else 404
    assert listing.status_code == detail.status_code == context.status_code == expected_read
    assert download.status_code == (307 if can_read else 404)
    if can_read:
        assert listing.json()["capabilities"] == {"canWrite": can_write}
    if can_write:
        _assert_detail_error(
            retry,
            request_id=retry_request_id,
            status_code=409,
            code="version_not_retryable",
            message="该版本不可重试",
        )
        _assert_detail_boundary(
            deleted,
            request_id=delete_request_id,
            status_code=204,
        )
        assert deleted.content == b""
    else:
        for response, request_id in (
            (retry, retry_request_id),
            (deleted, delete_request_id),
        ):
            _assert_detail_error(
                response,
                request_id=request_id,
                status_code=404,
                code="not_found",
                message="资源不存在",
            )


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
        missing_session_retry = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
            f"{version_id}/retry",
            headers={
                "Origin": APP_ORIGIN,
                "X-CSRF-Token": "csrf-without-session",
                "X-Request-ID": "req-resource-retry-no-session-csrf",
            },
        )
        missing_session_delete = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={
                "Origin": APP_ORIGIN,
                "X-CSRF-Token": "csrf-without-session",
                "X-Request-ID": "req-resource-delete-no-session-csrf",
            },
        )
    with knowledge_client(settings, database, actor, MemoryObjectStore()) as client:
        valid_csrf_token = client.headers["X-CSRF-Token"]
        valid_session_token = client.cookies.get(settings.session_cookie_name)
        assert valid_session_token is not None
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
        trusted_origin_retry = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
            f"{version_id}/retry",
            headers={
                "Origin": APP_ORIGIN,
                "X-CSRF-Token": "invalid-csrf",
                "X-Request-ID": "req-resource-cors-csrf-retry",
            },
        )
        trusted_origin_delete = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={
                "Origin": APP_ORIGIN,
                "X-CSRF-Token": "invalid-csrf",
                "X-Request-ID": "req-resource-cors-csrf-delete",
            },
        )
        with database.session_factory.begin() as session:
            session.execute(
                update(AuthSession)
                .where(AuthSession.user_id == actor.user_id)
                .values(revoked_at=datetime.now(UTC))
            )
        revoked_session_retry = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
            f"{version_id}/retry",
            headers={
                "Origin": APP_ORIGIN,
                "Cookie": f"{settings.session_cookie_name}={valid_session_token}",
                "X-CSRF-Token": valid_csrf_token,
                "X-Request-ID": "req-resource-retry-session",
            },
        )
        revoked_session_delete = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={
                "Origin": APP_ORIGIN,
                "Cookie": f"{settings.session_cookie_name}={valid_session_token}",
                "X-CSRF-Token": valid_csrf_token,
                "X-Request-ID": "req-resource-delete-session",
            },
        )

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["traceId"] == "req-resource-session"
    for response, request_id in (
        (missing_session_retry, "req-resource-retry-no-session-csrf"),
        (missing_session_delete, "req-resource-delete-no-session-csrf"),
    ):
        _assert_detail_error(
            response,
            request_id=request_id,
            status_code=403,
            code="csrf_failed",
            message="请求来源或 CSRF 令牌无效",
        )
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
        assert response.headers["cache-control"] == "private, no-store"
        assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-credentials" not in response.headers
    for response, request_id in (
        (trusted_origin_retry, "req-resource-cors-csrf-retry"),
        (trusted_origin_delete, "req-resource-cors-csrf-delete"),
    ):
        _assert_detail_error(
            response,
            request_id=request_id,
            status_code=403,
            code="csrf_failed",
            message="请求来源或 CSRF 令牌无效",
        )
    for response, request_id in (
        (revoked_session_retry, "req-resource-retry-session"),
        (revoked_session_delete, "req-resource-delete-session"),
    ):
        _assert_detail_error(
            response,
            request_id=request_id,
            status_code=401,
            code="session_invalid",
            message="会话无效或已过期",
        )


@pytest.mark.integration
def test_resource_mutation_validation_is_safe_traced_and_schema_stable(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    settings = knowledge_settings(test_database_url)
    with knowledge_client(settings, database, actor, MemoryObjectStore()) as client:
        retry = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/not-a-uuid/versions/"
            f"{uuid4()}/retry",
            headers={"X-Request-ID": "req-resource-retry-validation"},
        )
        deleted = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/not-a-uuid",
            headers={"X-Request-ID": "req-resource-delete-validation"},
        )

    for response, request_id in (
        (retry, "req-resource-retry-validation"),
        (deleted, "req-resource-delete-validation"),
    ):
        _assert_detail_error(
            response,
            request_id=request_id,
            status_code=422,
            code="validation_error",
            message="请求参数无效",
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure", "status_code", "code", "message"),
    [
        (
            OperationalError("SELECT retry", {}, Exception("database offline")),
            503,
            "database_unavailable",
            "数据库暂时不可用",
        ),
        (RuntimeError("private retry failure"), 500, "internal_error", "服务器内部错误"),
    ],
)
def test_resource_retry_infrastructure_and_unexpected_failures_are_safe_and_traced(
    failure: Exception,
    status_code: int,
    code: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    resource_id, version_id, _chunk_ids = _seed_ready_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="重试故障边界.pdf",
        created_at=datetime.now(UTC),
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(repository, "get_resource_version_job_for_update", fail)
    request_id = f"req-resource-retry-{status_code}"
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
            f"{version_id}/retry",
            headers={"X-Request-ID": request_id},
        )

    _assert_detail_error(
        response,
        request_id=request_id,
        status_code=status_code,
        code=code,
        message=message,
    )
    assert "private retry failure" not in response.text


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
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.integration
def test_upload_cleanup_expires_pending_and_preserves_completed_or_referenced_objects(
    database: Database,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    now = datetime.now(UTC) + timedelta(hours=1)
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
            expires_at=now - timedelta(minutes=1),
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
            expires_at=now - timedelta(minutes=1),
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
            expires_at=now - timedelta(minutes=1),
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
    now = datetime.now(UTC) + timedelta(hours=1)
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
    now = datetime.now(UTC) + timedelta(hours=1)
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
    assert response.headers["cache-control"] == "private, no-store"
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

    _assert_detail_error(
        response,
        request_id="req-delete-audit-failure",
        status_code=500,
        code="internal_error",
        message="服务器内部错误",
    )
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


@pytest.mark.integration
def test_delete_database_failure_preserves_resource_and_returns_traced_503(
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
        title="删除数据库故障.pdf",
        created_at=datetime.now(UTC),
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("UPDATE resource", {}, Exception("database offline"))

    monkeypatch.setattr(repository, "soft_delete_resource", fail)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
            headers={"X-Request-ID": "req-delete-database-failure"},
        )

    _assert_detail_error(
        response,
        request_id="req-delete-database-failure",
        status_code=503,
        code="database_unavailable",
        message="数据库暂时不可用",
    )
    with database.session_factory() as session:
        resource = session.get(KnowledgeResource, resource_id)
        assert resource is not None and resource.deleted_at is None
