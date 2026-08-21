from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cairn_api.auth.models import AuthSession
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.models import KnowledgeResource
from cairn_api.organizations.models import Membership
from sqlalchemy import delete, select

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_search import SearchEmbedding, seed_search_resource


@pytest.mark.integration
@pytest.mark.parametrize("role", [MembershipRole.MEMBER, MembershipRole.VIEWER])
def test_search_enforces_read_acl_for_member_and_viewer(
    database: Database,
    test_database_url: str,
    role: MembershipRole,
) -> None:
    actor = seed_actor(database, role)
    allowed_project = seed_project(database, actor, permission="read")
    denied_project = seed_project(database, actor, permission=None)
    chunk_id = uuid4()
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=allowed_project,
        title="Allowed.pdf",
        chunks=[(chunk_id, "authorized knowledge", [1.0] + [0.0] * 1023)],
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        allowed = client.post(
            f"/api/v1/projects/{allowed_project}/knowledge/search",
            json={"query": "authorized knowledge"},
        )
        denied = client.post(
            f"/api/v1/projects/{denied_project}/knowledge/search",
            json={"query": "authorized knowledge"},
        )
        with database.session_factory.begin() as session:
            session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
        unauthenticated = client.post(
            f"/api/v1/projects/{allowed_project}/knowledge/search",
            json={"query": "authorized knowledge"},
        )

    assert allowed.status_code == 200
    assert allowed.json()["results"][0]["chunkId"] == str(chunk_id)
    assert denied.status_code == 404
    assert denied.json()["code"] == "not_found"
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["code"] == "session_invalid"


@pytest.mark.integration
def test_search_excludes_other_tenants_projects_noncurrent_processing_and_deleted_resources(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    other_actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    other_project = seed_project(database, actor, permission="read")
    other_org_project = seed_project(database, other_actor, permission="read")
    visible_id = UUID("00000000-0000-4000-8000-000000000021")
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="Visible.pdf",
        chunks=[(visible_id, "isolation sentinel", [1.0] + [0.0] * 1023)],
    )
    fixtures = [
        (actor.organization_id, other_project, True, True, False),
        (other_actor.organization_id, other_org_project, True, True, False),
        (actor.organization_id, project_id, False, True, False),
        (actor.organization_id, project_id, True, False, False),
        (actor.organization_id, project_id, True, True, True),
    ]
    for org_id, scoped_project, current, ready, deleted in fixtures:
        seed_search_resource(
            database,
            org_id=org_id,
            project_id=scoped_project,
            title=f"Hidden-{uuid4()}.pdf",
            chunks=[(uuid4(), "isolation sentinel", [1.0] + [0.0] * 1023)],
            current=current,
            ready=ready,
            deleted=deleted,
            deleted_by=actor.user_id if deleted else None,
        )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "isolation sentinel", "limit": 20},
        )

    assert response.status_code == 200
    assert [item["chunkId"] for item in response.json()["results"]] == [str(visible_id)]


class RevokeAclOnEmbedding(SearchEmbedding):
    def __init__(self, database: Database, acl_id: UUID) -> None:
        super().__init__()
        self.database = database
        self.acl_id = acl_id

    def embed_query(self, query: str) -> list[float]:
        with self.database.session_factory.begin() as session:
            acl = session.get(ResourceAclEntry, self.acl_id)
            assert acl is not None
            acl.revoked_at = datetime.now(UTC)
        return super().embed_query(query)


class ChangeMembershipOnEmbedding(SearchEmbedding):
    def __init__(self, database: Database, membership_id: UUID, *, remove: bool) -> None:
        super().__init__()
        self.database = database
        self.membership_id = membership_id
        self.remove = remove

    def embed_query(self, query: str) -> list[float]:
        with self.database.session_factory.begin() as session:
            membership = session.get(Membership, self.membership_id)
            assert membership is not None
            if self.remove:
                session.delete(membership)
            else:
                membership.role = MembershipRole.MEMBER.value
        return super().embed_query(query)


@pytest.mark.integration
@pytest.mark.parametrize("remove", [False, True])
def test_search_rechecks_live_membership_after_provider_io(
    database: Database,
    test_database_url: str,
    remove: bool,
) -> None:
    actor = seed_actor(database, MembershipRole.ADMIN)
    project_id = seed_project(database, actor, permission=None)
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="Membership.pdf",
        chunks=[(uuid4(), "membership sentinel", [1.0] + [0.0] * 1023)],
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        ChangeMembershipOnEmbedding(database, actor.membership_id, remove=remove),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "membership sentinel"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


class DeleteResourceOnEmbedding(SearchEmbedding):
    def __init__(self, database: Database, resource_id: UUID, actor_id: UUID) -> None:
        super().__init__()
        self.database = database
        self.resource_id = resource_id
        self.actor_id = actor_id

    def embed_query(self, query: str) -> list[float]:
        with self.database.session_factory.begin() as session:
            resource = session.get(KnowledgeResource, self.resource_id)
            assert resource is not None
            resource.deleted_at = datetime.now(UTC)
            resource.deleted_by = self.actor_id
        return super().embed_query(query)


@pytest.mark.integration
def test_resource_deleted_during_provider_io_is_concealed_from_final_retrieval(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, _version_id = seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="Deleted.pdf",
        chunks=[(uuid4(), "deleted sentinel", [1.0] + [0.0] * 1023)],
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        DeleteResourceOnEmbedding(database, resource_id, actor.user_id),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "deleted sentinel"},
        )

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.integration
def test_acl_revoked_after_initial_check_is_reapplied_inside_both_candidate_queries(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    with database.session_factory() as session:
        acl = session.scalar(
            select(ResourceAclEntry).where(
                ResourceAclEntry.resource_id == project_id,
                ResourceAclEntry.principal_id == str(actor.user_id),
            )
        )
        assert acl is not None
        acl_id = acl.id
    seed_search_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        title="Revoked.pdf",
        chunks=[(uuid4(), "revocation sentinel", [1.0] + [0.0] * 1023)],
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        RevokeAclOnEmbedding(database, acl_id),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "revocation sentinel"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
