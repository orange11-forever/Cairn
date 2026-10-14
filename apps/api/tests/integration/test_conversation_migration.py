from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.conversation_models import KnowledgeConversation, KnowledgeConversationTurn
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from .authorization_helpers import seed_actor
from .knowledge_helpers import seed_project

pytestmark = pytest.mark.integration


def test_migration_empty_downgrade_and_populated_retention(
    database: Database, migrated_engine: Engine, test_database_url: str
) -> None:
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    try:
        command.downgrade(config, "0015_structure_lifecycle")
        assert "knowledge_conversations" not in inspect(migrated_engine).get_table_names()
        command.upgrade(config, "head")
        actor = seed_actor(database, MembershipRole.MEMBER)
        pid = seed_project(database, actor, permission="read")
        cid = uuid4()
        with database.session_factory.begin() as session:
            session.add(
                KnowledgeConversation(
                    id=cid, org_id=actor.organization_id, project_id=pid, owner_id=actor.user_id
                )
            )
        with pytest.raises(RuntimeError, match="populated project conversations"):
            command.downgrade(config, "0015_structure_lifecycle")
        with migrated_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0016_project_conversations"
            )
            assert (
                connection.scalar(
                    text("SELECT title FROM knowledge_conversations WHERE id=:id"), {"id": cid}
                )
                == "新对话"
            )
    finally:
        command.upgrade(config, "head")


def test_database_constraints_enforce_scope_and_turn_uniqueness(database: Database) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    other = seed_actor(database, MembershipRole.MEMBER)
    pid = seed_project(database, actor, permission="read")
    other_pid = seed_project(database, actor, permission="read")
    cid, tid = uuid4(), uuid4()
    with database.session_factory.begin() as session:
        session.add(
            KnowledgeConversation(
                id=cid, org_id=actor.organization_id, project_id=pid, owner_id=actor.user_id
            )
        )
        session.flush()
        session.add(
            KnowledgeConversationTurn(
                id=tid,
                org_id=actor.organization_id,
                project_id=pid,
                conversation_id=cid,
                sequence=1,
                question="测试完整轮次",
                answer={
                    "status": "insufficient_evidence",
                    "retrieval_mode": "hybrid",
                    "paragraphs": [],
                    "citations": [],
                },
                context_truncated=False,
            )
        )
    with pytest.raises(IntegrityError), database.session_factory.begin() as session:
        session.add(
            KnowledgeConversation(
                id=uuid4(), org_id=other.organization_id, project_id=pid, owner_id=other.user_id
            )
        )
    with pytest.raises(IntegrityError), database.session_factory.begin() as session:
        session.add(
            KnowledgeConversation(
                id=uuid4(), org_id=actor.organization_id, project_id=pid, owner_id=other.user_id
            )
        )
    for sequence, project_id, turn_id in [
        (1, pid, uuid4()),
        (2, other_pid, uuid4()),
        (51, pid, uuid4()),
        (2, pid, tid),
    ]:
        with pytest.raises(IntegrityError), database.session_factory.begin() as session:
            session.add(
                KnowledgeConversationTurn(
                    id=turn_id,
                    org_id=actor.organization_id,
                    project_id=project_id,
                    conversation_id=cid,
                    sequence=sequence,
                    question="测试完整轮次",
                    answer={},
                    context_truncated=False,
                )
            )
