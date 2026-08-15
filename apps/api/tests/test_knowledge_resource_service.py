from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.schemas import IdentityContextResponse, UserResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.types import MembershipRole, ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import (
    IngestionBatch,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobStatus,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
)
from cairn_api.knowledge.object_store import ObjectStore
from cairn_api.knowledge.resource_service import KnowledgeResourceService
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from cairn_api.projects.models import OutboxEvent
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)
AUDIT = RequestAuditContext(
    trace_id="req-resource-lifecycle",
    ip="198.51.100.41",
    user_agent="resource-lifecycle-test",
)


def _identity(org_id: UUID | None = None) -> IdentityContextResponse:
    organization_id = org_id or uuid4()
    return IdentityContextResponse(
        user=UserResponse(id=uuid4(), email="reader@example.com", display_name="Reader"),
        organization=OrganizationResponse(
            id=organization_id,
            slug="readers",
            name="Readers",
        ),
        membership=MembershipResponse(id=uuid4(), role=MembershipRole.MEMBER),
        csrf_token="csrf",
    )


def _resource(org_id: UUID, project_id: UUID) -> KnowledgeResource:
    resource_id = uuid4()
    version_id = uuid4()
    resource = KnowledgeResource(
        id=resource_id,
        org_id=org_id,
        project_id=project_id,
        title="报告.pdf",
        source_type="upload",
        source_id="upload-session",
        external_id="报告.pdf",
        current_version_id=version_id,
        created_at=NOW,
        updated_at=NOW,
    )
    return resource


def _version(resource: KnowledgeResource) -> KnowledgeResourceVersion:
    return KnowledgeResourceVersion(
        id=resource.current_version_id,
        org_id=resource.org_id,
        project_id=resource.project_id,
        resource_id=resource.id,
        source_type="upload",
        source_id="upload-session",
        external_id="报告.pdf",
        source_version="a" * 64,
        object_key="orgs/hidden/report.pdf",
        media_type="application/pdf",
        size_bytes=128,
        sha256="a" * 64,
        parser_profile="default-v1",
        chunking_profile="default-v1",
        status=ResourceVersionStatus.READY,
        created_at=NOW,
        processing_started_at=NOW,
        ready_at=NOW,
    )


def test_list_resources_passes_read_acl_filter_and_derives_write_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    identity = _identity()
    project_id = uuid4()
    access_filter = Mock()
    resource = _resource(identity.organization.id, project_id)
    version = _version(resource)
    policy.project_filter.return_value = access_filter
    policy.find_project.side_effect = [Mock(), None]
    list_resources = Mock(return_value=([(resource, version)], None))
    monkeypatch.setattr(repository, "list_resources", list_resources)

    result = KnowledgeResourceService(
        session,
        object_store,
        policy=policy,
        now=lambda: NOW,
    ).list_resources(
        identity=identity,
        project_id=project_id,
        cursor=None,
        limit=20,
    )

    policy.project_filter.assert_called_once_with(
        identity,
        ProjectPermission.READ,
        KnowledgeResource.project_id,
    )
    list_resources.assert_called_once_with(
        session,
        org_id=identity.organization.id,
        project_id=project_id,
        access_filter=access_filter,
        cursor=None,
        limit=20,
    )
    assert result.capabilities.can_write is False
    assert result.items[0].id == resource.id
    assert "object_key" not in result.model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize("error_code", ["embedding_unavailable", "ingestion_retry_exhausted"])
def test_retry_failed_version_reuses_job_and_creates_manual_attempt(
    error_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    identity = _identity()
    project_id = uuid4()
    resource = _resource(identity.organization.id, project_id)
    version = _version(resource)
    version.status = ResourceVersionStatus.FAILED
    version.error_code = error_code
    version.ready_at = None
    job = IngestionJob(
        id=uuid4(),
        org_id=identity.organization.id,
        project_id=project_id,
        job_kind="index_resource_version",
        target_id=version.id,
        profile_version="default-v1",
        status=IngestionJobStatus.FAILED,
        attempt=5,
        max_attempts=5,
        next_attempt_at=NOW,
        last_error_code=error_code,
        completed_at=NOW,
        created_at=NOW,
    )
    monkeypatch.setattr(
        repository,
        "get_resource_version_job_for_update",
        Mock(return_value=(resource, version, job)),
    )
    queued_attempt = IngestionJobAttempt(
        id=uuid4(),
        org_id=identity.organization.id,
        project_id=project_id,
        job_id=job.id,
        ordinal=6,
        trigger="manual",
        status="queued",
        queued_at=NOW,
    )

    def queue_retry(*_args: object, **_kwargs: object) -> IngestionJobAttempt:
        version.status = ResourceVersionStatus.QUEUED
        version.error_code = None
        return queued_attempt

    queue_attempt = Mock(side_effect=queue_retry)
    monkeypatch.setattr(repository, "queue_manual_retry", queue_attempt)
    monkeypatch.setattr(repository, "add_project_outbox_event", Mock())

    result = KnowledgeResourceService(
        session,
        object_store,
        policy=policy,
        now=lambda: NOW,
    ).retry_version(
        identity=identity,
        project_id=project_id,
        resource_id=resource.id,
        version_id=version.id,
        audit=AUDIT,
    )

    policy.require_project.assert_called_once_with(
        identity,
        project_id,
        ProjectPermission.WRITE,
        for_update=True,
    )
    queue_attempt.assert_called_once_with(session, job=job, version=version, queued_at=NOW)
    assert result.id == resource.id
    assert result.latest_version is not None
    assert result.latest_version.status == ResourceVersionStatus.QUEUED
    audits = [
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], AuditLog)
    ]
    assert [audit.action for audit in audits] == ["knowledge.version_retried"]


@pytest.mark.parametrize(
    "error_code",
    [
        None,
        "encrypted_pdf_unsupported",
        "no_extractable_text",
        "embedding_dimension_mismatch",
        "archive_path_unsafe",
        "parser_failed",
    ],
)
def test_retry_rejects_non_retryable_or_non_failed_versions(
    error_code: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    identity = _identity()
    project_id = uuid4()
    resource = _resource(identity.organization.id, project_id)
    version = _version(resource)
    version.status = (
        ResourceVersionStatus.QUEUED if error_code is None else ResourceVersionStatus.FAILED
    )
    version.error_code = error_code
    version.ready_at = None
    job = Mock(spec=IngestionJob)
    monkeypatch.setattr(
        repository,
        "get_resource_version_job_for_update",
        Mock(return_value=(resource, version, job)),
    )
    queue_attempt = Mock()
    monkeypatch.setattr(repository, "queue_manual_retry", queue_attempt)

    with pytest.raises(ApiProblem) as caught:
        KnowledgeResourceService(
            session,
            Mock(spec=ObjectStore),
            policy=policy,
            now=lambda: NOW,
        ).retry_version(
            identity=identity,
            project_id=project_id,
            resource_id=resource.id,
            version_id=version.id,
            audit=AUDIT,
        )

    assert caught.value.status_code == 409
    assert caught.value.code == "version_not_retryable"
    queue_attempt.assert_not_called()


@pytest.mark.parametrize(
    ("method_name", "repository_name", "filter_column", "arguments"),
    [
        ("get_batch", "get_batch_detail", IngestionBatch.project_id, {"batch_id": uuid4()}),
        (
            "get_resource",
            "get_resource_observation",
            KnowledgeResource.project_id,
            {"resource_id": uuid4()},
        ),
        (
            "create_download",
            "get_active_resource",
            KnowledgeResource.project_id,
            {"resource_id": uuid4(), "audit": AUDIT},
        ),
        (
            "get_chunk_context",
            "get_chunk_context",
            KnowledgeResource.project_id,
            {"resource_id": uuid4(), "chunk_id": uuid4()},
        ),
    ],
)
def test_protected_read_applies_live_acl_filter_after_initial_authorization(
    method_name: str,
    repository_name: str,
    filter_column: object,
    arguments: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    identity = _identity()
    project_id = uuid4()
    access_filter = Mock(name="live_acl_filter")
    policy.project_filter.return_value = access_filter
    protected_query = Mock(return_value=None)
    monkeypatch.setattr(repository, repository_name, protected_query)

    with pytest.raises(ApiProblem) as caught:
        getattr(
            KnowledgeResourceService(session, Mock(spec=ObjectStore), policy=policy),
            method_name,
        )(
            identity=identity,
            project_id=project_id,
            **arguments,
        )

    assert caught.value.status_code == 404
    assert caught.value.code == "not_found"
    policy.require_project.assert_called_once_with(
        identity,
        project_id,
        ProjectPermission.READ,
    )
    policy.project_filter.assert_called_once_with(
        identity,
        ProjectPermission.READ,
        filter_column,
    )
    assert protected_query.call_args.kwargs["access_filter"] is access_filter


def test_download_reauthorizes_audits_and_uses_configured_attachment_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    identity = _identity()
    project_id = uuid4()
    resource = _resource(identity.organization.id, project_id)
    version = _version(resource)
    access_filter = Mock()
    policy.project_filter.return_value = access_filter
    get_active_resource = Mock(return_value=(resource, version))
    monkeypatch.setattr(repository, "get_active_resource", get_active_resource)
    object_store.presign_get.return_value = "https://objects.example/download"

    url = KnowledgeResourceService(
        session,
        object_store,
        policy=policy,
        now=lambda: NOW,
        download_ttl=timedelta(seconds=137),
    ).create_download(
        identity=identity,
        project_id=project_id,
        resource_id=resource.id,
        audit=AUDIT,
    )

    policy.require_project.assert_called_once_with(
        identity,
        project_id,
        ProjectPermission.READ,
    )
    get_active_resource.assert_called_once_with(
        session,
        org_id=identity.organization.id,
        project_id=project_id,
        resource_id=resource.id,
        access_filter=access_filter,
    )
    object_store.presign_get.assert_called_once_with(
        object_key=version.object_key,
        download_name=resource.title,
        expires_in=timedelta(seconds=137),
    )
    assert url == "https://objects.example/download"
    audits = [
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], AuditLog)
    ]
    assert [audit.action for audit in audits] == ["knowledge.downloaded"]
    assert not any(
        isinstance(call.args[0], OutboxEvent) for call in session.add.call_args_list
    )


def test_soft_delete_is_idempotent_and_does_not_expose_deleted_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    identity = _identity()
    project_id = uuid4()
    resource = _resource(identity.organization.id, project_id)
    delete = Mock(side_effect=[(resource, True), (resource, False)])
    monkeypatch.setattr(repository, "soft_delete_resource", delete)
    monkeypatch.setattr(repository, "add_project_outbox_event", Mock())
    service = KnowledgeResourceService(
        session,
        Mock(spec=ObjectStore),
        policy=policy,
        now=lambda: NOW,
    )

    service.delete_resource(
        identity=identity,
        project_id=project_id,
        resource_id=resource.id,
        audit=AUDIT,
    )
    resource.deleted_at = NOW
    service.delete_resource(
        identity=identity,
        project_id=project_id,
        resource_id=resource.id,
        audit=AUDIT,
    )

    assert delete.call_count == 2
    assert resource.deleted_at == NOW
