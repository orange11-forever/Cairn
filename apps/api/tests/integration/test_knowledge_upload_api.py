import base64
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import httpx
import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.db.session import Database
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    IngestionBatch,
    IngestionBatchStatus,
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
    UploadSession,
)
from cairn_api.knowledge.object_store import (
    Boto3ObjectStore,
    ObjectStat,
    ObjectStoreUnavailable,
)
from cairn_api.projects.models import OutboxEvent, Project
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from .authorization_helpers import APP_ORIGIN, seed_actor
from .knowledge_helpers import (
    MemoryObjectStore,
    knowledge_client,
    knowledge_settings,
    seed_project,
)


def _intent(
    *,
    file_name: str = "report.pdf",
    media_type: str = "application/pdf",
    payload: bytes = b"%PDF-1.7\nCairn",
) -> dict[str, object]:
    return {
        "fileName": file_name,
        "mediaType": media_type,
        "sizeBytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _create_upload(
    client: TestClient,
    project_id: UUID,
    *,
    intents: list[dict[str, object]] | None = None,
) -> Response:
    return client.post(
        f"/api/v1/projects/{project_id}/knowledge/uploads",
        json={"files": intents or [_intent()]},
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("role", "permission", "expected_status"),
    [
        (MembershipRole.OWNER, None, 201),
        (MembershipRole.ADMIN, None, 201),
        (MembershipRole.MEMBER, "write", 201),
        (MembershipRole.MEMBER, "read", 404),
        (MembershipRole.MEMBER, None, 404),
        (MembershipRole.VIEWER, "write", 404),
    ],
)
def test_upload_creation_uses_live_project_write_policy(
    role: MembershipRole,
    permission: str | None,
    expected_status: int,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, role)
    project_id = seed_project(database, actor, permission=permission)
    store = MemoryObjectStore()
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        response = _create_upload(client, project_id)

    assert response.status_code == expected_status
    if expected_status == 404:
        assert response.json()["code"] == "not_found"
        assert store.presigned_keys == []


@pytest.mark.integration
def test_upload_creation_conceals_cross_organization_project_ids(
    database: Database,
    test_database_url: str,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    other = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, other, permission=None)
    with knowledge_client(
        knowledge_settings(test_database_url), database, owner, MemoryObjectStore()
    ) as client:
        response = _create_upload(client, project_id)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.integration
def test_upload_creation_persists_batch_items_sessions_audit_and_outbox(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="write")
    store = MemoryObjectStore()
    files = [
        _intent(),
        _intent(
            file_name="notes.md",
            media_type="text/markdown",
            payload="知识笔记".encode(),
        ),
    ]
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        response = _create_upload(client, project_id, intents=files)

    assert response.status_code == 201
    assert response.headers["x-request-id"]
    body = response.json()
    assert set(body) == {"batchId", "uploads"}
    assert len(body["uploads"]) == 2
    assert all(upload["method"] == "PUT" for upload in body["uploads"])
    assert all(upload["headers"]["If-None-Match"] == "*" for upload in body["uploads"])
    with database.session_factory() as session:
        batch = session.get(IngestionBatch, UUID(body["batchId"]))
        assert batch is not None
        assert batch.org_id == actor.organization_id
        assert batch.project_id == project_id
        assert batch.created_by == actor.user_id
        assert batch.item_count == 2
        assert batch.status == IngestionBatchStatus.PENDING
        items = list(
            session.scalars(
                select(IngestionItem)
                .where(IngestionItem.batch_id == batch.id)
                .order_by(IngestionItem.created_at, IngestionItem.id)
            )
        )
        uploads = list(
            session.scalars(
                select(UploadSession)
                .where(UploadSession.batch_id == batch.id)
                .order_by(UploadSession.created_at, UploadSession.id)
            )
        )
        assert len(items) == len(uploads) == 2
        assert all(
            upload.object_key.startswith(
                f"orgs/{actor.organization_id}/projects/{project_id}/uploads/"
            )
            for upload in uploads
        )
        assert len({upload.object_key for upload in uploads}) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "knowledge.upload_batch_created",
                    AuditLog.resource_id == batch.id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "knowledge.upload_batch_created",
                    OutboxEvent.aggregate_id == project_id,
                )
            )
            == 1
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "injected",
    [
        {"orgId": str(uuid4())},
        {"objectKey": "orgs/forged"},
        {"sourceType": "feishu"},
        {"actorId": str(uuid4())},
    ],
)
def test_upload_creation_rejects_client_authority_with_stable_traced_error(
    injected: dict[str, object],
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            headers={"X-Request-ID": "req-reject-upload-authority"},
            json={"files": [{**_intent(), **injected}]},
        )

    assert response.status_code == 422
    assert response.json() == {
        "message": "请求参数无效",
        "code": "validation_error",
        "traceId": "req-reject-upload-authority",
    }
    assert response.headers["x-request-id"] == "req-reject-upload-authority"


@pytest.mark.integration
@pytest.mark.parametrize(
    "intent",
    [
        {
            "file_name": "report.pdf",
            "media_type": "application/pdf",
            "size_bytes": 1,
            "sha256": "a" * 64,
        },
        _intent(file_name="x" * 255 + " "),
        {**_intent(), "sizeBytes": True},
        {**_intent(), "sizeBytes": "1"},
        {**_intent(), "sizeBytes": 1.0},
    ],
)
def test_upload_creation_rejects_forms_outside_the_openapi_contract(
    intent: dict[str, object],
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            headers={"X-Request-ID": "req-upload-strict-contract"},
            json={"files": [intent]},
        )

    assert response.status_code == 422
    assert response.json() == {
        "message": "请求参数无效",
        "code": "validation_error",
        "traceId": "req-upload-strict-contract",
    }
    assert store.presigned_keys == []


@pytest.mark.integration
def test_upload_mutations_require_origin_and_session_bound_csrf(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        csrf = client.headers.pop("X-CSRF-Token")
        client.headers.pop("Origin")
        missing = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            headers={"X-Request-ID": "req-upload-csrf"},
            json={"files": [_intent()]},
        )
        client.headers.update({"Origin": APP_ORIGIN, "X-CSRF-Token": csrf})

    assert missing.status_code == 403
    assert missing.json() == {
        "message": "请求来源或 CSRF 令牌无效",
        "code": "csrf_failed",
        "traceId": "req-upload-csrf",
    }


@pytest.mark.integration
def test_upload_creation_rejects_multipart_bytes_without_creating_state(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            headers={"X-Request-ID": "req-upload-no-multipart"},
            files={"file": ("report.pdf", b"%PDF-1.7\nbytes", "application/pdf")},
        )

    assert response.status_code == 422
    assert response.json() == {
        "message": "请求参数无效",
        "code": "validation_error",
        "traceId": "req-upload-no-multipart",
    }
    assert store.presigned_keys == []
    with database.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionBatch)
                .where(IngestionBatch.project_id == project_id)
            )
            == 0
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (MembershipRole.MEMBER, "read"),
        (MembershipRole.MEMBER, None),
        (MembershipRole.VIEWER, "write"),
    ],
)
def test_complete_upload_rechecks_live_project_write_policy(
    role: MembershipRole,
    permission: str | None,
    database: Database,
    test_database_url: str,
) -> None:
    owner = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, owner, permission=None)
    blocked = seed_actor(database, role, org_id=owner.organization_id)
    if permission is not None:
        with database.session_factory.begin() as session:
            session.add(
                ResourceAclEntry(
                    org_id=owner.organization_id,
                    resource_type="project",
                    resource_id=project_id,
                    principal_type="user",
                    principal_id=str(blocked.user_id),
                    permission=permission,
                    granted_by_type="system",
                )
            )
    store = MemoryObjectStore()
    settings = knowledge_settings(test_database_url)
    with knowledge_client(settings, database, owner, store) as owner_client:
        created = _create_upload(owner_client, project_id)
        assert created.status_code == 201
        upload_id = created.json()["uploads"][0]["uploadId"]
    with knowledge_client(settings, database, blocked, store) as blocked_client:
        response = blocked_client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
            headers={"X-Request-ID": "req-complete-write-policy"},
        )

    assert response.status_code == 404
    assert response.json() == {
        "message": "资源不存在",
        "code": "not_found",
        "traceId": "req-complete-write-policy",
    }
    assert store.stat_calls == []


@pytest.mark.integration
@pytest.mark.parametrize(
    ("file_name", "media_type", "payload", "expected_kind"),
    [
        ("report.pdf", "application/pdf", b"%PDF-1.7\nCairn", JobKind.INDEX_RESOURCE_VERSION),
        ("bundle.zip", "application/zip", b"PK\x03\x04archive", JobKind.EXPAND_ARCHIVE),
    ],
)
def test_complete_upload_is_persisted_and_idempotent_for_files_and_archives(
    file_name: str,
    media_type: str,
    payload: bytes,
    expected_kind: JobKind,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()
    intent = _intent(file_name=file_name, media_type=media_type, payload=payload)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        created = _create_upload(client, project_id, intents=[intent])
        assert created.status_code == 201
        upload_body = created.json()["uploads"][0]
        object_key = store.presigned_keys[0]
        store.objects[object_key] = ObjectStat(
            size_bytes=len(payload),
            content_type=media_type,
            checksum_sha256=str(intent["sha256"]),
        )
        path = f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_body['uploadId']}/complete"
        first = client.post(path)
        second = client.post(path)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    result = first.json()
    assert result["status"] == "queued"
    assert (result["resourceId"] is None) is (expected_kind is JobKind.EXPAND_ARCHIVE)
    assert (result["resourceVersionId"] is None) is (expected_kind is JobKind.EXPAND_ARCHIVE)
    assert store.stat_calls == [object_key]
    with database.session_factory() as session:
        upload_id = UUID(upload_body["uploadId"])
        upload = session.get(UploadSession, upload_id)
        assert upload is not None and upload.completed_at is not None
        batch = session.get(IngestionBatch, upload.batch_id)
        assert batch is not None
        assert batch.status == IngestionBatchStatus.PROCESSING
        assert (batch.ready_count, batch.failed_count, batch.completed_at) == (0, 0, None)
        jobs = list(
            session.scalars(
                select(IngestionJob).where(
                    IngestionJob.project_id == project_id,
                    IngestionJob.job_kind == expected_kind,
                )
            )
        )
        assert len(jobs) == 1
        expected_resources = 0 if expected_kind is JobKind.EXPAND_ARCHIVE else 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeResource)
                .where(KnowledgeResource.project_id == project_id)
            )
            == expected_resources
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeResourceVersion)
                .where(KnowledgeResourceVersion.project_id == project_id)
            )
            == expected_resources
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "knowledge.upload_completed",
                    AuditLog.resource_id == upload_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "knowledge.upload_completed",
                    OutboxEvent.aggregate_id == project_id,
                )
            )
            == 1
        )


@pytest.mark.integration
def test_concurrent_complete_requests_return_one_identical_result(
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    class BlockingStore(MemoryObjectStore):
        def __init__(self) -> None:
            super().__init__()
            self.first_stat_entered = threading.Event()
            self.release_first_stat = threading.Event()
            self._stat_count = 0
            self._stat_lock = threading.Lock()

        def stat(self, *, object_key: str) -> ObjectStat:
            with self._stat_lock:
                self._stat_count += 1
                call_number = self._stat_count
            if call_number == 1:
                self.first_stat_entered.set()
                if not self.release_first_stat.wait(timeout=10):
                    raise RuntimeError("concurrent completion test timed out")
            return super().stat(object_key=object_key)

    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = BlockingStore()
    payload = b"%PDF-1.7\nconcurrent-complete"
    intent = _intent(payload=payload)
    settings = knowledge_settings(test_database_url)
    with (
        knowledge_client(settings, database, actor, store) as first_client,
        knowledge_client(settings, database, actor, store) as second_client,
    ):
        created = _create_upload(first_client, project_id, intents=[intent])
        assert created.status_code == 201
        upload_id = UUID(created.json()["uploads"][0]["uploadId"])
        object_key = store.presigned_keys[0]
        store.objects[object_key] = ObjectStat(
            size_bytes=len(payload),
            content_type=str(intent["mediaType"]),
            checksum_sha256=str(intent["sha256"]),
        )
        original_require_project = AuthorizationPolicy.require_project
        policy_lock = threading.Lock()
        second_policy_call = threading.Event()
        locked_policy_calls = 0

        def observe_require_project(
            policy: AuthorizationPolicy,
            identity: IdentityContextResponse,
            requested_project_id: UUID,
            required: ProjectPermission,
            *,
            for_update: bool = False,
        ) -> Project:
            nonlocal locked_policy_calls
            if for_update:
                with policy_lock:
                    locked_policy_calls += 1
                    if locked_policy_calls == 2:
                        second_policy_call.set()
            return original_require_project(
                policy,
                identity,
                requested_project_id,
                required,
                for_update=for_update,
            )

        monkeypatch.setattr(AuthorizationPolicy, "require_project", observe_require_project)
        path = f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete"
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(first_client.post, path)
            assert store.first_stat_entered.wait(timeout=10)
            second_future = executor.submit(second_client.post, path)
            assert second_policy_call.wait(timeout=10)
            store.release_first_stat.set()
            first = first_future.result(timeout=10)
            second = second_future.result(timeout=10)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert store.stat_calls == [object_key]
    with database.session_factory() as session:
        for model in (KnowledgeResource, KnowledgeResourceVersion, IngestionJob):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.project_id == project_id)
                )
                == 1
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "knowledge.upload_completed",
                    AuditLog.resource_id == upload_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "knowledge.upload_completed",
                    OutboxEvent.aggregate_id == project_id,
                )
            )
            == 1
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("stat", "expected_status", "expected_code"),
    [
        (None, 409, "upload_object_missing"),
        (
            ObjectStat(1, "application/pdf", hashlib.sha256(b"x").hexdigest()),
            409,
            "upload_size_mismatch",
        ),
        (
            ObjectStat(len(b"%PDF-1.7\nCairn"), "application/pdf", "b" * 64),
            409,
            "upload_checksum_mismatch",
        ),
        (
            ObjectStat(
                len(b"%PDF-1.7\nCairn"),
                "text/plain",
                hashlib.sha256(b"%PDF-1.7\nCairn").hexdigest(),
            ),
            409,
            "upload_media_type_mismatch",
        ),
    ],
)
def test_complete_upload_reports_and_persists_object_validation_failures(
    stat: ObjectStat | None,
    expected_status: int,
    expected_code: str,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        created = _create_upload(client, project_id)
        upload_id = UUID(created.json()["uploads"][0]["uploadId"])
        if stat is not None:
            store.objects[store.presigned_keys[0]] = stat
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
            headers={"X-Request-ID": "req-upload-invalid-object"},
        )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert response.json()["traceId"] == "req-upload-invalid-object"
    with database.session_factory() as session:
        upload = session.get(UploadSession, upload_id)
        assert upload is not None and upload.abandoned_at is not None
        item = session.get(IngestionItem, upload.item_id)
        assert item is not None
        assert item.status == "failed"
        assert item.error_code == expected_code
        batch = session.get(IngestionBatch, upload.batch_id)
        assert batch is not None
        assert batch.status == IngestionBatchStatus.FAILED
        assert (batch.ready_count, batch.failed_count) == (0, 1)
        assert batch.completed_at is not None
        assert (
            session.scalar(
                select(func.count())
                .select_from(IngestionJob)
                .where(IngestionJob.project_id == project_id)
            )
            == 0
        )


@pytest.mark.integration
def test_complete_expired_upload_persists_failure_without_object_lookup(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        created = _create_upload(client, project_id)
        upload_id = UUID(created.json()["uploads"][0]["uploadId"])
        with database.session_factory.begin() as session:
            upload = session.get(UploadSession, upload_id)
            assert upload is not None
            upload.expires_at = upload.created_at + timedelta(microseconds=1)
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete"
        )

    assert response.status_code == 410
    assert response.json()["code"] == "upload_expired"
    assert store.stat_calls == []


@pytest.mark.integration
@pytest.mark.parametrize("failure_boundary", ["audit", "outbox"])
def test_upload_creation_rolls_back_when_transactional_side_effect_fails(
    failure_boundary: str,
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(f"{failure_boundary} insertion failed")

    if failure_boundary == "audit":
        monkeypatch.setattr("cairn_api.knowledge.upload_service.add_audit_log", fail)
    else:
        monkeypatch.setattr(repository, "add_project_outbox_event", fail)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = _create_upload(client, project_id)

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.json()["traceId"] == response.headers["x-request-id"]
    with database.session_factory() as session:
        for model in (IngestionBatch, IngestionItem, UploadSession):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.project_id == project_id)
                )
                == 0
            )


@pytest.mark.integration
def test_upload_completion_rolls_back_when_outbox_insertion_fails(
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        created = _create_upload(client, project_id)
        upload_id = UUID(created.json()["uploads"][0]["uploadId"])
        object_key = store.presigned_keys[0]
        payload = b"%PDF-1.7\nCairn"
        intent = _intent(payload=payload)
        store.objects[object_key] = ObjectStat(
            size_bytes=len(payload),
            content_type=str(intent["mediaType"]),
            checksum_sha256=str(intent["sha256"]),
        )

        def fail_completion_outbox(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("completion outbox failed")

        monkeypatch.setattr(
            repository,
            "add_project_outbox_event",
            fail_completion_outbox,
        )
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
            headers={"X-Request-ID": "req-completion-outbox-rollback"},
        )

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器内部错误",
        "code": "internal_error",
        "traceId": "req-completion-outbox-rollback",
    }
    with database.session_factory() as session:
        upload = session.get(UploadSession, upload_id)
        assert upload is not None
        assert upload.completed_at is None
        item = session.get(IngestionItem, upload.item_id)
        assert item is not None and item.status == IngestionItemStatus.AWAITING_UPLOAD
        for model in (KnowledgeResource, KnowledgeResourceVersion, IngestionJob):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.project_id == project_id)
                )
                == 0
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "knowledge.upload_completed",
                    AuditLog.resource_id == upload_id,
                )
            )
            == 0
        )


@pytest.mark.integration
def test_transient_object_store_failure_leaves_completion_retryable(
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()
    payload = b"%PDF-1.7\nCairn"
    intent = _intent(payload=payload)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        created = _create_upload(client, project_id, intents=[intent])
        assert created.status_code == 201
        upload_id = UUID(created.json()["uploads"][0]["uploadId"])
        object_key = store.presigned_keys[0]
        stat = ObjectStat(
            size_bytes=len(payload),
            content_type=str(intent["mediaType"]),
            checksum_sha256=str(intent["sha256"]),
        )
        stat_mock = Mock(side_effect=[ObjectStoreUnavailable(), stat])
        monkeypatch.setattr(store, "stat", stat_mock)

        unavailable = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
            headers={"X-Request-ID": "req-complete-store-transient"},
        )
        with database.session_factory() as session:
            upload = session.get(UploadSession, upload_id)
            assert upload is not None
            assert upload.completed_at is upload.abandoned_at is None
            item = session.get(IngestionItem, upload.item_id)
            assert item is not None and item.status == IngestionItemStatus.AWAITING_UPLOAD
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action == "knowledge.upload_failed")
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.event_type == "knowledge.upload_failed")
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IngestionJob)
                    .where(IngestionJob.project_id == project_id)
                )
                == 0
            )

        completed = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete"
        )

    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "message": "对象存储暂时不可用",
        "code": "object_store_unavailable",
        "traceId": "req-complete-store-transient",
    }
    assert completed.status_code == 200
    assert completed.json()["status"] == "queued"
    assert stat_mock.call_count == 2
    assert all(call.kwargs == {"object_key": object_key} for call in stat_mock.call_args_list)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (
            OperationalError("INSERT batch", {}, Exception("database offline")),
            "database_unavailable",
        ),
        (ObjectStoreUnavailable(), "object_store_unavailable"),
    ],
)
def test_upload_creation_maps_infrastructure_failures_to_traced_503(
    failure: Exception,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    if isinstance(failure, OperationalError):
        monkeypatch.setattr(repository, "create_batch", fail)
    else:
        monkeypatch.setattr(store, "presign_put", fail)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            headers={"X-Request-ID": f"req-{expected_code}"},
            json={"files": [_intent()]},
        )

    assert response.status_code == 503
    assert response.json()["code"] == expected_code
    assert response.json()["traceId"] == f"req-{expected_code}"
    assert response.headers["x-request-id"] == f"req-{expected_code}"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("item_states", "expected_status", "expected_ready", "expected_failed"),
    [
        ([IngestionItemStatus.AWAITING_UPLOAD], IngestionBatchStatus.PENDING, 0, 0),
        ([IngestionItemStatus.QUEUED], IngestionBatchStatus.PROCESSING, 0, 0),
        (
            [IngestionItemStatus.READY, IngestionItemStatus.AWAITING_UPLOAD],
            IngestionBatchStatus.PROCESSING,
            1,
            0,
        ),
        ([IngestionItemStatus.READY], IngestionBatchStatus.COMPLETED, 1, 0),
        (
            [IngestionItemStatus.READY, IngestionItemStatus.FAILED],
            IngestionBatchStatus.COMPLETED_WITH_ERRORS,
            1,
            1,
        ),
        ([IngestionItemStatus.FAILED], IngestionBatchStatus.FAILED, 0, 1),
    ],
)
def test_refresh_batch_summary_derives_every_persisted_status(
    item_states: list[IngestionItemStatus],
    expected_status: IngestionBatchStatus,
    expected_ready: int,
    expected_failed: int,
    database: Database,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    batch_id = uuid4()
    now = datetime.now(UTC)
    with database.session_factory.begin() as session:
        session.add(
            IngestionBatch(
                id=batch_id,
                org_id=actor.organization_id,
                project_id=project_id,
                created_by=actor.user_id,
                item_count=len(item_states),
            )
        )
        session.flush()
        for ordinal, item_status in enumerate(item_states):
            failed = item_status is IngestionItemStatus.FAILED
            ready = item_status is IngestionItemStatus.READY
            session.add(
                IngestionItem(
                    org_id=actor.organization_id,
                    project_id=project_id,
                    batch_id=batch_id,
                    normalized_path=f"item-{ordinal}.txt",
                    media_type="text/plain",
                    size_bytes=1,
                    sha256=f"{ordinal + 1:064x}",
                    status=item_status,
                    error_code="parser_failed" if failed else None,
                    completed_at=now if failed or ready else None,
                )
            )
        session.flush()
        summary = repository.refresh_batch_summary(
            session,
            org_id=actor.organization_id,
            project_id=project_id,
            batch_id=batch_id,
            now=now,
        )
        assert summary.status == expected_status
        assert summary.ready_count == expected_ready
        assert summary.failed_count == expected_failed
        assert (summary.completed_at is not None) is (
            expected_status
            in {
                IngestionBatchStatus.COMPLETED,
                IngestionBatchStatus.COMPLETED_WITH_ERRORS,
                IngestionBatchStatus.FAILED,
            }
        )


@pytest.mark.integration
def test_upload_openapi_is_json_only_and_declares_protected_error_contracts(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        schema = client.get("/openapi.json").json()

    create_operation = schema["paths"]["/api/v1/projects/{project_id}/knowledge/uploads"]["post"]
    complete_path = schema["paths"][
        "/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete"
    ]
    assert set(create_operation["requestBody"]["content"]) == {"application/json"}
    assert set(complete_path) == {"post"}
    assert "multipart/form-data" not in str(schema)
    for operation in (create_operation, complete_path["post"]):
        csrf = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "X-CSRF-Token"
        )
        assert csrf["required"] is True
        for status_code in ("401", "403", "404", "409", "410", "422", "500", "503"):
            assert operation["responses"][status_code]["content"]["application/json"]["schema"][
                "$ref"
            ].endswith("/ErrorBody")
            assert "X-Request-ID" in operation["responses"][status_code]["headers"]
            assert operation["responses"][status_code]["headers"]["Cache-Control"] == {
                "description": "防止受保护知识响应被浏览器或中间缓存保存",
                "schema": {"type": "string", "const": "private, no-store"},
            }


@pytest.mark.integration
def test_real_minio_signed_put_can_be_completed(
    database: Database,
    test_database_url: str,
) -> None:
    endpoint = os.environ.get("CAIRN_TEST_S3_ENDPOINT_URL")
    if not endpoint:
        pytest.skip("CAIRN_TEST_S3_ENDPOINT_URL is required for real MinIO upload test")
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    settings = knowledge_settings(
        test_database_url,
        object_store_endpoint_url=endpoint,
        object_store_public_endpoint_url=endpoint,
    )
    store = Boto3ObjectStore.from_settings(settings)
    payload = b"%PDF-1.7\nreal-minio-upload"
    intent = _intent(payload=payload)
    try:
        with knowledge_client(settings, database, actor, store) as client:
            created = _create_upload(client, project_id, intents=[intent])
            assert created.status_code == 201
            instruction = created.json()["uploads"][0]
            checksum = base64.b64encode(bytes.fromhex(str(intent["sha256"]))).decode()
            assert instruction["headers"]["x-amz-checksum-sha256"] == checksum
            with httpx.Client(trust_env=False) as http_client:
                upload = http_client.put(
                    instruction["url"],
                    content=payload,
                    headers=instruction["headers"],
                    timeout=10,
                )
            assert upload.status_code in {200, 204}
            completed = client.post(
                f"/api/v1/projects/{project_id}/knowledge/uploads/"
                f"{instruction['uploadId']}/complete"
            )
            assert completed.status_code == 200
            assert completed.json()["resourceVersionId"] is not None
    finally:
        store.close()
