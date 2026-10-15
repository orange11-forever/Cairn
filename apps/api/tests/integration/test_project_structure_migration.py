"""Upgrade preserves prior rows; DB constraints enforce project-scoped stages."""

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from .test_projects_api import _create_project, api_settings, client

# pyright: reportPrivateUsage=false
__all__ = ["api_settings", "client"]
pytestmark = pytest.mark.integration


def test_structure_upgrade_existing_data_composite_fk_and_safe_downgrade(
    client: TestClient,
    migrated_engine: Engine,
    test_database_url: str,
) -> None:
    project = _create_project(client, "Existing structure")
    other = _create_project(client, "Other structure")
    identity = client.get("/api/v1/session").json()
    org_id = identity["organization"]["id"]
    stage_id, other_stage, milestone_id, task_id = [uuid4() for _ in range(4)]
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    values = {
        "org": org_id,
        "project": project["id"],
        "other": other["id"],
        "stage": stage_id,
        "other_stage": other_stage,
        "milestone": milestone_id,
        "task": task_id,
    }
    try:
        command.downgrade(config, "0013_task_editing")
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO project_stages (id,org_id,project_id,name,position) VALUES (:stage,:org,:project,'Legacy Design',-1),(:other_stage,:org,:other,'Foreign',0)"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO milestones (id,org_id,project_id,name,description,due_at) VALUES (:milestone,:org,:project,'Legacy Review','Keep description','2026-10-09T01:02:03.123456+08:00')"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO tasks (id,org_id,project_id,title,stage_id,milestone_id) VALUES (:task,:org,:project,'Keep task',:stage,:milestone)"
                ),
                values,
            )
        command.upgrade(config, "head")
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT revision FROM projects WHERE id=:project"), values)
                == 1
            )
            stage = connection.execute(
                text("SELECT name,position,revision FROM project_stages WHERE id=:stage"), values
            ).one()
            assert tuple(stage) == ("Legacy Design", -1, 1)
            milestone = connection.execute(
                text(
                    "SELECT description,stage_id,acceptance_criteria,revision,EXTRACT(MICROSECONDS FROM due_at)::int FROM milestones WHERE id=:milestone"
                ),
                values,
            ).one()
            assert tuple(milestone) == ("Keep description", None, None, 1, 3123456)
            assert connection.execute(
                text("SELECT stage_id,milestone_id FROM tasks WHERE id=:task"), values
            ).one() == (stage_id, milestone_id)
        for statement in (
            "UPDATE milestones SET stage_id=:other_stage WHERE id=:milestone",
            "UPDATE projects SET revision=0 WHERE id=:project",
            "UPDATE project_stages SET revision=0 WHERE id=:stage",
            "UPDATE milestones SET revision=0 WHERE id=:milestone",
        ):
            with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
                connection.execute(text(statement), values)
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE milestones SET acceptance_criteria='Keep criteria' WHERE id=:milestone"
                ),
                values,
            )
        with pytest.raises(RuntimeError, match="edited project structure"):
            command.downgrade(config, "0013_task_editing")
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == ScriptDirectory.from_config(config).get_current_head()
            )
    finally:
        command.upgrade(config, "head")
