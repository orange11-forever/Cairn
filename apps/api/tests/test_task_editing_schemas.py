"""Consumer validation: catch empty patches, lost null semantics and unsafe writes."""

import pytest
from cairn_api.projects import schemas
from pydantic import ValidationError


def test_task_edit_accepts_explicit_null_but_preserves_missing_fields() -> None:
    assert hasattr(schemas, "TaskUpdateRequest"), "Task PATCH schema is missing"
    patch = schemas.TaskUpdateRequest.model_validate(  # type: ignore[attr-defined]
        {"expectedRevision": 1, "title": " Updated ", "description": None}
    )
    assert patch.title == "Updated"
    assert patch.model_fields_set == {"expected_revision", "title", "description"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expectedRevision": 1},
        {"expectedRevision": 0, "title": "x"},
        {"expectedRevision": 1, "title": None},
        {"expectedRevision": 1, "title": "  "},
        {"expectedRevision": 1, "priority": None},
        {"expectedRevision": 1, "status": "done"},
        {"expectedRevision": 1, "dueAt": "2026-10-05T10:00:00"},
        {"expectedRevision": 1, "description": "x" * 10001},
    ],
)
def test_task_edit_rejects_unsafe_or_empty_patch(payload: dict[str, object]) -> None:
    assert hasattr(schemas, "TaskUpdateRequest"), "Task PATCH schema is missing"
    with pytest.raises(ValidationError):
        schemas.TaskUpdateRequest.model_validate(payload)  # type: ignore[attr-defined]


def test_legacy_write_payloads_remain_valid_and_revision_can_be_supplied() -> None:
    assert "expected_revision" in schemas.TaskStatusUpdateRequest.model_fields
    assert schemas.TaskStatusUpdateRequest(status="todo").expected_revision is None  # type: ignore[attr-defined]
    assert (
        schemas.TaskStatusUpdateRequest.model_validate(
            {"status": "todo", "expectedRevision": 2}
        ).expected_revision
        == 2
    )  # type: ignore[attr-defined]
    assert (
        schemas.TaskCreateRequest.model_validate(
            {"title": "Create", "description": "Details", "assigneeUserId": None}
        ).description
        == "Details"
    )  # type: ignore[attr-defined]


def test_patch_public_schema_does_not_advertise_null_title_or_priority() -> None:
    properties = schemas.TaskUpdateRequest.model_json_schema(by_alias=True)["anyOf"][0][
        "properties"
    ]
    assert properties["title"].get("type") == "string"
    assert "anyOf" not in properties["priority"]
    assert "default" not in properties["title"]
    assert "default" not in properties["priority"]


@pytest.mark.parametrize(
    "field,value,internal",
    [
        ("title", "Updated", "title"),
        ("description", "Details", "description"),
        ("description", None, "description"),
        ("assigneeUserId", "00000000-0000-4000-8000-000000001001", "assignee_user_id"),
        ("assigneeUserId", None, "assignee_user_id"),
        ("priority", "critical", "priority"),
        ("dueAt", "2026-10-05T09:00:00+08:00", "due_at"),
        ("dueAt", None, "due_at"),
        ("acceptanceCriteria", "Observable", "acceptance_criteria"),
        ("acceptanceCriteria", None, "acceptance_criteria"),
    ],
)
def test_task_edit_single_field_agrees_with_nullable_omission_contract(
    field: str, value: object, internal: str
) -> None:
    body = {"expectedRevision": 1, field: value}
    parsed = schemas.TaskUpdateRequest.model_validate(body)
    assert parsed.model_fields_set == {"expected_revision", internal}
    assert parsed.model_dump(mode="json", exclude_unset=True, by_alias=True) == body


def test_public_task_edit_contract_requires_one_editable_field() -> None:
    schema = schemas.TaskUpdateRequest.model_json_schema(by_alias=True)
    branches = schema.get("anyOf", [])
    assert len(branches) == 10
    assert {tuple(branch["required"]) for branch in branches} == {
        ("expectedRevision", "title"),
        ("expectedRevision", "description"),
        ("expectedRevision", "assigneeUserId"),
        ("expectedRevision", "priority"),
        ("expectedRevision", "dueAt"),
        ("expectedRevision", "acceptanceCriteria"),
        ("expectedRevision", "estimatedEffortMinutes"),
        ("expectedRevision", "remainingEffortMinutes"),
        ("expectedRevision", "stageId", "expectedProjectRevision"),
        ("expectedRevision", "milestoneId", "expectedProjectRevision"),
    }
    assert all(branch["additionalProperties"] is False for branch in branches)
