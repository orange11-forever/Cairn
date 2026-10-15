"""Existing tasks upgrade safely and assigned/edited data cannot be discarded."""

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from cairn_api.db.session import Database
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

# pyright: reportPrivateUsage=false
from .test_projects_api import _create_project, _create_task, api_settings, client

__all__ = ["api_settings", "client"]
pytestmark = pytest.mark.integration


def test_task_migration_defaults_constraints_and_safe_downgrade(
    client: TestClient, database: Database, migrated_engine: Engine, test_database_url: str
) -> None:
    project = _create_project(client, "Migration")
    task = _create_task(client, str(project["id"]), "Existing task")
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with migrated_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT revision FROM tasks WHERE id=:id"), {"id": task["id"]})
            == 1
        )
    try:
        # The task was created through the current writer, advancing the new
        # project revision. Restore the pre-0014 fixture before exercising 0013.
        with migrated_engine.begin() as connection:
            connection.execute(
                text("UPDATE projects SET revision=1 WHERE id=:id"), {"id": project["id"]}
            )
        command.downgrade(config, "0012_native_registration")
        command.upgrade(config, "head")
        with database.session_factory() as session:
            assert (
                session.scalar(text("SELECT revision FROM tasks WHERE id=:id"), {"id": task["id"]})
                == 1
            )
        for changes in ("revision=0", f"assignee_user_id='{uuid4()}'"):
            with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
                connection.execute(
                    text(f"UPDATE tasks SET {changes} WHERE id=:id"), {"id": task["id"]}
                )
        with migrated_engine.begin() as connection:
            connection.execute(text("UPDATE tasks SET revision=2 WHERE id=:id"), {"id": task["id"]})
        with pytest.raises(RuntimeError, match="edited or assigned tasks"):
            command.downgrade(config, "0012_native_registration")
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == ScriptDirectory.from_config(config).get_current_head()
            )
    finally:
        command.upgrade(config, "head")
