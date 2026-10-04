from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.knowledge.answer_provider import AnswerEvidence, ProviderAnswer, ProviderParagraph
from cairn_api.knowledge.models import (
    ChunkEmbedding,
    EmbeddingProfile,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobStatus,
    JobKind,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
)
from cairn_api.knowledge.source_models import KnowledgeSource
from sqlalchemy import select

from .authorization_helpers import seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_search import SearchEmbedding


def _seed_feishu_resource(
    database: Database,
    *,
    org_id: UUID,
    project_id: UUID,
    source: KnowledgeSource,
    title: str,
    failed: bool = False,
) -> tuple[UUID, UUID, UUID]:
    resource_id, version_id, chunk_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    with database.session_factory.begin() as session:
        profile = session.scalar(
            select(EmbeddingProfile).where(
                EmbeddingProfile.org_id.is_(None), EmbeddingProfile.status == "active"
            )
        )
        if profile is None:
            profile = EmbeddingProfile(
                id=uuid4(),
                org_id=None,
                provider_key="default",
                model="text-embedding-v4",
                dimensions=1024,
                distance_metric="cosine",
                chunking_config={"maxCodepoints": 1800, "overlapCodepoints": 180},
                index_config={"strategy": "exact", "candidateLimit": 50},
                version="default-v1",
                status="active",
            )
            session.add(profile)
            session.flush()
        resource = KnowledgeResource(
            id=resource_id,
            org_id=org_id,
            project_id=project_id,
            title=title,
            source_type="feishu",
            source_id=str(source.id),
            external_id=source.external_id,
        )
        session.add(resource)
        session.flush()
        version = KnowledgeResourceVersion(
            id=version_id,
            org_id=org_id,
            project_id=project_id,
            resource_id=resource_id,
            source_type="feishu",
            source_id=str(source.id),
            external_id=source.external_id,
            source_version=uuid4().hex,
            object_key=f"orgs/{org_id}/feishu/{version_id}",
            media_type="text/plain",
            size_bytes=20,
            sha256="a" * 64,
            parser_profile="default-v1",
            chunking_profile="default-v1",
            status=ResourceVersionStatus.FAILED if failed else ResourceVersionStatus.READY,
            error_code="embedding_unavailable" if failed else None,
            created_at=now,
            processing_started_at=now,
            ready_at=None if failed else now,
        )
        session.add(version)
        session.flush()
        if not failed:
            resource.current_version_id = version_id
            chunk = KnowledgeChunk(
                id=chunk_id,
                org_id=org_id,
                project_id=project_id,
                resource_id=resource_id,
                resource_version_id=version_id,
                ordinal=0,
                kind="text",
                text="source revocation sentinel",
                normalized_text="source revocation sentinel",
                locator={"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 1},
            )
            session.add(chunk)
            session.flush()
            session.add(
                ChunkEmbedding(
                    org_id=org_id,
                    project_id=project_id,
                    resource_id=resource_id,
                    resource_version_id=version_id,
                    chunk_id=chunk_id,
                    embedding_profile_scope_org_id=profile.scope_org_id,
                    embedding_profile_id=profile.id,
                    embedding=[1.0] + [0.0] * 1023,
                )
            )
        session.add(
            IngestionJob(
                org_id=org_id,
                project_id=project_id,
                job_kind=JobKind.INDEX_RESOURCE_VERSION,
                target_id=version_id,
                profile_version="default-v1",
                status=IngestionJobStatus.FAILED if failed else IngestionJobStatus.COMPLETED,
                attempt=1,
                max_attempts=5,
                next_attempt_at=now,
                last_error_code="embedding_unavailable" if failed else None,
                completed_at=now,
            )
        )
    return resource_id, version_id, chunk_id


def _source(database: Database, org_id: UUID, project_id: UUID) -> KnowledgeSource:
    source = KnowledgeSource(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        name="Shared handbook",
        external_id=f"doc-{uuid4().hex}",
        credential_ref=f"credential_{uuid4().hex}",
        access_policy="project_members",
        access_state="available",
    )
    with database.session_factory.begin() as session:
        session.add(source)
    return source


@pytest.mark.integration
@pytest.mark.parametrize("revocation", ["disabled", "access_denied", "not_found", "unverified"])
def test_feishu_state_revokes_every_content_boundary(
    database: Database,
    test_database_url: str,
    revocation: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source = _source(database, actor.organization_id, project_id)
    ready_id, _ready_version, chunk_id = _seed_feishu_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        source=source,
        title="ready source",
    )
    failed_source = _source(database, actor.organization_id, project_id)
    failed_id, failed_version, _ = _seed_feishu_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        source=failed_source,
        title="failed source",
        failed=True,
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
    ) as client:
        assert client.get(f"/api/v1/projects/{project_id}/knowledge/resources").status_code == 200
        assert client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{ready_id}"
        ).status_code == 200
        assert client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{ready_id}/download",
            follow_redirects=False,
        ).status_code == 307
        assert client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{ready_id}/chunks/{chunk_id}"
        ).status_code == 200
        assert client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "source revocation sentinel"},
        ).json()["results"]

        with database.session_factory.begin() as session:
            for source_id in (source.id, failed_source.id):
                stored = session.get(KnowledgeSource, source_id)
                assert stored is not None
                if revocation == "disabled":
                    stored.status = "disabled"
                    stored.disabled_at = datetime.now(UTC)
                else:
                    stored.access_state = revocation

        listing = client.get(f"/api/v1/projects/{project_id}/knowledge/resources")
        detail = client.get(f"/api/v1/projects/{project_id}/knowledge/resources/{ready_id}")
        download = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{ready_id}/download",
            follow_redirects=False,
        )
        context = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{ready_id}/chunks/{chunk_id}"
        )
        search = client.post(
            f"/api/v1/projects/{project_id}/knowledge/search",
            json={"query": "source revocation sentinel"},
        )
        retry = client.post(
            f"/api/v1/projects/{project_id}/knowledge/resources/{failed_id}/versions/"
            f"{failed_version}/retry"
        )
        delete = client.delete(
            f"/api/v1/projects/{project_id}/knowledge/resources/{ready_id}"
        )

    assert listing.status_code == 200 and listing.json()["items"] == []
    assert search.status_code == 200 and search.json()["results"] == []
    assert all(response.status_code == 404 for response in (detail, download, context, retry, delete))


@pytest.mark.integration
@pytest.mark.parametrize(
    ("resource_change", "version_change"),
    [
        ({"source_id": "not-a-source"}, {}),
        ({}, {"source_type": "upload"}),
        ({}, {"external_id": "another-document"}),
    ],
)
def test_source_identity_and_mixed_provenance_fail_closed(
    database: Database,
    test_database_url: str,
    resource_change: dict[str, str],
    version_change: dict[str, str],
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source = _source(database, actor.organization_id, project_id)
    resource_id, version_id, _ = _seed_feishu_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        source=source,
        title="mixed provenance",
    )
    with database.session_factory.begin() as session:
        resource = session.get(KnowledgeResource, resource_id)
        version = session.get(KnowledgeResourceVersion, version_id)
        assert resource is not None and version is not None
        for name, value in resource_change.items():
            setattr(resource, name, value)
        for name, value in version_change.items():
            setattr(version, name, value)

    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        listing = client.get(f"/api/v1/projects/{project_id}/knowledge/resources")
        detail = client.get(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}")

    assert listing.status_code == 200 and listing.json()["items"] == []
    assert detail.status_code == 404


class _DisableDuringAnswer:
    def __init__(self, database: Database, source_id: UUID) -> None:
        self.database = database
        self.source_id = source_id

    def generate(self, *, question: str, evidence: list[AnswerEvidence]) -> ProviderAnswer:
        assert question and evidence
        with self.database.session_factory.begin() as session:
            source = session.get(KnowledgeSource, self.source_id)
            assert source is not None
            source.status = "disabled"
            source.disabled_at = datetime.now(UTC)
        return ProviderAnswer(
            status="answered",
            paragraphs=[ProviderParagraph(text="revoked", citationIds=["S1"])],
        )


@pytest.mark.integration
def test_answer_revalidates_source_after_generation(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source = _source(database, actor.organization_id, project_id)
    _seed_feishu_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        source=source,
        title="answer source",
    )
    with knowledge_client(
        knowledge_settings(test_database_url),
        database,
        actor,
        MemoryObjectStore(),
        SearchEmbedding(),
        _DisableDuringAnswer(database, source.id),
    ) as client:
        response = client.post(
            f"/api/v1/projects/{project_id}/knowledge/answers",
            json={"question": "source revocation sentinel?"},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "knowledge_changed"


@pytest.mark.integration
def test_batch_with_revoked_linked_item_is_concealed_as_a_whole(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source = _source(database, actor.organization_id, project_id)
    resource_id, version_id, _ = _seed_feishu_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        source=source,
        title="batch source",
    )
    batch_id = uuid4()
    now = datetime.now(UTC)
    with database.session_factory.begin() as session:
        session.add(
            IngestionBatch(
                id=batch_id,
                org_id=actor.organization_id,
                project_id=project_id,
                created_by=actor.user_id,
                status=IngestionBatchStatus.COMPLETED,
                item_count=1,
                ready_count=1,
                completed_at=now,
            )
        )
        session.add(
            IngestionItem(
                org_id=actor.organization_id,
                project_id=project_id,
                batch_id=batch_id,
                normalized_path="batch-source.txt",
                media_type="text/plain",
                size_bytes=20,
                sha256="a" * 64,
                status=IngestionItemStatus.READY,
                resource_id=resource_id,
                resource_version_id=version_id,
                completed_at=now,
            )
        )

    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        visible = client.get(f"/api/v1/projects/{project_id}/knowledge/batches/{batch_id}")
        with database.session_factory.begin() as session:
            stored = session.get(KnowledgeSource, source.id)
            assert stored is not None
            stored.status = "disabled"
            stored.disabled_at = now
        revoked = client.get(f"/api/v1/projects/{project_id}/knowledge/batches/{batch_id}")

    assert visible.status_code == 200
    assert revoked.status_code == 404


@pytest.mark.integration
def test_cross_project_and_cross_tenant_sources_are_not_content_authority(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    other = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    other_project = seed_project(database, actor, permission=None)
    other_tenant_project = seed_project(database, other, permission=None)
    wrong_sources = [
        _source(database, actor.organization_id, other_project),
        _source(database, other.organization_id, other_tenant_project),
    ]
    resource_ids = [
        _seed_feishu_resource(
            database,
            org_id=actor.organization_id,
            project_id=project_id,
            source=source,
            title=f"wrong scope {index}",
        )[0]
        for index, source in enumerate(wrong_sources)
    ]

    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        listing = client.get(f"/api/v1/projects/{project_id}/knowledge/resources")
        details = [
            client.get(f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}")
            for resource_id in resource_ids
        ]

    assert listing.status_code == 200 and listing.json()["items"] == []
    assert all(response.status_code == 404 for response in details)


@pytest.mark.integration
def test_source_filter_runs_before_pagination_and_preserves_versionless_upload(
    database: Database,
    test_database_url: str,
) -> None:
    actor = seed_actor(database, MembershipRole.OWNER)
    project_id = seed_project(database, actor, permission=None)
    source = _source(database, actor.organization_id, project_id)
    hidden_id, _, _ = _seed_feishu_resource(
        database,
        org_id=actor.organization_id,
        project_id=project_id,
        source=source,
        title="hidden before limit",
    )
    upload_id = uuid4()
    with database.session_factory.begin() as session:
        hidden = session.get(KnowledgeResource, hidden_id)
        stored_source = session.get(KnowledgeSource, source.id)
        assert hidden is not None and stored_source is not None
        hidden.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        stored_source.status = "disabled"
        stored_source.disabled_at = datetime.now(UTC)
        session.add(
            KnowledgeResource(
                id=upload_id,
                org_id=actor.organization_id,
                project_id=project_id,
                title="versionless upload",
                source_type="upload",
                source_id=str(uuid4()),
                external_id="versionless.txt",
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )

    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, MemoryObjectStore()
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources", params={"limit": 1}
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(upload_id),
                "title": "versionless upload",
                "sourceType": "upload",
                "createdAt": "2026-01-02T00:00:00Z",
                "updatedAt": response.json()["items"][0]["updatedAt"],
                "latestVersion": None,
            }
        ],
        "nextCursor": None,
        "capabilities": {"canWrite": True},
    }
