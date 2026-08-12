from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cairn_api.knowledge.models import IngestionItemStatus
from cairn_api.knowledge.schemas import (
    UploadBatchCreateRequest,
    UploadBatchCreateResponse,
    UploadCompleteResponse,
    UploadInstruction,
)
from pydantic import ValidationError


def _file(**overrides: object) -> dict[str, object]:
    return {
        "fileName": "报告.pdf",
        "mediaType": "application/pdf",
        "sizeBytes": 128,
        "sha256": "a" * 64,
        **overrides,
    }


def test_upload_request_accepts_only_bounded_camel_case_file_intents() -> None:
    request = UploadBatchCreateRequest.model_validate({"files": [_file()]})

    assert request.files[0].file_name == "报告.pdf"
    assert request.files[0].media_type == "application/pdf"
    assert request.files[0].size_bytes == 128
    assert request.files[0].sha256 == "a" * 64
    assert request.model_dump(mode="json", by_alias=True) == {"files": [_file()]}


@pytest.mark.parametrize(
    "payload",
    [
        {"files": []},
        {"files": [_file(fileName=f"{index}.txt") for index in range(21)]},
        {"files": [_file(fileName="")]},
        {"files": [_file(fileName="x" * 256)]},
        {"files": [_file(fileName="x" * 255 + " ")]},
        {"files": [_file(mediaType="")]},
        {"files": [_file(mediaType="x" * 128)]},
        {"files": [_file(sizeBytes=0)]},
        {"files": [_file(sizeBytes=True)]},
        {"files": [_file(sizeBytes="1")]},
        {"files": [_file(sizeBytes=1.0)]},
        {"files": [_file(sha256="A" * 64)]},
        {"files": [_file(sha256="a" * 63)]},
        {
            "files": [
                {
                    "file_name": "report.pdf",
                    "media_type": "application/pdf",
                    "size_bytes": 1,
                    "sha256": "a" * 64,
                }
            ]
        },
    ],
)
def test_upload_request_rejects_hard_limit_violations(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UploadBatchCreateRequest.model_validate(payload)


@pytest.mark.parametrize(
    "injected",
    [
        {"orgId": str(uuid4())},
        {"objectKey": "orgs/forged"},
        {"sourceType": "feishu"},
        {"createdBy": str(uuid4())},
        {"actorId": str(uuid4())},
    ],
)
def test_upload_request_rejects_client_controlled_authority_fields(
    injected: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        UploadBatchCreateRequest.model_validate({"files": [{**_file(), **injected}]})


def test_upload_responses_serialize_the_documented_camel_case_contract() -> None:
    batch_id = uuid4()
    upload_id = uuid4()
    item_id = uuid4()
    resource_id = uuid4()
    version_id = uuid4()
    expires_at = datetime(2026, 8, 13, 1, 15, tzinfo=UTC)
    instruction = UploadInstruction(
        upload_id=upload_id,
        item_id=item_id,
        url="https://objects.example/upload",
        headers={"If-None-Match": "*"},
        expires_at=expires_at,
    )

    created = UploadBatchCreateResponse(batch_id=batch_id, uploads=[instruction])
    completed = UploadCompleteResponse(
        upload_id=upload_id,
        batch_id=batch_id,
        item_id=item_id,
        resource_id=resource_id,
        resource_version_id=version_id,
        status=IngestionItemStatus.QUEUED,
    )

    assert created.model_dump(mode="json", by_alias=True) == {
        "batchId": str(batch_id),
        "uploads": [
            {
                "uploadId": str(upload_id),
                "itemId": str(item_id),
                "method": "PUT",
                "url": "https://objects.example/upload",
                "headers": {"If-None-Match": "*"},
                "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
            }
        ],
    }
    assert completed.model_dump(mode="json", by_alias=True) == {
        "uploadId": str(upload_id),
        "batchId": str(batch_id),
        "itemId": str(item_id),
        "resourceId": str(resource_id),
        "resourceVersionId": str(version_id),
        "status": "queued",
    }
