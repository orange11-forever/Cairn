from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import AnswerGuidance, ProviderAnswer, ProviderParagraph
from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_knowledge_search import SearchEmbedding
from .test_project_conversations import (
    ConversationProvider,
    assert_error,
    create,
    seed_conversation_boundary,
)


class AssistantProvider(ConversationProvider):
    def __init__(self) -> None:
        super().__init__()
        self.guidance: list[AnswerGuidance] = []

    def generate_with_guidance(self, *, guidance: AnswerGuidance, **kwargs: Any) -> ProviderAnswer:
        self.guidance.append(guidance)
        return ProviderAnswer(
            status="answered",
            paragraphs=[ProviderParagraph(text="9月30日交付", citationIds=["S1"])],
        )


@pytest.mark.integration
def test_create_switch_edit_and_answer_preserve_independent_assistant_settings(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    provider = AssistantProvider()
    prefix = f"/api/v1/projects/{pid}/knowledge"
    settings = knowledge_settings(test_database_url, answer_model="synthetic")
    with knowledge_client(
        settings, database, actor, MemoryObjectStore(), SearchEmbedding(), provider
    ) as client:
        plan = {
            "expectedRevision": 0,
            "name": "规划助手",
            "instructions": "先列计划",
            "enabledSkillIds": ["knowledge-summary"],
            "modelId": "default",
        }
        first = client.put(prefix + "/assistant-settings", json=plan).json()
        aid = first["id"]
        review: dict[str, object] = {
            "expectedRevision": 1,
            "name": "复核助手",
            "instructions": "指出风险",
            "enabledSkillIds": [],
            "modelId": None,
        }
        response = client.post(prefix + "/assistants", json=review)
        assert response.status_code == 201
        second = response.json()
        bid = second["id"]
        assert bid != aid and second["revision"] == 2
        assert {item["id"] for item in client.get(prefix + "/assistants").json()["items"]} == {
            aid,
            bid,
        }
        assert_error(client.post(prefix + "/assistants", json=review), 409, "assistant_changed")
        cid = create(client, prefix)
        body = {
            "id": str(uuid4()),
            "expectedRevision": 1,
            "assistantRevision": 2,
            "question": "何时交付？",
        }
        saved = client.post(f"{prefix}/conversations/{cid}/turns", json=body)
        assert saved.status_code == 200
        assert saved.json()["turns"][0]["assistantId"] == bid
        selected = client.post(f"{prefix}/assistants/{aid}/select", json={"expectedRevision": 2})
        assert selected.status_code == 200
        assert selected.json() == {**first, "revision": 3}
        assert (
            client.post(f"{prefix}/assistants/{aid}/select", json={"expectedRevision": 3}).json()[
                "revision"
            ]
            == 3
        )
        assert_error(client.post(
            f"{prefix}/conversations/{cid}/turns",
            json={**body, "id": str(uuid4()), "expectedRevision": 2, "assistantRevision": 3},
        ), 409, "conversation_assistant_mismatch")
        first_cid = create(client, prefix)
        next_turn = client.post(
            f"{prefix}/conversations/{first_cid}/turns",
            json={**body, "id": str(uuid4()), "expectedRevision": 1, "assistantRevision": 3, "skillId": "knowledge-summary"},
        )
        assert next_turn.status_code == 200
        assert [turn["assistantId"] for turn in next_turn.json()["turns"]] == [aid]
        assert [(item.assistant_name, item.instructions, item.skill_id) for item in provider.guidance] == [("复核助手", "指出风险", None), ("规划助手", "先列计划", "knowledge-summary")]
        assert client.post(f"{prefix}/conversations/{cid}/turns", json=body).json() == saved.json()
        assert len(provider.guidance) == 2
        updated = client.put(
            prefix + "/assistant-settings", json={**plan, "expectedRevision": 3, "name": "计划助手"}
        )
        assert updated.json()["revision"] == 4
        back = client.post(f"{prefix}/assistants/{bid}/select", json={"expectedRevision": 4})
        assert back.json() == {**second, "revision": 5}
        assert client.get(prefix + "/assistant-settings").json() == back.json()
        assert_error(
            client.put(prefix + "/assistant-settings", json={**review, "expectedRevision": 2}),
            409,
            "assistant_changed",
        )
    other = seed_actor(database, MembershipRole.ADMIN, org_id=actor.organization_id)
    with knowledge_client(
        settings, database, other, MemoryObjectStore(), SearchEmbedding(), provider
    ) as client:
        assert client.get(prefix + "/assistants").json() == {"items": []}
        assert client.get(prefix + "/assistant-settings").json()["id"] is None
        assert_error(
            client.post(f"{prefix}/assistants/{aid}/select", json={"expectedRevision": 0}),
            404,
            "not_found",
        )


@pytest.mark.integration
def test_first_creation_keeps_default_and_concurrent_create_has_one_winner(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    body: dict[str, object] = {
        "expectedRevision": 0,
        "name": "新助手",
        "instructions": "",
        "enabledSkillIds": [],
    }
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        assert_error(
            client.post(prefix + "/assistants", json=body, headers={"X-CSRF-Token": "invalid"}),
            403,
            "csrf_failed",
        )
        assert_error(
            client.post(prefix + "/assistants", json={**body, "modelId": "unlisted"}),
            422,
            "model_not_available",
        )
        assert client.get(prefix + "/assistants").json() == {"items": []}
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = [
                executor.submit(client.post, prefix + "/assistants", json=body) for _ in range(2)
            ]
            responses = [future.result(timeout=10) for future in pending]
        assert sorted(response.status_code for response in responses) == [201, 409]
        items = client.get(prefix + "/assistants").json()["items"]
        assert sorted(item["name"] for item in items) == ["岑宁", "新助手"]
        default_id = next(item["id"] for item in items if item["name"] == "岑宁")
        assert_error(
            client.post(
                f"{prefix}/assistants/{default_id}/select",
                json={"expectedRevision": 1},
                headers={"X-CSRF-Token": "invalid"},
            ),
            403,
            "csrf_failed",
        )
        restored = client.post(
            f"{prefix}/assistants/{default_id}/select", json={"expectedRevision": 1}
        )
        assert restored.json()["revision"] == 2
        assert restored.json()["instructions"] == "" and restored.json()["enabledSkillIds"] == []
        contract = client.get("/openapi.json").json()["paths"][
            "/api/v1/projects/{project_id}/knowledge/assistants"
        ]["post"]["responses"]
        assert "200" not in contract
        assert contract["201"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/AssistantSettingsResponse"
        }
        assert "X-Request-ID" in contract["201"]["headers"]


@pytest.mark.integration
def test_assistant_limit_rejects_creation_without_changing_active_profile(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    body: dict[str, object] = {
        "expectedRevision": 0,
        "name": "原助手",
        "instructions": "",
        "enabledSkillIds": [],
    }
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        current = client.put(prefix + "/assistant-settings", json=body).json()
        with database.session_factory.begin() as session:
            for index in range(19):
                session.add(
                    KnowledgeAssistantSettings(
                        id=uuid4(),
                        org_id=actor.organization_id,
                        project_id=pid,
                        owner_id=actor.user_id,
                        name=f"备用{index}",
                        instructions="",
                        enabled_skill_ids=[],
                        revision=1,
                        is_active=False,
                    )
                )
        assert len(client.get(prefix + "/assistants").json()["items"]) == 20
        assert_error(
            client.post(prefix + "/assistants", json={**body, "expectedRevision": 1}),
            409,
            "assistant_limit",
        )
        assert client.get(prefix + "/assistant-settings").json() == current


@pytest.mark.integration
def test_switch_during_generation_rejects_old_assistant_turn(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    entered, release = Event(), Event()

    class WaitingProvider(AssistantProvider):
        def generate_with_guidance(
            self, *, guidance: AnswerGuidance, **kwargs: Any
        ) -> ProviderAnswer:
            entered.set()
            assert release.wait(10)
            return super().generate_with_guidance(guidance=guidance, **kwargs)

    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        WaitingProvider(),
    ) as client:
        second = client.post(
            prefix + "/assistants",
            json={
                "expectedRevision": 0,
                "name": "新助手",
                "instructions": "说明交付",
                "enabledSkillIds": [],
            },
        )
        assert second.status_code == 201
        original = next(
            item
            for item in client.get(prefix + "/assistants").json()["items"]
            if item["name"] == "岑宁"
        )
        cid = create(client, prefix)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                client.post,
                f"{prefix}/conversations/{cid}/turns",
                json={
                    "id": str(uuid4()),
                    "expectedRevision": 1,
                    "assistantRevision": 1,
                    "question": "何时交付？",
                },
            )
            try:
                assert entered.wait(5)
                switched = client.post(
                    f"{prefix}/assistants/{original['id']}/select", json={"expectedRevision": 1}
                )
                assert switched.status_code == 200 and switched.json()["revision"] == 2
            finally:
                release.set()
            assert_error(future.result(timeout=10), 409, "assistant_changed")
        assert client.get(f"{prefix}/conversations/{cid}").json()["turns"] == []


@pytest.mark.integration
def test_assistant_context_and_history_are_isolated_without_losing_legacy_reads(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    provider = AssistantProvider()
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore(), SearchEmbedding(), provider) as client:
        first = client.put(prefix + "/assistant-settings", json={"expectedRevision": 0, "name": "计划", "instructions": "先列计划", "enabledSkillIds": []}).json()
        cid = create(client, prefix)
        first_turn = {"id": str(uuid4()), "question": "何时交付？", "expectedRevision": 1, "assistantRevision": 1}
        response = client.post(f"{prefix}/conversations/{cid}/turns", json=first_turn)
        assert response.status_code == 200
        original = response.json()
        second = client.post(prefix + "/assistants", json={"expectedRevision": 1, "name": "复核", "instructions": "指出风险", "enabledSkillIds": []}).json()
        assert client.get(prefix + "/conversations?currentAssistant=true").json()["items"] == []
        assert_error(client.post(f"{prefix}/conversations/{cid}/turns", json={**first_turn, "id": str(uuid4()), "expectedRevision": 2, "assistantRevision": 2}), 409, "conversation_assistant_mismatch")
        assert client.get(f"{prefix}/conversations/{cid}").json() == original
        cid2 = create(client, prefix)
        assert client.post(f"{prefix}/conversations/{cid2}/turns", json={**first_turn, "id": str(uuid4()), "assistantRevision": 2}).status_code == 200
        assert [item["id"] for item in client.get(prefix + "/conversations?currentAssistant=true").json()["items"]] == [str(cid2)]
        assert len(client.get(prefix + "/conversations").json()["items"]) == 2
        assert client.post(f"{prefix}/assistants/{first['id']}/select", json={"expectedRevision": 2}).status_code == 200
        assert [item["id"] for item in client.get(prefix + "/conversations?currentAssistant=true").json()["items"]] == [str(cid)]
        result = client.post(f"{prefix}/conversations/{cid}/turns", json={**first_turn, "id": str(uuid4()), "expectedRevision": 2, "assistantRevision": 3})
        assert result.status_code == 200
        assert len(provider.guidance) == 3
        assert [turn["assistantId"] for turn in result.json()["turns"]] == [first["id"], first["id"]]
        assert second["id"] != first["id"]
        assert result.json()["turns"][0] == original["turns"][0]


@pytest.mark.integration
def test_legacy_mixed_history_is_only_in_all_history(database: Database, test_database_url: str) -> None:
    from cairn_api.knowledge.conversation_models import KnowledgeConversationTurn
    from sqlalchemy import select

    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(knowledge_settings(test_database_url), database, actor, MemoryObjectStore(), SearchEmbedding(), AssistantProvider()) as client:
        config: dict[str, object] = {"expectedRevision": 0, "name": "当前助手", "instructions": "", "enabledSkillIds": []}
        current = client.put(prefix + "/assistant-settings", json=config).json()
        cid = create(client, prefix)
        for revision in (1, 2):
            assert client.post(f"{prefix}/conversations/{cid}/turns", json={"id": str(uuid4()), "question": "何时交付？", "expectedRevision": revision, "assistantRevision": 1}).status_code == 200
        with database.session_factory.begin() as session:
            turns = list(session.scalars(select(KnowledgeConversationTurn).where(KnowledgeConversationTurn.conversation_id == cid).order_by(KnowledgeConversationTurn.sequence)))
            turns[0].assistant_id = None
        assert client.get(prefix + "/conversations?currentAssistant=true").json()["items"] == []
        assert [item["id"] for item in client.get(prefix + "/conversations").json()["items"]] == [str(cid)]
        detail = client.get(f"{prefix}/conversations/{cid}").json()
        assert len(detail["turns"]) == 2 and detail["turns"][1]["assistantId"] == current["id"]
