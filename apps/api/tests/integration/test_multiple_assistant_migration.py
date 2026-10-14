from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from cairn_api.db.session import Database
from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_knowledge_search import SearchEmbedding
from .test_project_conversations import seed_conversation_boundary


@pytest.mark.integration
def test_existing_assistant_keeps_identity_and_configuration_and_multiple_profiles_cannot_be_dropped(
    database: Database, migrated_engine: Engine, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    aid = uuid4()
    try:
        command.downgrade(config, "0018_answer_model_selection")
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge_assistant_settings (id,org_id,project_id,owner_id,name,instructions,enabled_skill_ids,revision,model_id) VALUES (:id,:org,:pid,:owner,'原助手','保留说明','[\"knowledge-summary\"]',7,NULL)"
                ),
                {"id": aid, "org": actor.organization_id, "pid": pid, "owner": actor.user_id},
            )
        command.upgrade(config, "head")
        prefix = f"/api/v1/projects/{pid}/knowledge"
        with knowledge_client(
            knowledge_settings(test_database_url),
            database,
            actor,
            MemoryObjectStore(),
            SearchEmbedding(),
        ) as client:
            before = client.get(prefix + "/assistant-settings").json()
            assert before == {
                "id": str(aid),
                "name": "原助手",
                "instructions": "保留说明",
                "enabledSkillIds": ["knowledge-summary"],
                "revision": 7,
                "modelId": None,
            }
            assert client.get(prefix + "/assistants").json() == {
                "items": [{"id": str(aid), "name": "原助手", "modelId": None}]
            }
            with pytest.raises(IntegrityError), database.session_factory.begin() as session:
                session.add(
                    KnowledgeAssistantSettings(
                        id=uuid4(),
                        org_id=actor.organization_id,
                        project_id=pid,
                        owner_id=actor.user_id,
                        name="重复活动助手",
                        instructions="",
                        enabled_skill_ids=[],
                        revision=8,
                        is_active=True,
                    )
                )
            created = client.post(
                prefix + "/assistants",
                json={
                    "expectedRevision": 7,
                    "name": "第二助手",
                    "instructions": "",
                    "enabledSkillIds": [],
                },
            )
            assert created.status_code == 201 and created.json()["revision"] == 8
            with pytest.raises(RuntimeError, match="populated multiple assistants"):
                command.downgrade(config, "0018_answer_model_selection")
            assert len(client.get(prefix + "/assistants").json()["items"]) == 2
            restored = client.post(
                f"{prefix}/assistants/{aid}/select", json={"expectedRevision": 8}
            )
            assert restored.json() == {**before, "revision": 9}
    finally:
        command.upgrade(config, "head")
