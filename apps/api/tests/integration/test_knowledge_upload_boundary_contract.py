import hashlib
from typing import cast
from uuid import uuid4

import pytest
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.errors import ErrorBody
from cairn_api.knowledge import repository
from cairn_api.knowledge.object_store import ObjectStat, ObjectStoreUnavailable
from cairn_api.knowledge.schemas import (
    BatchDetailResponse,
    IngestionItemResponse,
    UploadBatchCreateResponse,
    UploadCompleteResponse,
    UploadInstruction,
)
from httpx2 import Response
from sqlalchemy.exc import OperationalError

from .authorization_helpers import APP_ORIGIN, seed_actor
from .knowledge_helpers import (
    MemoryObjectStore,
    knowledge_client,
    knowledge_settings,
    seed_project,
)


def _intent(payload: bytes = b"%PDF-1.7\nBoundary") -> dict[str, object]:
    return {
        "fileName": "boundary.pdf",
        "mediaType": "application/pdf",
        "sizeBytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _assert_protected_boundary(
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


def _assert_error_boundary(
    response: Response,
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
) -> None:
    _assert_protected_boundary(response, request_id=request_id, status_code=status_code)
    body = response.json()
    assert set(body) == {"message", "code", "traceId"}
    parsed = ErrorBody.model_validate(
        {"message": body["message"], "code": body["code"], "trace_id": body["traceId"]}
    )
    assert body == parsed.model_dump(by_alias=True, mode="json")
    assert body == {
        "message": message,
        "code": code,
        "traceId": request_id,
    }


def _parse_create_response(body: dict[str, object]) -> UploadBatchCreateResponse:
    assert set(body) == {"batchId", "uploads"}
    assert isinstance(body["uploads"], list)
    raw_uploads = cast(list[dict[str, object]], body["uploads"])
    uploads: list[UploadInstruction] = []
    for raw in raw_uploads:
        assert isinstance(raw, dict)
        assert set(raw) == {"uploadId", "itemId", "method", "url", "headers", "expiresAt"}
        uploads.append(
            UploadInstruction.model_validate(
                {
                    "upload_id": raw["uploadId"],
                    "item_id": raw["itemId"],
                    "method": raw["method"],
                    "url": raw["url"],
                    "headers": raw["headers"],
                    "expires_at": raw["expiresAt"],
                }
            )
        )
    parsed = UploadBatchCreateResponse.model_validate(
        {"batch_id": body["batchId"], "uploads": uploads}
    )
    assert body == parsed.model_dump(by_alias=True, mode="json")
    return parsed


def _parse_complete_response(body: dict[str, object]) -> UploadCompleteResponse:
    assert set(body) == {
        "uploadId",
        "batchId",
        "itemId",
        "resourceId",
        "resourceVersionId",
        "status",
    }
    parsed = UploadCompleteResponse.model_validate(
        {
            "upload_id": body["uploadId"],
            "batch_id": body["batchId"],
            "item_id": body["itemId"],
            "resource_id": body["resourceId"],
            "resource_version_id": body["resourceVersionId"],
            "status": body["status"],
        }
    )
    assert body == parsed.model_dump(by_alias=True, mode="json")
    return parsed


def _parse_batch_response(body: dict[str, object]) -> BatchDetailResponse:
    assert set(body) == {
        "id",
        "status",
        "itemCount",
        "readyCount",
        "failedCount",
        "createdAt",
        "completedAt",
        "items",
    }
    assert isinstance(body["items"], list)
    raw_items = cast(list[dict[str, object]], body["items"])
    items: list[IngestionItemResponse] = []
    expected_item_fields = {
        "id",
        "parentItemId",
        "normalizedPath",
        "mediaType",
        "sizeBytes",
        "status",
        "errorCode",
        "errorDetail",
        "resourceId",
        "resourceVersionId",
        "createdAt",
        "completedAt",
    }
    for raw in raw_items:
        assert isinstance(raw, dict)
        assert set(raw) == expected_item_fields
        items.append(
            IngestionItemResponse.model_validate(
                {
                    "id": raw["id"],
                    "parent_item_id": raw["parentItemId"],
                    "normalized_path": raw["normalizedPath"],
                    "media_type": raw["mediaType"],
                    "size_bytes": raw["sizeBytes"],
                    "status": raw["status"],
                    "error_code": raw["errorCode"],
                    "error_detail": raw["errorDetail"],
                    "resource_id": raw["resourceId"],
                    "resource_version_id": raw["resourceVersionId"],
                    "created_at": raw["createdAt"],
                    "completed_at": raw["completedAt"],
                }
            )
        )
    parsed = BatchDetailResponse.model_validate(
        {
            "id": body["id"],
            "status": body["status"],
            "item_count": body["itemCount"],
            "ready_count": body["readyCount"],
            "failed_count": body["failedCount"],
            "created_at": body["createdAt"],
            "completed_at": body["completedAt"],
            "items": items,
        }
    )
    assert body == parsed.model_dump(by_alias=True, mode="json")
    return parsed


@pytest.mark.integration
def test_upload_create_complete_and_batch_success_match_schemas_and_protected_headers(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    store = MemoryObjectStore()
    payload = b"%PDF-1.7\nBoundary"
    intent = _intent(payload)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        created = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            headers={"X-Request-ID": "req-upload-boundary-create"},
            json={"files": [intent]},
        )
        created_model = _parse_create_response(created.json())
        _assert_protected_boundary(
            created,
            request_id="req-upload-boundary-create",
            status_code=201,
        )

        upload = created_model.uploads[0]
        store.objects[store.presigned_keys[0]] = ObjectStat(
            size_bytes=len(payload),
            content_type=str(intent["mediaType"]),
            checksum_sha256=str(intent["sha256"]),
        )
        completed = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{upload.upload_id}/complete",
            headers={"X-Request-ID": "req-upload-boundary-complete"},
        )
        completed_model = _parse_complete_response(completed.json())
        _assert_protected_boundary(
            completed,
            request_id="req-upload-boundary-complete",
            status_code=200,
        )

        batch = client.get(
            f"/api/v1/projects/{project_id}/knowledge/batches/{created_model.batch_id}",
            headers={"X-Request-ID": "req-upload-boundary-batch"},
        )
        batch_model = _parse_batch_response(batch.json())
        _assert_protected_boundary(
            batch,
            request_id="req-upload-boundary-batch",
            status_code=200,
        )

    assert completed_model.batch_id == created_model.batch_id == batch_model.id
    assert completed_model.upload_id == upload.upload_id
    assert completed_model.item_id == upload.item_id == batch_model.items[0].id


@pytest.mark.integration
def test_upload_validation_auth_csrf_and_not_found_errors_share_the_safe_contract(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    missing_project_id = uuid4()
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        validation = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            headers={"X-Request-ID": "req-upload-boundary-validation"},
            json={"files": []},
        )

        csrf = client.headers.pop("X-CSRF-Token")
        csrf_failure = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads",
            headers={"X-Request-ID": "req-upload-boundary-csrf"},
            json={"files": [_intent()]},
        )
        client.headers["X-CSRF-Token"] = csrf

        hidden_project = client.post(
            f"/api/v1/projects/{missing_project_id}/knowledge/uploads",
            headers={"X-Request-ID": "req-upload-boundary-project-404"},
            json={"files": [_intent()]},
        )
        hidden_upload = client.post(
            f"/api/v1/projects/{project_id}/knowledge/uploads/{uuid4()}/complete",
            headers={"X-Request-ID": "req-upload-boundary-complete-404"},
        )
        hidden_batch = client.get(
            f"/api/v1/projects/{project_id}/knowledge/batches/{uuid4()}",
            headers={"X-Request-ID": "req-upload-boundary-batch-404"},
        )

        client.cookies.clear()
        unauthenticated = client.get(
            f"/api/v1/projects/{project_id}/knowledge/batches/{uuid4()}",
            headers={"X-Request-ID": "req-upload-boundary-auth"},
        )

    _assert_error_boundary(
        validation,
        request_id="req-upload-boundary-validation",
        status_code=422,
        code="validation_error",
        message="请求参数无效",
    )
    _assert_error_boundary(
        csrf_failure,
        request_id="req-upload-boundary-csrf",
        status_code=403,
        code="csrf_failed",
        message="请求来源或 CSRF 令牌无效",
    )
    for response, request_id in (
        (hidden_project, "req-upload-boundary-project-404"),
        (hidden_upload, "req-upload-boundary-complete-404"),
        (hidden_batch, "req-upload-boundary-batch-404"),
    ):
        _assert_error_boundary(
            response,
            request_id=request_id,
            status_code=404,
            code="not_found",
            message="资源不存在",
        )
    _assert_error_boundary(
        unauthenticated,
        request_id="req-upload-boundary-auth",
        status_code=401,
        code="session_invalid",
        message="会话无效或已过期",
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure", "status_code", "code", "message"),
    [
        (
            OperationalError("SELECT batch", {}, Exception("database offline")),
            503,
            "database_unavailable",
            "数据库暂时不可用",
        ),
        (RuntimeError("private batch failure"), 500, "internal_error", "服务器内部错误"),
    ],
)
def test_batch_database_and_unexpected_failures_use_safe_traced_boundaries(
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

    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(repository, "get_batch_detail", fail)
    request_id = f"req-upload-boundary-batch-{status_code}"
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/batches/{uuid4()}",
            headers={"X-Request-ID": request_id},
        )

    _assert_error_boundary(
        response,
        request_id=request_id,
        status_code=status_code,
        code=code,
        message=message,
    )
    assert "private batch failure" not in response.text


@pytest.mark.integration
@pytest.mark.parametrize(
    ("stage", "failure", "status_code", "code", "message"),
    [
        (
            "create",
            OperationalError("INSERT batch", {}, Exception("database offline")),
            503,
            "database_unavailable",
            "数据库暂时不可用",
        ),
        ("create", ObjectStoreUnavailable(), 503, "object_store_unavailable", "对象存储暂时不可用"),
        ("create", RuntimeError("private create failure"), 500, "internal_error", "服务器内部错误"),
        ("complete", ObjectStoreUnavailable(), 503, "object_store_unavailable", "对象存储暂时不可用"),
        ("complete", RuntimeError("private complete failure"), 500, "internal_error", "服务器内部错误"),
    ],
)
def test_upload_mutation_infrastructure_and_unexpected_failures_use_safe_boundaries(
    stage: str,
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
    store = MemoryObjectStore()
    request_id = f"req-upload-boundary-{stage}-{status_code}-{code}"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        if stage == "create":
            if isinstance(failure, ObjectStoreUnavailable):
                monkeypatch.setattr(store, "presign_put", fail)
            else:
                monkeypatch.setattr(repository, "create_batch", fail)
            response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/uploads",
                headers={"X-Request-ID": request_id},
                json={"files": [_intent()]},
            )
        else:
            created = client.post(
                f"/api/v1/projects/{project_id}/knowledge/uploads",
                json={"files": [_intent()]},
            )
            assert created.status_code == 201
            upload_id = created.json()["uploads"][0]["uploadId"]
            monkeypatch.setattr(store, "stat", fail)
            response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
                headers={"X-Request-ID": request_id},
            )

    _assert_error_boundary(
        response,
        request_id=request_id,
        status_code=status_code,
        code=code,
        message=message,
    )
    assert "private" not in response.text
