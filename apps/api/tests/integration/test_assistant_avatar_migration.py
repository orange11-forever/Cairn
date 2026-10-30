from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from cairn_api.db.session import Database
from sqlalchemy import Engine, text

from apps.api.tests.test_assistant_avatar import avatar_png

from .test_project_conversations import seed_conversation_boundary


@pytest.mark.integration
def test_avatar_upgrade_preserves_profiles_and_downgrade_refuses_avatar_loss(
    database: Database, migrated_engine: Engine, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    aid = uuid4()
    try:
        command.downgrade(config, "0023_project_scheduling")
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge_assistant_settings (id,org_id,project_id,owner_id,name,instructions,enabled_skill_ids,revision,model_id) VALUES (:id,:org,:pid,:owner,'原有助手','原有说明','[]',7,'default')"
                ),
                {"id": aid, "org": actor.organization_id, "pid": pid, "owner": actor.user_id},
            )
        command.upgrade(config, "head")
        with migrated_engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT name,instructions,revision,model_id,avatar_data_url FROM knowledge_assistant_settings WHERE id=:id"
                ),
                {"id": aid},
            ).one()
            assert tuple(row) == ("原有助手", "原有说明", 7, "default", None)
            connection.execute(
                text(
                    "UPDATE knowledge_assistant_settings SET avatar_data_url=:avatar WHERE id=:id"
                ),
                {"id": aid, "avatar": avatar_png()},
            )
        with pytest.raises(RuntimeError, match="populated assistant avatars"):
            command.downgrade(config, "0023_project_scheduling")
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT avatar_data_url FROM knowledge_assistant_settings WHERE id=:id"),
                    {"id": aid},
                )
                == avatar_png()
            )
    finally:
        command.upgrade(config, "head")
