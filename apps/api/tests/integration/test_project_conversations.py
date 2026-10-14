from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event, Lock
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession, User
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import (
    AnswerEvidence,
    AnswerHistoryTurn,
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
    ProviderAnswer,
    ProviderParagraph,
)
from cairn_api.knowledge.conversation_models import KnowledgeConversation, KnowledgeConversationTurn
from cairn_api.knowledge.conversation_service import KnowledgeConversationService
from cairn_api.knowledge.models import KnowledgeResource
from cairn_api.knowledge.schemas import KnowledgeSearchResponse, PdfLocator
from cairn_api.knowledge.search_service import KnowledgeSearchService
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from .authorization_helpers import SeededActor, seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_search import SearchEmbedding, seed_search_resource


class ConversationProvider:
    def __init__(self) -> None:
        self.histories: list[list[AnswerHistoryTurn]] = []

    def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
        return self.generate_with_history(question=question, evidence=evidence, history=[])

    def generate_with_history(
        self, *, question: str, evidence: list[AnswerEvidence], history: list[AnswerHistoryTurn]
    ) -> ProviderAnswer:
        self.histories.append(history)
        assert evidence
        return ProviderAnswer(
            status="answered",
            paragraphs=[ProviderParagraph(text="9 月 30 日交付。", citationIds=["S1"])],
        )


@pytest.mark.integration
def test_two_turns_persist_and_replay_without_provider_call(
    database: Database, test_database_url: str
) -> None:
    actor = seed_actor(database, MembershipRole.VIEWER)
    project_id = seed_project(database, actor, permission="read")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="交付说明",
        chunks=[(uuid4(), "9 月 30 日交付。", [1.0] + [0.0] * 1023)],
    )
    provider = ConversationProvider()
    cid, tid = uuid4(), uuid4()
    prefix = f"/api/v1/projects/{project_id}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        created = client.post(f"{prefix}/conversations", json={"id": str(cid)})
        assert created.status_code == 201
        assert created.json()["revision"] == 1
        create_replay = client.post(f"{prefix}/conversations", json={"id": str(cid)})
        assert create_replay.status_code == 200
        assert create_replay.json() == created.json()
        assert provider.histories == []
        first = client.post(
            f"{prefix}/conversations/{cid}/turns",
            json={"id": str(tid), "expectedRevision": 1, "question": "什么时候交付？"},
        )
        assert first.status_code == 200
        assert first.json()["revision"] == 2
        second = client.post(
            f"{prefix}/conversations/{cid}/turns",
            json={"id": str(uuid4()), "expectedRevision": 2, "question": "交付要准备什么？"},
        )
        assert second.status_code == 200
        assert second.json()["revision"] == 3
        replay = client.post(
            f"{prefix}/conversations/{cid}/turns",
            json={"id": str(tid), "expectedRevision": 1, "question": "什么时候交付？"},
        )
        assert replay.status_code == 200
        assert replay.json() == second.json()
        assert client.get(f"{prefix}/conversations/{cid}").json() == second.json()
        assert len(client.get(f"{prefix}/conversations").json()["items"]) == 1
        assert client.get(f"{prefix}/answer-model").json() == {
            "configured": True,
            "model": None,
            "protocol": None,
            "defaultModelId": "default",
            "models": [{"id": "default", "name": "已配置模型", "model": None, "protocol": None}],
        }
        assert second.headers["cache-control"] == "private, no-store"
        assert second.headers["x-request-id"]
    assert provider.histories == [
        [],
        [AnswerHistoryTurn(question="什么时候交付?", answer="9 月 30 日交付。")],
    ]
    with database.session_factory() as session:
        assert len(list(session.scalars(select(KnowledgeConversationTurn)))) == 2
        audits = list(
            session.scalars(select(AuditLog).where(AuditLog.action.like("knowledge.conversation%")))
        )
        assert len(audits) == 3
        assert {item.action for item in audits} == {
            "knowledge.conversation_created",
            "knowledge.conversation_turn_appended",
        }
        for item in audits:
            assert "什么时候" not in str(item.details)
            assert "9 月" not in str(item.details)
            assert "title" not in item.details


def seed_conversation_boundary(database: Database) -> tuple[SeededActor, UUID, UUID]:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, _ = seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="私有证据标题",
        chunks=[(uuid4(), "9 月 30 日交付。", [1.0] + [0.0] * 1023)],
    )
    return actor, project_id, resource_id


def create(client: TestClient, prefix: str) -> UUID:
    cid = uuid4()
    assert client.post(f"{prefix}/conversations", json={"id": str(cid)}).status_code == 201
    return cid


def append(
    client: TestClient,
    prefix: str,
    cid: UUID,
    *,
    revision: int = 1,
    tid: UUID | None = None,
    question: str = "什么时候交付？",
) -> Response:
    return client.post(
        f"{prefix}/conversations/{cid}/turns",
        json={"id": str(tid or uuid4()), "expectedRevision": revision, "question": question},
        headers={"X-Request-ID": "req-conversation-boundary"},
    )


def assert_error(response: Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert set(response.json()) == {"code", "message", "traceId"}
    assert response.json()["code"] == code
    assert response.json()["traceId"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["access-control-allow-origin"]
    assert "secret" not in response.text


@pytest.mark.integration
def test_validation_csrf_auth_protocol_and_conflict_contract(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    provider = ConversationProvider()
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
        for revision in (None, True, "1", 0):
            invalid = client.post(
                f"{prefix}/conversations/{cid}/turns",
                json={
                    "id": str(uuid4()),
                    "expectedRevision": revision,
                    "question": "什么时候交付？",
                },
            )
            assert_error(invalid, 422, "validation_error")
        assert_error(
            client.post(f"{prefix}/conversations", json={"id": str(uuid4()), "extra": True}),
            422,
            "validation_error",
        )
        assert_error(client.get(f"{prefix}/conversations?limit=51"), 422, "validation_error")
        assert_error(client.get(f"{prefix}/conversations?cursor=bad"), 422, "invalid_cursor")
        assert_error(
            client.post(
                f"{prefix}/conversations",
                json={"id": str(uuid4())},
                headers={"X-CSRF-Token": "wrong"},
            ),
            403,
            "csrf_failed",
        )
        tid = uuid4()
        assert append(client, prefix, cid, tid=tid).status_code == 200
        assert_error(
            append(client, prefix, cid, tid=tid, question="完全不同问题"),
            409,
            "conversation_conflict",
        )
        assert_error(append(client, prefix, cid), 409, "conversation_conflict")
        method = client.put(f"{prefix}/conversations/{cid}")
        assert method.status_code == 405
        assert method.headers["allow"] == "GET"
        assert method.json()["traceId"] == method.headers["x-request-id"]
        assert method.headers["cache-control"] == "private, no-store"
        with database.session_factory.begin() as session:
            session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
        assert_error(client.get(f"{prefix}/conversations/{cid}"), 401, "session_invalid")
    assert len(provider.histories) == 1


@pytest.mark.integration
@pytest.mark.parametrize("scope", ["user", "org", "project"])
def test_scope_is_private_even_for_admin(
    database: Database, test_database_url: str, scope: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        ConversationProvider(),
    ) as client:
        cid = create(client, prefix)
        tid = uuid4()
        assert append(client, prefix, cid, tid=tid).status_code == 200
    other = (
        actor
        if scope == "project"
        else seed_actor(
            database,
            MembershipRole.ADMIN,
            org_id=actor.organization_id if scope == "user" else None,
        )
    )
    target_pid = seed_project(database, other, permission="read") if scope == "project" else pid
    other_prefix = f"/api/v1/projects/{target_pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        other,
        MemoryObjectStore(),
        SearchEmbedding(),
        ConversationProvider(),
    ) as client:
        assert_error(client.get(f"{other_prefix}/conversations/{cid}"), 404, "not_found")
        assert_error(
            client.post(f"{other_prefix}/conversations", json={"id": str(cid)}), 404, "not_found"
        )
        assert_error(append(client, other_prefix, cid, tid=tid), 404, "not_found")
        if scope != "org":
            assert client.get(f"{other_prefix}/conversations").json()["items"] == []
            other_cid = create(client, other_prefix)
            assert_error(append(client, other_prefix, other_cid, tid=tid), 404, "not_found")


@pytest.mark.integration
@pytest.mark.parametrize("change", ["delete", "version", "source"])
def test_stale_history_redacts_all_answer_content_and_is_excluded_from_context(
    database: Database, test_database_url: str, change: str
) -> None:
    from cairn_api.knowledge.models import KnowledgeResourceVersion
    from cairn_api.knowledge.source_models import KnowledgeSource

    actor, pid, rid = seed_conversation_boundary(database)
    provider = ConversationProvider()
    prefix = f"/api/v1/projects/{pid}/knowledge"
    source_id = uuid4()
    if change == "source":
        with database.session_factory.begin() as session:
            resource = session.get(KnowledgeResource, rid)
            assert resource is not None
            version = session.get(KnowledgeResourceVersion, resource.current_version_id)
            assert version is not None
            session.add(
                KnowledgeSource(
                    id=source_id,
                    org_id=actor.organization_id,
                    project_id=pid,
                    name="合成来源",
                    provider="feishu",
                    external_id=resource.external_id,
                    credential_ref="test",
                    access_policy="project_members",
                    access_state="available",
                )
            )
            for row in (resource, version):
                row.source_type = "feishu"
                row.source_id = str(source_id)
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        cid = create(client, prefix)
        assert append(client, prefix, cid).status_code == 200
        with database.session_factory.begin() as session:
            resource = session.get(KnowledgeResource, rid)
            assert resource is not None
            if change == "delete":
                resource.deleted_at, resource.deleted_by = datetime.now(UTC), actor.user_id
            elif change == "version":
                resource.current_version_id = None
            else:
                source = session.get(KnowledgeSource, source_id)
                assert source is not None
                source.access_state = "access_denied"
        redacted = client.get(f"{prefix}/conversations/{cid}")
        assert redacted.status_code == 200
        turn = redacted.json()["turns"][0]
        assert turn["answer"] is None and turn["answerUnavailable"] is True
        assert turn["question"] == "什么时候交付?"
        assert "私有证据标题" not in redacted.text
        assert "9 月 30 日" not in redacted.text
        seed_search_resource(
            database,
            org_id=actor.organization_id,
            project_id=pid,
            title="新证据",
            chunks=[(uuid4(), "9 月 30 日交付。", [1.0] + [0.0] * 1023)],
        )
        second = append(client, prefix, cid, revision=2)
        assert second.status_code == 200
        assert second.json()["turns"][1]["contextTruncated"] is True
        assert provider.histories == [[], []]


class MutatingProvider(ConversationProvider):
    def __init__(self, change: Callable[[], None]) -> None:
        super().__init__()
        self.change = change

    def generate_with_history(
        self, *, question: str, evidence: list[AnswerEvidence], history: list[AnswerHistoryTurn]
    ) -> ProviderAnswer:
        self.change()
        return super().generate_with_history(question=question, evidence=evidence, history=history)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ("logout", 401, "session_invalid"),
        ("inactive", 401, "session_invalid"),
        ("revoke", 409, "knowledge_changed"),
        ("evidence", 409, "knowledge_changed"),
    ],
)
def test_generation_finalization_rechecks_session_permission_and_evidence(
    database: Database, test_database_url: str, change: str, status: int, code: str
) -> None:
    actor, pid, rid = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"

    def mutate() -> None:
        # This second DB connection would block if provider I/O held the relevant locks.
        with database.session_factory.begin() as session:
            if change == "logout":
                session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
            elif change == "inactive":
                user = session.get(User, actor.user_id)
                assert user is not None
                user.is_active = False
            elif change == "revoke":
                session.execute(delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == pid))
            else:
                resource = session.get(KnowledgeResource, rid)
                assert resource is not None
                resource.deleted_at, resource.deleted_by = datetime.now(UTC), actor.user_id

    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        MutatingProvider(mutate),
    ) as client:
        cid = create(client, prefix)
        assert_error(append(client, prefix, cid), status, code)
    with database.session_factory() as session:
        row = session.get(KnowledgeConversation, cid)
        assert row is not None and row.revision == 1
        assert list(session.scalars(select(KnowledgeConversationTurn))) == []
        assert (
            list(
                session.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "knowledge.conversation_turn_appended"
                    )
                )
            )
            == []
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AnswerProviderUnavailable("provider-secret"), 503, "answer_unavailable"),
        (AnswerProviderInvalidResponse("provider-secret"), 503, "answer_unavailable"),
        (RuntimeError("provider-secret"), 500, "internal_error"),
    ],
)
def test_generation_failures_are_safe_and_save_nothing(
    database: Database, test_database_url: str, error: Exception, status: int, code: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"

    def fail() -> None:
        raise error

    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        MutatingProvider(fail),
    ) as client:
        cid = create(client, prefix)
        assert_error(append(client, prefix, cid), status, code)
        assert client.get(f"{prefix}/conversations/{cid}").json()["turns"] == []


@pytest.mark.integration
def test_atomic_audit_failure_rolls_back_complete_turn(
    database: Database, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        ConversationProvider(),
    ) as client:
        cid = create(client, prefix)
        monkeypatch.setattr(
            KnowledgeConversationService,
            "_business_audit",
            Mock(side_effect=OperationalError("database-secret", {}, Exception("driver-secret"))),
        )
        assert_error(append(client, prefix, cid), 503, "database_unavailable")
        detail = client.get(f"{prefix}/conversations/{cid}").json()
        assert detail["revision"] == 1 and detail["turns"] == [] and detail["title"] == "新对话"
    with database.session_factory() as session:
        assert list(session.scalars(select(KnowledgeConversationTurn))) == []


@pytest.mark.integration
def test_unconfigured_model_and_rate_limit_preserve_readable_history(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    settings = knowledge_settings(test_database_url, search_user_limit_per_minute=1)
    with knowledge_client(
        settings, database, actor, MemoryObjectStore(), SearchEmbedding(), ConversationProvider()
    ) as client:
        cid = create(client, prefix)
        assert append(client, prefix, cid).status_code == 200
        limited = append(client, prefix, cid, revision=2)
        assert_error(limited, 429, "search_rate_limited")
        assert int(limited.headers["retry-after"]) >= 1
    with knowledge_client(
        settings, database, actor, MemoryObjectStore(), SearchEmbedding()
    ) as client:
        assert client.get(f"{prefix}/answer-model").json() == {
            "configured": False,
            "model": None,
            "protocol": None,
            "defaultModelId": None,
            "models": [],
        }
        assert len(client.get(f"{prefix}/conversations/{cid}").json()["turns"]) == 1


@pytest.mark.integration
def test_no_model_is_safe_503_and_legacy_provider_cannot_silently_drop_history(
    database: Database, test_database_url: str
) -> None:
    from .test_knowledge_answers import AnswerStub

    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        cid = create(client, prefix)
        assert_error(append(client, prefix, cid), 503, "answer_unavailable")
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        AnswerStub(),
    ) as client:
        assert append(client, prefix, cid).status_code == 200
        assert_error(append(client, prefix, cid, revision=2), 503, "answer_unavailable")
        assert len(client.get(f"{prefix}/conversations/{cid}").json()["turns"]) == 1


@pytest.mark.integration
def test_full_conversation_replays_but_rejects_new_turn(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    provider = ConversationProvider()
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        cid = create(client, prefix)
        with database.session_factory.begin() as session:
            conversation = session.get(KnowledgeConversation, cid)
            assert conversation is not None
            conversation.revision = 51
            for sequence in range(1, 51):
                session.add(
                    KnowledgeConversationTurn(
                        id=uuid4(),
                        org_id=actor.organization_id,
                        project_id=pid,
                        conversation_id=cid,
                        sequence=sequence,
                        question="无充分证据的问题",
                        answer={
                            "status": "insufficient_evidence",
                            "retrieval_mode": "hybrid",
                            "paragraphs": [],
                            "citations": [],
                        },
                        context_truncated=False,
                    )
                )
        detail = client.get(f"{prefix}/conversations/{cid}").json()
        assert len(detail["turns"]) == 50
        assert_error(append(client, prefix, cid, revision=51), 409, "conversation_conflict")
        assert (
            append(
                client, prefix, cid, tid=UUID(detail["turns"][0]["id"]), question="无充分证据的问题"
            ).json()
            == detail
        )
    assert provider.histories == []


@pytest.mark.integration
def test_history_is_rechecked_after_provider_even_when_current_evidence_is_different(
    database: Database, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn_api.knowledge.schemas import KnowledgeCitation, KnowledgeSearchResponse
    from cairn_api.knowledge.search_service import KnowledgeSearchService

    actor, pid, historical_rid = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        ConversationProvider(),
    ) as client:
        cid = create(client, prefix)
        assert append(client, prefix, cid).status_code == 200
    new_chunk = uuid4()
    new_rid, new_vid = seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=pid,
        title="本轮合成证据",
        chunks=[(new_chunk, "9 月 30 日交付。", [1.0] + [0.0] * 1023)],
    )
    citation = KnowledgeCitation(
        resource_id=new_rid,
        resource_version_id=new_vid,
        chunk_id=new_chunk,
        title="本轮合成证据",
        media_type="application/pdf",
        excerpt="9 月 30 日交付。",
        locator=PdfLocator(type="pdf", page=1),
        score=0.5,
    )
    monkeypatch.setattr(
        KnowledgeSearchService,
        "search",
        Mock(return_value=KnowledgeSearchResponse(retrieval_mode="hybrid", results=[citation])),
    )

    def delete_history() -> None:
        with database.session_factory.begin() as session:
            resource = session.get(KnowledgeResource, historical_rid)
            assert resource is not None
            resource.deleted_at, resource.deleted_by = datetime.now(UTC), actor.user_id

    provider = MutatingProvider(delete_history)
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        assert_error(append(client, prefix, cid, revision=2), 409, "knowledge_changed")
        detail = client.get(f"{prefix}/conversations/{cid}").json()
        assert detail["revision"] == 2 and len(detail["turns"]) == 1
        assert detail["turns"][0]["answerUnavailable"] is True
    assert len(provider.histories[0]) == 1


@pytest.mark.integration
def test_pagination_is_stable_by_creation_and_safe_database_read_failures(
    database: Database, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        ConversationProvider(),
    ) as client:
        ids = [create(client, prefix) for _ in range(3)]
        assert append(client, prefix, ids[0]).status_code == 200
        page = client.get(f"{prefix}/conversations?limit=2").json()
        assert [item["id"] for item in page["items"]] == [str(ids[2]), str(ids[1])]
        assert "turns" not in page["items"][0]
        following = client.get(
            f"{prefix}/conversations", params={"limit": 2, "cursor": page["nextCursor"]}
        ).json()
        assert [item["id"] for item in following["items"]] == [str(ids[0])]
        assert following["nextCursor"] is None
        monkeypatch.setattr(
            KnowledgeConversationService,
            "_authorize",
            Mock(side_effect=OperationalError("database-secret", {}, Exception("driver-secret"))),
        )
        for suffix in ("/answer-model", "/conversations", f"/conversations/{ids[0]}"):
            assert_error(client.get(prefix + suffix), 503, "database_unavailable")


@pytest.mark.integration
def test_configured_model_status_does_not_probe_provider_and_openapi_is_exact(
    database: Database, test_database_url: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    provider = ConversationProvider()
    settings = knowledge_settings(
        test_database_url, answer_model="gpt-synthetic", answer_protocol="openai-responses"
    )
    with knowledge_client(
        settings, database, actor, MemoryObjectStore(), SearchEmbedding(), provider
    ) as client:
        assert client.get(f"{prefix}/answer-model").json() == {
            "configured": True,
            "model": "gpt-synthetic",
            "protocol": "openai-responses",
            "defaultModelId": "default",
            "models": [{"id": "default", "name": "gpt-synthetic", "model": "gpt-synthetic", "protocol": "openai-responses"}],
        }
        assert provider.histories == []
        openapi = client.get("/openapi.json").json()
    create_operation = openapi["paths"]["/api/v1/projects/{project_id}/knowledge/conversations"][
        "post"
    ]
    for status in ("200", "201"):
        assert create_operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/KnowledgeConversationResponse"
        }
    turn_operation = openapi["paths"][
        "/api/v1/projects/{project_id}/knowledge/conversations/{conversation_id}/turns"
    ]["post"]
    assert {"200", "401", "403", "404", "409", "422", "429", "500", "503"} <= set(
        turn_operation["responses"]
    )
    assert "Retry-After" in turn_operation["responses"]["429"]["headers"]
    assert "X-Request-ID" in turn_operation["responses"]["200"]["headers"]
    assert "Cache-Control" in turn_operation["responses"]["200"]["headers"]
    assert turn_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "KnowledgeConversationTurnRequest"
    )
    schema = openapi["components"]["schemas"]["KnowledgeConversationTurnRequest"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"id", "question", "expectedRevision"}
    assert schema["properties"]["expectedRevision"]["type"] == "integer"


@pytest.mark.integration
@pytest.mark.parametrize("same_id", [False, True])
def test_concurrent_append_has_one_atomic_winner_and_idempotent_replay(
    database: Database, test_database_url: str, same_id: bool
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    barrier = Barrier(2)

    def synchronize() -> None:
        barrier.wait(timeout=15)

    provider = MutatingProvider(synchronize)
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        cid = create(client, prefix)
        first_id = uuid4()
        ids = [first_id, first_id if same_id else uuid4()]

        def send(tid: UUID) -> Response:
            return append(client, prefix, cid, tid=tid)

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(send, ids))
        assert sorted(response.status_code for response in responses) == (
            [200, 200] if same_id else [200, 409]
        )
        if not same_id:
            assert_error(
                next(response for response in responses if response.status_code == 409),
                409,
                "conversation_conflict",
            )
        detail = client.get(f"{prefix}/conversations/{cid}").json()
        assert detail["revision"] == 2 and len(detail["turns"]) == 1
        assert append(client, prefix, cid, tid=UUID(detail["turns"][0]["id"])).status_code == 200
        assert len(provider.histories) == 2
    with database.session_factory() as session:
        assert len(list(session.scalars(select(KnowledgeConversationTurn)))) == 1
        assert (
            len(
                list(
                    session.scalars(
                        select(AuditLog).where(
                            AuditLog.action == "knowledge.conversation_turn_appended"
                        )
                    )
                )
            )
            == 1
        )


@pytest.mark.integration
def test_concurrent_global_turn_id_collision_is_concealed(
    database: Database, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    actors = [seed_conversation_boundary(database), seed_conversation_boundary(database)]
    provider = ConversationProvider()
    barrier = Barrier(2)
    original = KnowledgeConversationService._replay  # pyright: ignore[reportPrivateUsage]
    calls: dict[int, int] = {}

    def synchronized_replay(
        self: KnowledgeConversationService,
        row: KnowledgeConversation,
        turn_id: UUID,
        question: str,
        assistant_revision: int = 0,
        skill_id: str | None = None,
    ) -> bool:
        result = original(self, row, turn_id, question, assistant_revision, skill_id)
        calls[id(self)] = calls.get(id(self), 0) + 1
        if calls[id(self)] == 2:
            barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(KnowledgeConversationService, "_replay", synchronized_replay)
    actor1, pid1, _ = actors[0]
    actor2, pid2, _ = actors[1]
    prefix1 = f"/api/v1/projects/{pid1}/knowledge"
    prefix2 = f"/api/v1/projects/{pid2}/knowledge"
    with (
        knowledge_client(
            knowledge_settings(test_database_url),
            database,
            actor1,
            MemoryObjectStore(),
            SearchEmbedding(),
            provider,
        ) as first,
        knowledge_client(
            knowledge_settings(test_database_url),
            database,
            actor2,
            MemoryObjectStore(),
            SearchEmbedding(),
            provider,
        ) as second,
    ):
        cid1, cid2, tid = create(first, prefix1), create(second, prefix2), uuid4()
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(append, first, prefix1, cid1, tid=tid)
            two = pool.submit(append, second, prefix2, cid2, tid=tid)
            responses = [one.result(), two.result()]
        assert sorted(response.status_code for response in responses) == [200, 404]
        assert_error(
            next(response for response in responses if response.status_code == 404),
            404,
            "not_found",
        )
    with database.session_factory() as session:
        assert len(list(session.scalars(select(KnowledgeConversationTurn)))) == 1
        assert sorted(row.revision for row in session.scalars(select(KnowledgeConversation))) == [
            1,
            2,
        ]


@pytest.mark.integration
@pytest.mark.parametrize("retry_kind", ["identical", "distinct_id", "different_question"])
def test_turn_committed_during_retrieval_replays_only_identical_request(
    database: Database, test_database_url: str, monkeypatch: pytest.MonkeyPatch, retry_kind: str
) -> None:
    actor, pid, _ = seed_conversation_boundary(database)
    prefix = f"/api/v1/projects/{pid}/knowledge"
    provider = ConversationProvider()
    delayed_started, release_delayed = Event(), Event()
    counter_lock = Lock()
    calls = 0
    original = KnowledgeSearchService.search

    def delayed_search(
        self: KnowledgeSearchService,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        query: str,
        limit: int,
        audit: RequestAuditContext,
    ) -> KnowledgeSearchResponse:
        nonlocal calls
        with counter_lock:
            calls += 1
            delayed = calls == 1
        if delayed:
            delayed_started.set()
            assert release_delayed.wait(timeout=15)
        return original(
            self, identity=identity, project_id=project_id, query=query, limit=limit, audit=audit
        )

    monkeypatch.setattr(KnowledgeSearchService, "search", delayed_search)
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        provider,
    ) as client:
        cid, winner_id = create(client, prefix), uuid4()
        delayed_id = uuid4() if retry_kind == "distinct_id" else winner_id
        delayed_question = (
            "交付需要准备什么？" if retry_kind == "different_question" else "什么时候交付？"
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            delayed = pool.submit(
                append, client, prefix, cid, tid=delayed_id, question=delayed_question
            )
            assert delayed_started.wait(timeout=15)
            try:
                winner = pool.submit(append, client, prefix, cid, tid=winner_id).result(timeout=15)
            finally:
                release_delayed.set()
            retry = delayed.result(timeout=15)
        detail = client.get(f"{prefix}/conversations/{cid}").json()
        assert winner.status_code == 200
        assert len(provider.histories) == 1
        assert len(detail["turns"]) == 1 and detail["revision"] == 2
        if retry_kind == "identical":
            assert retry.status_code == 200
            assert retry.json() == detail
            assert retry.headers["cache-control"] == "private, no-store"
        else:
            assert_error(retry, 409, "conversation_conflict")
    with database.session_factory() as session:
        assert len(list(session.scalars(select(KnowledgeConversationTurn)))) == 1
        assert (
            len(
                list(
                    session.scalars(
                        select(AuditLog).where(
                            AuditLog.action == "knowledge.conversation_turn_appended"
                        )
                    )
                )
            )
            == 1
        )


@pytest.mark.integration
def test_markdown_two_turn_snapshot_read_and_replay_with_responses_adapter(
    database: Database, test_database_url: str
) -> None:
    import json

    import httpx
    from cairn_api.knowledge.answer_provider import OpenAIAnswerProvider
    from cairn_api.knowledge.models import KnowledgeChunk, KnowledgeResourceVersion

    actor, pid, rid = seed_conversation_boundary(database)
    locator: dict[str, object] = {
        "type": "markdown",
        "headingPath": ["项目", "交付"],
        "lineStart": 2,
        "lineEnd": 5,
    }
    with database.session_factory.begin() as session:
        resource = session.get(KnowledgeResource, rid)
        assert resource is not None
        version = session.get(KnowledgeResourceVersion, resource.current_version_id)
        chunk = session.scalar(select(KnowledgeChunk).where(KnowledgeChunk.resource_id == rid))
        assert version is not None and chunk is not None
        version.media_type = "text/markdown"
        chunk.locator = locator
    histories: list[object] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user = json.loads(payload["input"])
        assert user["evidence"][0]["locator"] == locator
        histories.append(user["history"])
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
                                            {"text": "9 月 30 日交付。", "citationIds": ["S1"]}
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
        api_key="synthetic-key",
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
        cid, tid = create(client, prefix), uuid4()
        first = append(client, prefix, cid, tid=tid)
        assert first.status_code == 200
        assert first.json()["turns"][0]["answer"]["citations"][0]["locator"] == locator
        second = append(client, prefix, cid, revision=2)
        assert second.status_code == 200
        assert client.get(f"{prefix}/conversations/{cid}").json() == second.json()
        assert append(client, prefix, cid, tid=tid).json() == second.json()
        assert all(
            turn["answer"]["citations"][0]["locator"] == locator for turn in second.json()["turns"]
        )
    assert len(histories) == 2 and histories[0] == []
    assert histories[1] == [{"question": "什么时候交付?", "answer": "9 月 30 日交付。"}]
