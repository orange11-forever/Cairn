"""Structure requests reject lost revision and unsafe grouping patches."""

from uuid import uuid4

import pytest
from cairn_api.projects import schemas
from pydantic import ValidationError


@pytest.mark.parametrize("position", [-1, None, 1.5, True, "0", 2147483648])
def test_stage_position_is_a_nonnegative_storage_integer(position: object) -> None:
    with pytest.raises(ValidationError):
        schemas.StageCreateRequest.model_validate(
            {"name": "X", "position": position, "expectedProjectRevision": 1}
        )


def test_structure_creation_requires_project_revision_and_valid_fields() -> None:
    for name, valid in (
        ("StageCreateRequest", {"name": "Design", "position": 0}),
        ("MilestoneCreateRequest", {"name": "Review"}),
    ):
        assert hasattr(schemas, name), f"missing {name}"
        model = getattr(schemas, name)
        with pytest.raises(ValidationError):
            model.model_validate(valid)
        parsed = model.model_validate({**valid, "expectedProjectRevision": 1})
        assert parsed.expected_project_revision == 1
        with pytest.raises(ValidationError):
            model.model_validate({**valid, "expectedProjectRevision": 0})


def test_structure_patch_requires_both_revisions_and_editable_field() -> None:
    for name in ("StageUpdateRequest", "MilestoneUpdateRequest"):
        assert hasattr(schemas, name), f"missing {name}"
        model = getattr(schemas, name)
        for invalid in (
            {},
            {"expectedRevision": 1, "name": "X"},
            {"expectedRevision": 1, "expectedProjectRevision": 1},
            {"expectedRevision": 1, "expectedProjectRevision": 1, "name": None},
        ):
            with pytest.raises(ValidationError):
                model.model_validate(invalid)
        assert (
            model.model_validate(
                {"expectedRevision": 1, "expectedProjectRevision": 1, "name": " X "}
            ).name
            == "X"
        )


def test_task_grouping_requires_project_revision_and_preserves_null_omission() -> None:
    for field in ("stageId", "milestoneId"):
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest.model_validate({"expectedRevision": 1, field: None})
        parsed = schemas.TaskUpdateRequest.model_validate(
            {"expectedRevision": 1, "expectedProjectRevision": 2, field: None}
        )
        assert parsed.model_dump(by_alias=True, exclude_unset=True)[field] is None
    with pytest.raises(ValidationError):
        schemas.TaskUpdateRequest.model_validate(
            {"expectedRevision": 1, "expectedProjectRevision": 2}
        )
    create = schemas.TaskCreateRequest.model_validate(
        {"title": "X", "milestoneId": str(uuid4()), "expectedProjectRevision": 1}
    )
    assert create.milestone_id is not None


@pytest.mark.parametrize("field", ["stageId", "milestoneId"])
def test_grouping_schema_requires_nonnull_project_revision_even_with_ordinary_edits(
    field: str,
) -> None:
    for body in (
        {"expectedRevision": 1, "expectedProjectRevision": None, field: None},
        {"expectedRevision": 1, "expectedProjectRevision": None, field: None, "title": "Keep"},
    ):
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest.model_validate(body)
    public = schemas.TaskUpdateRequest.model_json_schema(by_alias=True)
    branch = next(branch for branch in public["anyOf"] if field in branch["required"])
    assert branch["properties"]["expectedProjectRevision"].get("type") == "integer"
    assert branch["properties"]["expectedProjectRevision"].get("minimum") == 1
    assert (
        schemas.TaskUpdateRequest.model_validate(
            {"expectedRevision": 1, "title": "Keep", "expectedProjectRevision": None}
        ).title
        == "Keep"
    )


@pytest.mark.parametrize(
    "field,value",
    [("description", None), ("acceptanceCriteria", None), ("dueAt", None), ("stageId", None)],
)
def test_milestone_patch_explicit_clear(field: str, value: object) -> None:
    assert hasattr(schemas, "MilestoneUpdateRequest")
    body = {"expectedRevision": 1, "expectedProjectRevision": 1, field: value}
    assert (
        schemas.MilestoneUpdateRequest.model_validate(body).model_dump(
            by_alias=True, exclude_unset=True
        )
        == body
    )


@pytest.mark.parametrize("model", [schemas.StageUpdateRequest, schemas.MilestoneUpdateRequest])
def test_lifecycle_patch_is_strict_exclusive_and_public_schema_matches(
    model: type[schemas.StructureUpdateRequest],
) -> None:
    base = {"expectedRevision": 1, "expectedProjectRevision": 2}
    for archived in (True, False):
        parsed = model.model_validate({**base, "archived": archived})
        assert parsed.model_dump(by_alias=True, exclude_unset=True) == {
            **base,
            "archived": archived,
        }
    for archived in (None, "true", "false", 0, 1):
        with pytest.raises(ValidationError):
            model.model_validate({**base, "archived": archived})
    with pytest.raises(ValidationError):
        model.model_validate({**base, "archived": True, "name": "Mixed"})
    schema = model.model_json_schema(by_alias=True)
    lifecycle = next(branch for branch in schema["anyOf"] if "archived" in branch["required"])
    assert lifecycle["properties"]["archived"] == {"title": "Archived", "type": "boolean"}
    assert lifecycle["properties"]["name"] is False
    for branch in schema["anyOf"]:
        if "archived" not in branch["required"]:
            assert branch["properties"]["archived"] is False


@pytest.mark.parametrize(
    "model,extra",
    [(schemas.StageCreateRequest, {"position": 0}), (schemas.MilestoneCreateRequest, {})],
)
def test_create_cannot_set_archived(
    model: type[schemas.StructureCreateRequest], extra: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(
            {"name": "X", "expectedProjectRevision": 1, "archived": False, **extra}
        )


@pytest.mark.parametrize(
    "path,method,codes",
    [
        ("/api/v1/projects/{project_id}/stages", "post", {"revision_conflict"}),
        (
            "/api/v1/projects/{project_id}/stages/{stage_id}",
            "patch",
            {"revision_conflict", "structure_in_use", "structure_archived"},
        ),
        (
            "/api/v1/projects/{project_id}/milestones",
            "post",
            {"revision_conflict", "structure_archived"},
        ),
        (
            "/api/v1/projects/{project_id}/milestones/{milestone_id}",
            "patch",
            {"revision_conflict", "structure_in_use", "structure_archived", "milestone_in_use"},
        ),
        (
            "/api/v1/projects/{project_id}/tasks",
            "post",
            {"revision_conflict", "structure_archived"},
        ),
        ("/api/v1/tasks/{task_id}", "patch", {"revision_conflict", "structure_archived"}),
    ],
)
def test_openapi_documents_observable_structure_and_grouping_conflicts(
    path: str, method: str, codes: set[str]
) -> None:
    from cairn_api.app import create_app
    from cairn_api.db.session import Database
    from cairn_api.settings import Settings

    database = Database("postgresql+psycopg://unused/unused")
    try:
        app = create_app(
            Settings(
                environment="test",
                database_url="postgresql+psycopg://unused/unused",
                _env_file=None,  # pyright: ignore[reportCallIssue]
            ),
            database,
        )
        response = app.openapi()["paths"][path][method]["responses"]["409"]
        assert all(code in response["description"] for code in codes), response["description"]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorBody")
        assert set(response["headers"]) == {
            "X-Request-ID",
            "Cache-Control",
            "X-Content-Type-Options",
        }
    finally:
        database.dispose()
