"""Migration backfills archive flags and refuses destructive downgrade."""

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from .test_projects_api import api_settings, client
from .test_structure_lifecycle_api import structure

__all__ = ["api_settings", "client"]
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("archived_table", ["project_stages", "milestones"])
def test_archive_migration_backfills_and_retains_archived_history(
    client: TestClient, migrated_engine: Engine, test_database_url: str, archived_table: str
) -> None:
    _, stage, milestone = structure(client)
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    try:
        command.downgrade(config, "0014_project_structure")
        command.upgrade(config, "head")
        with migrated_engine.connect() as connection:
            for table, row in (("project_stages", stage), ("milestones", milestone)):
                assert (
                    connection.scalar(
                        text(f"SELECT archived FROM {table} WHERE id=:id"), {"id": row["id"]}
                    )
                    is False
                )
        selected = stage if archived_table == "project_stages" else milestone
        with migrated_engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {archived_table} SET archived=true WHERE id=:id"),
                {"id": selected["id"]},
            )
        with pytest.raises(RuntimeError, match="archived project structure"):
            command.downgrade(config, "0014_project_structure")
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == ScriptDirectory.from_config(config).get_current_head()
            )
            for table, row in (("project_stages", stage), ("milestones", milestone)):
                stored = connection.execute(
                    text(f"SELECT name,archived FROM {table} WHERE id=:id"), {"id": row["id"]}
                ).one()
                assert stored.name == row["name"]
                assert stored.archived is (table == archived_table)
    finally:
        command.upgrade(config, "head")
