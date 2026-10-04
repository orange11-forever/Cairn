from uuid import uuid4

import pytest
from cairn_api.knowledge.source_schemas import FeishuSourceCreateRequest, FeishuSourcePatchRequest
from pydantic import ValidationError


def _payload(**overrides: object) -> dict[str, object]:
    return {
        "name": "  Engineering handbook  ",
        "documentId": "Doc123",
        "credentialRef": "engineering_feishu",
        "accessPolicy": "project_members",
        **overrides,
    }


def test_feishu_source_request_requires_explicit_project_member_sharing() -> None:
    request = FeishuSourceCreateRequest.model_validate(_payload())

    assert request.name == "Engineering handbook"
    assert request.document_id == "Doc123"
    assert request.credential_ref == "engineering_feishu"
    assert request.access_policy == "project_members"


def test_lifecycle_requests_validate_interval_and_reconfirmation() -> None:
    with pytest.raises(ValidationError):
        FeishuSourceCreateRequest.model_validate(_payload(syncIntervalSeconds=True))
    with pytest.raises(ValidationError):
        FeishuSourcePatchRequest.model_validate({"status": "configured"})
    with pytest.raises(ValidationError):
        FeishuSourcePatchRequest.model_validate({"credentialRef": "other"})
    with pytest.raises(ValidationError):
        FeishuSourcePatchRequest.model_validate({"syncIntervalSeconds": False})
    assert FeishuSourcePatchRequest.model_validate(
        {"syncIntervalSeconds": None}
    ).sync_interval_seconds is None


@pytest.mark.parametrize(
    "payload",
    [
        _payload(accessPolicy=None),
        _payload(accessPolicy="private"),
        _payload(name=""),
        _payload(name="x\nsecret"),
        _payload(name="\nsecret"),
        _payload(name="bad\ud800text"),
        _payload(name="x" * 201),
        _payload(documentId="doc-123"),
        _payload(documentId="文档"),
        _payload(documentId="x" * 129),
        _payload(credentialRef="_secret"),
        _payload(credentialRef="x" * 65),
        _payload(url="https://example.invalid/doc"),
        _payload(appSecret="secret"),
        _payload(token="secret"),
        _payload(orgId=str(uuid4())),
    ],
)
def test_feishu_source_request_rejects_invalid_or_prohibited_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        FeishuSourceCreateRequest.model_validate(payload)
