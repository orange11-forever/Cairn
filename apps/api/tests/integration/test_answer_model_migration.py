import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from cairn_api.db.session import Database
from sqlalchemy import Engine, text

from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_knowledge_search import SearchEmbedding
from .test_project_conversations import seed_conversation_boundary


@pytest.mark.integration
def test_upgrade_retains_old_settings_and_turns_and_downgrade_preserves_new_data(
    database: Database, migrated_engine: Engine, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    cid, tid, aid = uuid4(), uuid4(), uuid4()
    answer: dict[str, object] = {
        "status": "insufficient_evidence",
        "retrieval_mode": "hybrid",
        "paragraphs": [],
        "citations": [],
    }
    try:
        command.downgrade(config, "0017_assistant_skills")
        with migrated_engine.begin() as connection:
            values = {
                "org": actor.organization_id,
                "pid": pid,
                "owner": actor.user_id,
                "cid": cid,
                "tid": tid,
                "aid": aid,
                "answer": json.dumps(answer),
            }
            connection.execute(
                text(
                    "INSERT INTO knowledge_assistant_settings (id,org_id,project_id,owner_id,name,instructions,enabled_skill_ids,revision) VALUES (:aid,:org,:pid,:owner,'原助手','保留说明','[]',3)"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_conversations (id,org_id,project_id,owner_id,title,revision) VALUES (:cid,:org,:pid,:owner,'原对话',2)"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_conversation_turns (id,org_id,project_id,conversation_id,sequence,question,answer,assistant_name,assistant_revision) VALUES (:tid,:org,:pid,:cid,1,'旧的问题',CAST(:answer AS jsonb),'原助手',3)"
                ),
                values,
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
            assert client.get(prefix + "/assistant-settings").json() == {
                "id": str(aid),
                "name": "原助手",
                "instructions": "保留说明",
                "enabledSkillIds": [],
                "revision": 3,
                "modelId": None,
                "avatarDataUrl": None,
            }
            detail = client.get(f"{prefix}/conversations/{cid}").json()
            assert detail["revision"] == 2
            assert detail["turns"][0]["model"] is None
            assert detail["turns"][0]["assistantName"] == "原助手"
        with migrated_engine.begin() as connection:
            connection.execute(
                text("UPDATE knowledge_assistant_settings SET model_id='chosen' WHERE id=:id"),
                {"id": aid},
            )
        with pytest.raises(RuntimeError, match="populated answer model"):
            command.downgrade(config, "0017_assistant_skills")
        with migrated_engine.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT model_id FROM knowledge_assistant_settings WHERE id=:id"),
                    {"id": aid},
                )
                == "chosen"
            )
            connection.execute(
                text("UPDATE knowledge_assistant_settings SET model_id=NULL WHERE id=:id"),
                {"id": aid},
            )
            connection.execute(
                text(
                    "UPDATE knowledge_conversation_turns SET model_snapshot=CAST(:snapshot AS jsonb) WHERE id=:id"
                ),
                {
                    "id": tid,
                    "snapshot": json.dumps(
                        {
                            "id": "chosen",
                            "name": "已使用模型",
                            "model": "synthetic",
                            "protocol": "openai-compatible",
                        }
                    ),
                },
            )
        with pytest.raises(RuntimeError, match="populated answer model"):
            command.downgrade(config, "0017_assistant_skills")
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT model_snapshot->>'id' FROM knowledge_conversation_turns WHERE id=:id"
                    ),
                    {"id": tid},
                )
                == "chosen"
            )
    finally:
        command.upgrade(config, "head")
