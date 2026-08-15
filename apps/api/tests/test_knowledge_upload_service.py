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
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceVersionStatus,
    UploadSession,
)
from cairn_api.knowledge.object_store import (
    ObjectNotFound,
    ObjectStat,
    ObjectStore,
    ObjectStoreUnavailable,
    PresignedPut,
)
from cairn_api.knowledge.schemas import UploadFileIntent
from cairn_api.knowledge.upload_service import KnowledgeUploadService
from cairn_api.organizations.schemas import MembershipResponse, OrganizationResponse
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 13, 2, 0, tzinfo=UTC)
AUDIT = RequestAuditContext(
    trace_id="req-knowledge-upload",
    ip="198.51.100.31",
    user_agent="knowledge-upload-test",
)


def _identity(org_id: UUID) -> IdentityContextResponse:
    return IdentityContextResponse(
        user=UserResponse(id=uuid4(), email="writer@example.com", display_name="Writer"),
        organization=OrganizationResponse(id=org_id, slug="writers", name="Writers"),
        membership=MembershipResponse(id=uuid4(), role=MembershipRole.MEMBER),
        csrf_token="csrf",
    )


def _intent(
    *,
    file_name: str = "report.pdf",
    media_type: str = "application/pdf",
    size_bytes: int = 128,
    sha256: str = "a" * 64,
) -> UploadFileIntent:
    return UploadFileIntent.model_validate(
        {
            "fileName": file_name,
            "mediaType": media_type,
            "sizeBytes": size_bytes,
            "sha256": sha256,
        }
    )


def _record(
    *,
    org_id: UUID,
    project_id: UUID,
    intent: UploadFileIntent,
    canonical_media_type: str | None = None,
    expires_at: datetime = NOW + timedelta(minutes=15),
) -> repository.UploadRecord:
    batch_id = uuid4()
    item = IngestionItem(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        batch_id=batch_id,
        normalized_path=intent.file_name,
        media_type=canonical_media_type or intent.media_type,
        size_bytes=intent.size_bytes,
        sha256=intent.sha256,
        status=IngestionItemStatus.AWAITING_UPLOAD,
        created_at=NOW,
    )
    upload = UploadSession(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        batch_id=batch_id,
        item_id=item.id,
        original_file_name=intent.file_name,
        declared_media_type=canonical_media_type or intent.media_type,
        size_bytes=intent.size_bytes,
        sha256=intent.sha256,
        object_key=f"orgs/{org_id}/projects/{project_id}/uploads/{uuid4().hex}",
        expires_at=expires_at,
        created_at=NOW,
    )
    return repository.UploadRecord(upload=upload, item=item)


def _service(
    *,
    session: MagicMock,
    policy: MagicMock,
    object_store: Mock,
) -> KnowledgeUploadService:
    return KnowledgeUploadService(
        session,
        object_store,
        policy=policy,
        now=lambda: NOW,
        upload_ttl=timedelta(minutes=15),
    )


def _added[Model](session: MagicMock, model_type: type[Model]) -> list[Model]:
    return [
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], model_type)
    ]


def test_create_batch_authorizes_then_rejects_duplicate_names_before_writes() -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    identity = _identity(uuid4())
    service = _service(session=session, policy=policy, object_store=object_store)
    project_id = uuid4()

    with pytest.raises(ApiProblem) as caught:
        service.create_batch(
            identity=identity,
            project_id=project_id,
            files=[_intent(file_name="Résumé.pdf"), _intent(file_name="RÉSUMÉ.PDF")],
            audit=AUDIT,
        )

    assert caught.value.status_code == 422
    assert caught.value.code == "duplicate_file_name"
    policy.require_project.assert_called_once_with(
        identity,
        project_id,
        ProjectPermission.WRITE,
    )
    session.begin.assert_not_called()
    session.add.assert_not_called()
    object_store.presign_put.assert_not_called()


def test_create_batch_uses_write_policy_random_tenant_keys_and_fifteen_minute_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    org_id = uuid4()
    project_id = uuid4()
    identity = _identity(org_id)
    intents = [_intent(), _intent(file_name="notes.md", media_type="text/markdown")]
    batch = IngestionBatch(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        created_by=identity.user.id,
        item_count=2,
        created_at=NOW,
    )
    records = [
        _record(
            org_id=org_id,
            project_id=project_id,
            intent=intent,
            canonical_media_type=intent.media_type,
        )
        for intent in intents
    ]
    for record in records:
        record.upload.batch_id = batch.id
        record.item.batch_id = batch.id
    create_batch = Mock(return_value=batch)
    record_results = iter(records)

    def create_upload_with_key(*_args: object, **kwargs: object) -> repository.UploadRecord:
        record = next(record_results)
        record.upload.object_key = str(kwargs["object_key"])
        return record

    create_upload = Mock(side_effect=create_upload_with_key)
    add_outbox = Mock()
    events: list[str] = []

    def require_project(*_args: object, **kwargs: object) -> None:
        events.append("authorize_locked" if kwargs.get("for_update") else "authorize_preflight")

    transaction_context = session.begin.return_value

    def begin() -> MagicMock:
        events.append("begin")
        return transaction_context

    def create_batch_with_event(*args: object, **kwargs: object) -> IngestionBatch:
        events.append("create_batch")
        return batch

    policy.require_project.side_effect = require_project
    session.begin.side_effect = begin
    create_batch.side_effect = create_batch_with_event
    monkeypatch.setattr(repository, "create_batch", create_batch)
    monkeypatch.setattr(repository, "create_upload_session", create_upload)
    monkeypatch.setattr(repository, "add_project_outbox_event", add_outbox)
    signed_uploads = iter(
        [
            PresignedPut(
                url=f"https://objects.example/{index}",
                headers={"If-None-Match": "*"},
                expires_at=NOW + timedelta(minutes=15),
            )
            for index in range(2)
        ]
    )

    def presign_put(*_args: object, **_kwargs: object) -> PresignedPut:
        events.append("presign")
        return next(signed_uploads)

    object_store.presign_put.side_effect = presign_put

    response = _service(
        session=session,
        policy=policy,
        object_store=object_store,
    ).create_batch(
        identity=identity,
        project_id=project_id,
        files=intents,
        audit=AUDIT,
    )

    assert events == [
        "authorize_preflight",
        "presign",
        "presign",
        "begin",
        "authorize_locked",
        "create_batch",
    ]
    assert response.batch_id == batch.id
    assert [upload.upload_id for upload in response.uploads] == [
        record.upload.id for record in records
    ]
    assert len({record.upload.object_key for record in records}) == 2
    expected_prefix = f"orgs/{org_id}/projects/{project_id}/uploads/"
    assert all(record.upload.object_key.startswith(expected_prefix) for record in records)
    for call, record in zip(object_store.presign_put.call_args_list, records, strict=True):
        assert call.kwargs == {
            "object_key": record.upload.object_key,
            "content_type": record.upload.declared_media_type,
            "checksum_sha256": record.upload.sha256,
            "expires_in": timedelta(minutes=15),
        }
    audits = _added(session, AuditLog)
    assert [(audit.action, audit.resource_id) for audit in audits] == [
        ("knowledge.upload_batch_created", batch.id)
    ]
    assert audits[0].actor_id == identity.user.id
    assert audits[0].trace_id == AUDIT.trace_id
    add_outbox.assert_called_once()
    assert add_outbox.call_args.kwargs["event_type"] == "knowledge.upload_batch_created"
    assert add_outbox.call_args.kwargs["project_id"] == project_id


def test_create_batch_maps_object_store_signing_outage_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    org_id = uuid4()
    project_id = uuid4()
    identity = _identity(org_id)
    intent = _intent()
    batch = IngestionBatch(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        created_by=identity.user.id,
        item_count=1,
        created_at=NOW,
    )
    monkeypatch.setattr(repository, "create_batch", Mock(return_value=batch))
    monkeypatch.setattr(
        repository,
        "create_upload_session",
        Mock(return_value=_record(org_id=org_id, project_id=project_id, intent=intent)),
    )
    object_store.presign_put.side_effect = ObjectStoreUnavailable()

    with pytest.raises(ApiProblem) as caught:
        _service(session=session, policy=policy, object_store=object_store).create_batch(
            identity=identity,
            project_id=project_id,
            files=[intent],
            audit=AUDIT,
        )

    assert caught.value.status_code == 503
    assert caught.value.code == "object_store_unavailable"


def test_complete_normal_upload_is_idempotent_and_creates_one_version_job_and_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    org_id = uuid4()
    project_id = uuid4()
    identity = _identity(org_id)
    record = _record(org_id=org_id, project_id=project_id, intent=_intent())
    resource = KnowledgeResource(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        title=record.upload.original_file_name,
        source_type="upload",
        source_id=str(record.upload.id),
        external_id=record.item.normalized_path,
        created_by=identity.user.id,
        created_at=NOW,
        updated_at=NOW,
    )
    version = KnowledgeResourceVersion(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        resource_id=resource.id,
        source_type="upload",
        source_id=str(record.upload.id),
        external_id=record.item.normalized_path,
        source_version=record.upload.sha256,
        object_key=record.upload.object_key,
        media_type=record.upload.declared_media_type,
        size_bytes=record.upload.size_bytes,
        sha256=record.upload.sha256,
        parser_profile="default-v1",
        chunking_profile="default-v1",
        status=ResourceVersionStatus.QUEUED,
        created_at=NOW,
    )
    job = IngestionJob(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        job_kind=JobKind.INDEX_RESOURCE_VERSION,
        target_id=version.id,
        next_attempt_at=NOW,
        created_at=NOW,
    )
    create_resource = Mock(return_value=(resource, version))
    create_job = Mock(return_value=job)
    add_outbox = Mock()

    def mark_complete(*_args: object, **_kwargs: object) -> None:
        record.upload.completed_at = NOW
        record.upload.resource_version_id = version.id
        record.item.resource_id = resource.id
        record.item.resource_version_id = version.id
        record.item.status = IngestionItemStatus.QUEUED

    monkeypatch.setattr(repository, "get_upload_for_update", Mock(return_value=record))
    monkeypatch.setattr(repository, "create_resource_with_version", create_resource)
    monkeypatch.setattr(repository, "create_ingestion_job", create_job)
    monkeypatch.setattr(repository, "mark_upload_complete", Mock(side_effect=mark_complete))
    monkeypatch.setattr(repository, "refresh_batch_summary", Mock())
    monkeypatch.setattr(repository, "add_project_outbox_event", add_outbox)
    object_store.stat.return_value = ObjectStat(
        size_bytes=record.upload.size_bytes,
        content_type=record.upload.declared_media_type,
        checksum_sha256=record.upload.sha256,
    )
    service = _service(session=session, policy=policy, object_store=object_store)

    first = service.complete_upload(
        identity=identity,
        project_id=project_id,
        upload_id=record.upload.id,
        audit=AUDIT,
    )
    second = service.complete_upload(
        identity=identity,
        project_id=project_id,
        upload_id=record.upload.id,
        audit=AUDIT,
    )

    assert first == second
    assert first.resource_id == resource.id
    assert first.resource_version_id == version.id
    assert first.status is IngestionItemStatus.QUEUED
    assert create_resource.call_count == create_job.call_count == 1
    assert create_job.call_args.kwargs["job_kind"] is JobKind.INDEX_RESOURCE_VERSION
    assert create_job.call_args.kwargs["target_id"] == version.id
    assert object_store.stat.call_count == 1
    assert len(_added(session, AuditLog)) == 1
    assert add_outbox.call_count == 1


def test_complete_zip_upload_enqueues_expansion_without_creating_a_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    org_id = uuid4()
    project_id = uuid4()
    identity = _identity(org_id)
    record = _record(
        org_id=org_id,
        project_id=project_id,
        intent=_intent(file_name="bundle.zip", media_type="application/zip"),
    )
    create_resource = Mock()
    create_job = Mock(
        return_value=IngestionJob(
            id=uuid4(),
            org_id=org_id,
            project_id=project_id,
            job_kind=JobKind.EXPAND_ARCHIVE,
            target_id=record.item.id,
            next_attempt_at=NOW,
            created_at=NOW,
        )
    )

    def mark_complete(*_args: object, **_kwargs: object) -> None:
        record.upload.completed_at = NOW
        record.item.status = IngestionItemStatus.QUEUED

    monkeypatch.setattr(repository, "get_upload_for_update", Mock(return_value=record))
    monkeypatch.setattr(repository, "create_resource_with_version", create_resource)
    monkeypatch.setattr(repository, "create_ingestion_job", create_job)
    monkeypatch.setattr(repository, "mark_upload_complete", Mock(side_effect=mark_complete))
    monkeypatch.setattr(repository, "refresh_batch_summary", Mock())
    monkeypatch.setattr(repository, "add_project_outbox_event", Mock())
    object_store.stat.return_value = ObjectStat(
        size_bytes=record.upload.size_bytes,
        content_type="application/zip",
        checksum_sha256=record.upload.sha256,
    )

    result = _service(
        session=session,
        policy=policy,
        object_store=object_store,
    ).complete_upload(
        identity=identity,
        project_id=project_id,
        upload_id=record.upload.id,
        audit=AUDIT,
    )

    assert result.resource_id is result.resource_version_id is None
    create_resource.assert_not_called()
    assert create_job.call_args.kwargs["job_kind"] is JobKind.EXPAND_ARCHIVE
    assert create_job.call_args.kwargs["target_id"] == record.item.id


@pytest.mark.parametrize(
    ("stat", "expected_code"),
    [
        (
            ObjectStat(
                size_bytes=127,
                content_type="application/pdf",
                checksum_sha256="a" * 64,
            ),
            "upload_size_mismatch",
        ),
        (
            ObjectStat(
                size_bytes=128,
                content_type="application/pdf",
                checksum_sha256="b" * 64,
            ),
            "upload_checksum_mismatch",
        ),
        (
            ObjectStat(
                size_bytes=128,
                content_type="text/plain",
                checksum_sha256="a" * 64,
            ),
            "upload_media_type_mismatch",
        ),
    ],
)
def test_complete_upload_persists_terminal_object_mismatch_without_creating_jobs(
    monkeypatch: pytest.MonkeyPatch,
    stat: ObjectStat,
    expected_code: str,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    org_id = uuid4()
    project_id = uuid4()
    identity = _identity(org_id)
    record = _record(org_id=org_id, project_id=project_id, intent=_intent())
    mark_failed = Mock()
    monkeypatch.setattr(repository, "get_upload_for_update", Mock(return_value=record))
    monkeypatch.setattr(repository, "mark_item_failed", mark_failed)
    monkeypatch.setattr(repository, "refresh_batch_summary", Mock())
    monkeypatch.setattr(repository, "add_project_outbox_event", Mock())
    monkeypatch.setattr(repository, "create_resource_with_version", Mock())
    monkeypatch.setattr(repository, "create_ingestion_job", Mock())
    object_store.stat.return_value = stat

    with pytest.raises(ApiProblem) as caught:
        _service(session=session, policy=policy, object_store=object_store).complete_upload(
            identity=identity,
            project_id=project_id,
            upload_id=record.upload.id,
            audit=AUDIT,
        )

    assert caught.value.status_code == 409
    assert caught.value.code == expected_code
    mark_failed.assert_called_once()
    assert mark_failed.call_args.kwargs["error_code"] == expected_code
    assert mark_failed.call_args.kwargs["abandon_upload"] is True


@pytest.mark.parametrize(
    ("failure", "status_code", "code"),
    [
        (ObjectNotFound(), 409, "upload_object_missing"),
        (ObjectStoreUnavailable(), 503, "object_store_unavailable"),
    ],
)
def test_complete_upload_maps_object_store_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    status_code: int,
    code: str,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    org_id = uuid4()
    project_id = uuid4()
    identity = _identity(org_id)
    record = _record(org_id=org_id, project_id=project_id, intent=_intent())
    mark_failed = Mock()
    refresh_summary = Mock()
    add_outbox = Mock()
    monkeypatch.setattr(repository, "get_upload_for_update", Mock(return_value=record))
    monkeypatch.setattr(repository, "mark_item_failed", mark_failed)
    monkeypatch.setattr(repository, "refresh_batch_summary", refresh_summary)
    monkeypatch.setattr(repository, "add_project_outbox_event", add_outbox)
    object_store.stat.side_effect = failure

    with pytest.raises(ApiProblem) as caught:
        _service(session=session, policy=policy, object_store=object_store).complete_upload(
            identity=identity,
            project_id=project_id,
            upload_id=record.upload.id,
            audit=AUDIT,
        )

    assert caught.value.status_code == status_code
    assert caught.value.code == code
    policy.require_project.assert_called_once_with(
        identity,
        project_id,
        ProjectPermission.WRITE,
        for_update=True,
    )
    if isinstance(failure, ObjectStoreUnavailable):
        mark_failed.assert_not_called()
        refresh_summary.assert_not_called()
        add_outbox.assert_not_called()
        session.add.assert_not_called()
    else:
        mark_failed.assert_called_once()
        refresh_summary.assert_called_once()
        add_outbox.assert_called_once()


def test_complete_expired_upload_fails_without_touching_object_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    policy = MagicMock(spec=AuthorizationPolicy)
    object_store = Mock(spec=ObjectStore)
    org_id = uuid4()
    project_id = uuid4()
    record = _record(
        org_id=org_id,
        project_id=project_id,
        intent=_intent(),
        expires_at=NOW,
    )
    mark_failed = Mock()
    monkeypatch.setattr(repository, "get_upload_for_update", Mock(return_value=record))
    monkeypatch.setattr(repository, "mark_item_failed", mark_failed)
    monkeypatch.setattr(repository, "refresh_batch_summary", Mock())
    monkeypatch.setattr(repository, "add_project_outbox_event", Mock())

    with pytest.raises(ApiProblem) as caught:
        _service(session=session, policy=policy, object_store=object_store).complete_upload(
            identity=_identity(org_id),
            project_id=project_id,
            upload_id=record.upload.id,
            audit=AUDIT,
        )

    assert caught.value.status_code == 410
    assert caught.value.code == "upload_expired"
    object_store.stat.assert_not_called()
    assert mark_failed.call_args.kwargs["error_code"] == "upload_expired"
