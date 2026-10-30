import json
from uuid import uuid4

import httpx
import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import OpenAIAnswerProvider
from sqlalchemy import select

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_knowledge_search import SearchEmbedding
from .test_project_conversations import create, seed_conversation_boundary

CONTENT = "---\nname: 合成技能\ndescription: 摘要说明\n---\n仅根据本轮知识总结并引用。"


@pytest.mark.integration
def test_settings_import_and_actual_guidance_with_semantic_replay(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    payloads: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(json.loads(request.content)["input"]))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "status": "answered",
                                        "paragraphs": [
                                            {"text": "9月30日交付", "citationIds": ["S1"]}
                                        ],
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    provider = OpenAIAnswerProvider(
        base_url="https://controlled.test/v1",
        api_key="synthetic",
        model="gpt-test",
        timeout_seconds=5,
        protocol="openai-responses",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        default = client.get(prefix + "/assistant-settings").json()
        assert default == {"id": None, "name": "岑宁", "instructions": "", "enabledSkillIds": [], "revision": 0, "modelId": None, "avatarDataUrl": None}
        settings: dict[str, object] = {
            "expectedRevision": 0,
            "name": "岑宁",
            "instructions": "",
            "enabledSkillIds": [],
        }
        assert client.put(prefix + "/assistant-settings", json=settings).json()["revision"] == 1
        settings["expectedRevision"] = 1
        assert client.put(prefix + "/assistant-settings", json=settings).json()["revision"] == 1
        source = {"type": "markdown", "fileName": "SKILL.md", "content": CONTENT}
        preview = client.post(prefix + "/skills/preview", json={"source": source})
        assert preview.status_code == 200
        iid = str(uuid4())
        imported = {"id": iid, "source": source, "expectedDigest": preview.json()["digest"]}
        assert client.post(prefix + "/skills/import", json=imported).status_code == 201
        assert client.post(prefix + "/skills/import", json=imported).status_code == 200
        assert (
            client.post(
                prefix + "/skills/import", json={**imported, "expectedDigest": "0" * 64}
            ).status_code
            == 409
        )
        assert len(client.get(prefix + "/skills").json()["items"]) == 3
        settings.update(name="合成助手", instructions="优先列结论", enabledSkillIds=[iid])
        assert client.put(prefix + "/assistant-settings", json=settings).json()["revision"] == 2
        cid, tid = create(client, prefix), str(uuid4())
        turn = {
            "id": tid,
            "expectedRevision": 1,
            "question": "什么时候交付？",
            "assistantRevision": 2,
            "skillId": iid,
        }
        saved = client.post(f"{prefix}/conversations/{cid}/turns", json=turn)
        assert saved.status_code == 200
        assert saved.json()["turns"][0]["assistantName"] == "合成助手"
        assert saved.json()["turns"][0]["skillId"] == iid
        settings.update(expectedRevision=2, name="更新后的助手")
        assert client.put(prefix + "/assistant-settings", json=settings).json()["revision"] == 3
        assert client.post(f"{prefix}/conversations/{cid}/turns", json=turn).status_code == 200
        assert (
            client.post(
                f"{prefix}/conversations/{cid}/turns", json={**turn, "skillId": None}
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"{prefix}/conversations/{cid}/turns",
                json={**turn, "id": str(uuid4()), "expectedRevision": 2},
            ).status_code
            == 409
        )
        assert saved.headers["cache-control"] == "private, no-store"
        assert len(payloads) == 1
        guidance = payloads[0]["guidance"]
        assert isinstance(guidance, dict)
        assert guidance["skill_id"] == iid and guidance["assistant_name"] == "合成助手"
        assert guidance["skill_instructions"] == "仅根据本轮知识总结并引用。"
    with database.session_factory() as session:
        audits = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.action.in_(
                        ["knowledge.assistant_configured", "knowledge.skill_imported"]
                    )
                )
            )
        )
        assert len(audits) == 4
        assert "优先列结论" not in str([audit.details for audit in audits])


@pytest.mark.integration
def test_private_settings_import_scope_validation_and_headers(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    other = seed_actor(database, MembershipRole.ADMIN, org_id=actor.organization_id)
    outsider = seed_actor(database, MembershipRole.ADMIN)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    source = {"type": "markdown", "fileName": "SKILL.md", "content": CONTENT}
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        preview = client.post(prefix + "/skills/preview", json={"source": source}).json()
        imported = {"id": str(uuid4()), "source": source, "expectedDigest": preview["digest"]}
        assert client.post(prefix + "/skills/import", json=imported).status_code == 201
        settings: dict[str, object] = {
            "expectedRevision": 0,
            "name": "私有助手",
            "instructions": "私有说明",
            "enabledSkillIds": [],
        }
        assert client.put(prefix + "/assistant-settings", json=settings).status_code == 200
        for revision in (True, None, -1):
            assert (
                client.put(
                    prefix + "/assistant-settings", json={**settings, "expectedRevision": revision}
                ).status_code
                == 422
            )
        assert client.put(prefix + "/assistant-settings", json=settings).status_code == 409
        assert (
            client.put(
                prefix + "/assistant-settings",
                json={**settings, "expectedRevision": 1, "enabledSkillIds": ["unknown"]},
            ).status_code
            == 422
        )
        denied = client.put(
            prefix + "/assistant-settings", json=settings, headers={"X-CSRF-Token": "wrong"}
        )
        assert (
            denied.status_code == 403 and denied.json()["traceId"] == denied.headers["x-request-id"]
        )
        assert denied.headers["cache-control"] == "private, no-store"
        operation = client.get("/openapi.json").json()["paths"][
            "/api/v1/projects/{project_id}/knowledge/skills/import"
        ]["post"]
        assert (
            operation["responses"]["200"]["content"]["application/json"]["schema"]
            == operation["responses"]["201"]["content"]["application/json"]["schema"]
        )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        other,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        assert client.get(prefix + "/assistant-settings").json()["revision"] == 0
        assert len(client.get(prefix + "/skills").json()["items"]) == 2
        assert client.post(prefix + "/skills/import", json=imported).status_code == 404
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        outsider,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        assert client.get(prefix + "/assistant-settings").status_code == 404
        assert client.get(prefix + "/skills").status_code == 404


@pytest.mark.integration
def test_assistant_migration_retains_configuration_and_old_turn_defaults(
    database: Database, test_database_url: str
) -> None:
    from alembic import command
    from alembic.config import Config

    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.downgrade(config, "0016_project_conversations")
    command.upgrade(config, "head")
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        settings: dict[str, object] = {
            "expectedRevision": 0,
            "name": "岑宁",
            "instructions": "",
            "enabledSkillIds": [],
        }
        assert client.put(prefix + "/assistant-settings", json=settings).status_code == 200
        with pytest.raises(RuntimeError, match="populated assistant skills"):
            command.downgrade(config, "0016_project_conversations")
        assert client.get(prefix + "/assistant-settings").json()["revision"] == 1


@pytest.mark.integration
def test_configuration_change_during_model_discards_turn(
    database: Database, test_database_url: str
) -> None:
    from cairn_api.knowledge.answer_provider import (
        AnswerEvidence,
        AnswerGuidance,
        AnswerHistoryTurn,
        ProviderAnswer,
        ProviderParagraph,
    )
    from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings
    from cairn_api.knowledge.conversation_models import KnowledgeConversationTurn

    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"

    class MutatingProvider:
        def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
            raise AssertionError("configured guidance must be used")

        def generate_with_guidance(
            self,
            *,
            question: str,
            evidence: list[AnswerEvidence],
            history: list[AnswerHistoryTurn],
            guidance: AnswerGuidance,
        ) -> ProviderAnswer:
            with database.session_factory.begin() as session:
                row = session.scalar(
                    select(KnowledgeAssistantSettings).where(
                        KnowledgeAssistantSettings.owner_id == actor.user_id
                    )
                )
                assert row is not None
                row.revision += 1
            return ProviderAnswer(
                status="answered", paragraphs=[ProviderParagraph(text="事实", citationIds=["S1"])]
            )

    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        MutatingProvider(),
    ) as client:
        assert (
            client.put(
                prefix + "/assistant-settings",
                json={
                    "expectedRevision": 0,
                    "name": "合成助手",
                    "instructions": "",
                    "enabledSkillIds": [],
                },
            ).status_code
            == 200
        )
        cid = create(client, prefix)
        response = client.post(
            f"{prefix}/conversations/{cid}/turns",
            json={
                "id": str(uuid4()),
                "expectedRevision": 1,
                "question": "什么时候交付？",
                "assistantRevision": 1,
            },
        )
        assert response.status_code == 409 and response.json()["code"] == "assistant_changed"
    with database.session_factory() as session:
        assert list(session.scalars(select(KnowledgeConversationTurn))) == []
