import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from cairn_api.auth.models import AuthSession
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import ProviderAnswer, ProviderParagraph
from cairn_api.knowledge.conversation_models import KnowledgeConversationTurn
from httpx2 import Response
from sqlalchemy import delete, select

from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings
from .test_knowledge_search import SearchEmbedding
from .test_project_conversations import (
    ConversationProvider,
    assert_error,
    create,
    seed_conversation_boundary,
)


class StreamingProvider(ConversationProvider):
    def __init__(self, mutate: Callable[[], None] = lambda: None) -> None:
        super().__init__()
        self.mutate = mutate
        self.calls = 0

    def generate_stream(
        self,
        *,
        on_paragraph: Callable[[ProviderParagraph], None],
        check_cancelled: Callable[[], None],
        **kwargs: Any,
    ) -> ProviderAnswer:
        self.calls += 1
        first = ProviderParagraph(text="第一段。", citationIds=["S1"])
        second = ProviderParagraph(text="第二段。", citationIds=["S1"])
        on_paragraph(first)
        self.mutate()
        check_cancelled()
        on_paragraph(second)
        return ProviderAnswer(status="answered", paragraphs=[first, second])


def events(response: Response) -> list[dict[str, Any]]:
    return [
        json.loads(frame.removeprefix("data: ")) for frame in response.text.strip().split("\n\n")
    ]


@pytest.mark.integration
def test_stream_persists_once_and_replays_complete_without_provider(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)

    def still_unsaved() -> None:
        with database.session_factory() as session:
            assert not list(session.scalars(select(KnowledgeConversationTurn)))

    provider = StreamingProvider(still_unsaved)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        cid = create(client, prefix)
        body = {"id": str(uuid4()), "expectedRevision": 1, "question": "何时交付？"}
        response = client.post(f"{prefix}/conversations/{cid}/turns/stream", json=body)
        assert response.status_code == 200
        received = events(response)
        assert [e["type"] for e in received] == ["paragraph", "paragraph", "complete"]
        assert [e["index"] for e in received[:2]] == [0, 1]
        assert received[-1]["conversation"]["revision"] == 2
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["access-control-allow-origin"]
        operation = client.get("/openapi.json").json()["paths"][
            "/api/v1/projects/{project_id}/knowledge/conversations/{conversation_id}/turns/stream"
        ]["post"]
        assert operation["responses"]["200"]["content"] == {
            "text/event-stream": {
                "schema": {"$ref": "#/components/schemas/KnowledgeConversationStreamEvent"}
            }
        }
        for status in ("401", "403", "404", "409", "422", "429", "500", "503"):
            assert operation["responses"][status]["content"] == {
                "application/json": {"schema": {"$ref": "#/components/schemas/ErrorBody"}}
            }
        assert {"401", "403", "404", "409", "422", "429", "500", "503"} <= set(
            operation["responses"]
        )
        assert "Retry-After" in operation["responses"]["429"]["headers"]
        replay = client.post(f"{prefix}/conversations/{cid}/turns/stream", json=body)
        assert [e["type"] for e in events(replay)] == ["complete"]
        assert provider.calls == 1
        assert client.get(f"{prefix}/conversations/{cid}").json() == received[-1]["conversation"]
        conflict = client.post(
            f"{prefix}/conversations/{cid}/turns/stream", json={**body, "id": str(uuid4())}
        )
        assert_error(conflict, 409, "conversation_conflict")
        assert conflict.headers["content-type"] == "application/json"
    with database.session_factory() as session:
        assert len(list(session.scalars(select(KnowledgeConversationTurn)))) == 1


@pytest.mark.integration
def test_session_revocation_after_preview_errors_without_commit(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)

    def revoke() -> None:
        with database.session_factory.begin() as session:
            session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))

    provider = StreamingProvider(revoke)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        cid = create(client, prefix)
        response = client.post(
            f"{prefix}/conversations/{cid}/turns/stream",
            json={"id": str(uuid4()), "expectedRevision": 1, "question": "何时交付？"},
        )
        assert response.status_code == 200
        received = events(response)
        assert [e["type"] for e in received] == ["paragraph", "error"]
        assert received[-1]["status"] == 401
        assert received[-1]["code"] == "session_invalid"
        assert received[-1]["traceId"] == response.headers["x-request-id"]
    with database.session_factory() as session:
        assert not list(session.scalars(select(KnowledgeConversationTurn)))


@pytest.mark.integration
@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ("inactive", 401, "session_invalid"),
        ("permission", 404, "not_found"),
        ("evidence", 409, "knowledge_changed"),
        ("assistant", 409, "assistant_changed"),
    ],
)
def test_stream_revalidates_all_access_and_configuration_before_second_paragraph(
    database: Database, test_database_url: str, change: str, status: int, code: str
) -> None:
    from datetime import UTC, datetime

    from cairn_api.auth.models import User
    from cairn_api.authorization.models import ResourceAclEntry
    from cairn_api.knowledge.assistant_models import KnowledgeAssistantSettings
    from cairn_api.knowledge.models import KnowledgeResource

    actor, pid, rid = seed_conversation_boundary(database)

    def mutate() -> None:
        with database.session_factory.begin() as session:
            if change == "inactive":
                user = session.get(User, actor.user_id)
                assert user is not None
                user.is_active = False
            elif change == "permission":
                session.execute(delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == pid))
            elif change == "assistant":
                settings = session.scalar(
                    select(KnowledgeAssistantSettings).where(
                        KnowledgeAssistantSettings.owner_id == actor.user_id
                    )
                )
                assert settings is not None
                settings.revision += 1
            else:
                resource = session.get(KnowledgeResource, rid)
                assert resource is not None
                resource.deleted_at, resource.deleted_by = datetime.now(UTC), actor.user_id

    provider = StreamingProvider(mutate)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
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
            f"{prefix}/conversations/{cid}/turns/stream",
            json={
                "id": str(uuid4()),
                "expectedRevision": 1,
                "assistantRevision": 1,
                "question": "何时交付？",
            },
        )
        received = events(response)
        assert [e["type"] for e in received] == ["paragraph", "error"]
        assert (received[-1]["status"], received[-1]["code"]) == (status, code)
    with database.session_factory() as session:
        assert not list(session.scalars(select(KnowledgeConversationTurn)))


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        ("provider", 503, "answer_unavailable"),
        ("unexpected", 500, "internal_error"),
        ("quota", 429, "search_rate_limited"),
    ],
)
@pytest.mark.parametrize("after_preview", [False, True])
def test_stream_safe_failures_before_and_after_headers(
    database: Database,
    test_database_url: str,
    failure: str,
    status: int,
    code: str,
    after_preview: bool,
) -> None:
    from cairn_api.errors import ApiProblem
    from cairn_api.knowledge.answer_provider import AnswerProviderUnavailable

    actor, pid, _ = seed_conversation_boundary(database)

    def fail() -> None:
        if failure == "provider":
            raise AnswerProviderUnavailable("provider-secret")
        if failure == "quota":
            raise ApiProblem(
                status_code=429, code=code, message="提问过于频繁", headers={"Retry-After": "17"}
            )
        raise RuntimeError("provider-secret")

    class FailingProvider(StreamingProvider):
        def generate_stream(
            self,
            *,
            on_paragraph: Callable[[ProviderParagraph], None],
            check_cancelled: Callable[[], None],
            **kwargs: Any,
        ) -> ProviderAnswer:
            if not after_preview:
                fail()
            return super().generate_stream(
                on_paragraph=on_paragraph, check_cancelled=check_cancelled, **kwargs
            )

    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        FailingProvider(fail),
    ) as client:
        cid = create(client, prefix)
        response = client.post(
            f"{prefix}/conversations/{cid}/turns/stream",
            json={"id": str(uuid4()), "expectedRevision": 1, "question": "何时交付？"},
        )
        assert "provider-secret" not in response.text
        if after_preview:
            assert response.status_code == 200
            received = events(response)
            assert [e["type"] for e in received] == ["paragraph", "error"]
            assert (received[-1]["status"], received[-1]["code"], received[-1]["traceId"]) == (
                status,
                code,
                response.headers["x-request-id"],
            )
            if failure == "quota":
                assert received[-1]["retryAfter"] == "17"
        else:
            assert_error(response, status, code)
            if failure == "quota":
                assert response.headers["retry-after"] == "17"
    with database.session_factory() as session:
        assert not list(session.scalars(select(KnowledgeConversationTurn)))


@pytest.mark.integration
def test_stream_preheader_validation_csrf_scope_auth_and_admission(
    database: Database, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import BoundedSemaphore

    from cairn_api.knowledge import conversation_streaming

    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        StreamingProvider(),
    ) as client:
        cid = create(client, prefix)
        url = f"{prefix}/conversations/{cid}/turns/stream"
        body = {"id": str(uuid4()), "expectedRevision": 1, "question": "何时交付？"}
        assert_error(
            client.post(url, json={**body, "expectedRevision": True}), 422, "validation_error"
        )
        assert_error(
            client.post(url, json=body, headers={"X-CSRF-Token": "wrong"}), 403, "csrf_failed"
        )
        assert_error(
            client.post(f"{prefix}/conversations/{uuid4()}/turns/stream", json=body),
            404,
            "not_found",
        )
        capacity = BoundedSemaphore(1)
        assert capacity.acquire(blocking=False)
        monkeypatch.setattr(conversation_streaming, "STREAM_WORKERS", capacity)
        response = client.post(url, json=body)
        assert_error(response, 503, "answer_unavailable")
        assert response.headers["retry-after"] == "1"
        capacity.release()
        with database.session_factory.begin() as session:
            session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
        assert_error(client.post(url, json=body), 401, "session_invalid")
