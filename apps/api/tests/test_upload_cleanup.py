from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from cairn_api.db.session import Database
from cairn_api.knowledge.models import IngestionItem, IngestionItemStatus, UploadSession
from cairn_api.knowledge.object_store import ObjectNotFound, ObjectStore, ObjectStoreUnavailable
from cairn_api.maintenance import upload_cleanup
from cairn_api.maintenance.upload_cleanup import run_upload_cleanup
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)


def test_cleanup_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit"):
        run_upload_cleanup(
            database=MagicMock(spec=Database),
            object_store=Mock(spec=ObjectStore),
            now=lambda: NOW,
            limit=0,
        )


def test_cleanup_marks_expired_upload_failed_and_deletes_unreferenced_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = MagicMock()
    database = cast(Database, SimpleNamespace(session_factory=session_factory))
    store = Mock(spec=ObjectStore)
    upload = UploadSession(
        id=uuid4(),
        org_id=uuid4(),
        project_id=uuid4(),
        batch_id=uuid4(),
        item_id=uuid4(),
        original_file_name="expired.pdf",
        declared_media_type="application/pdf",
        size_bytes=1,
        sha256="a" * 64,
        object_key="orgs/expired.pdf",
        expires_at=NOW - timedelta(minutes=1),
        created_at=NOW - timedelta(minutes=16),
    )
    item = IngestionItem(
        id=upload.item_id,
        org_id=upload.org_id,
        project_id=upload.project_id,
        batch_id=upload.batch_id,
        normalized_path="expired.pdf",
        media_type="application/pdf",
        size_bytes=1,
        sha256="a" * 64,
        status=IngestionItemStatus.AWAITING_UPLOAD,
        created_at=upload.created_at,
    )
    session = MagicMock()
    session_factory.return_value.__enter__.return_value = session
    repository = pytest.importorskip("cairn_api.maintenance.upload_cleanup")
    monkeypatch.setattr(repository, "claim_expired_uploads", Mock(return_value=[(upload, item)]))
    mark_failed = Mock()
    monkeypatch.setattr(repository, "mark_expired_upload", mark_failed)
    monkeypatch.setattr(repository, "refresh_expired_batch", Mock())
    monkeypatch.setattr(repository, "find_orphan_upload_objects", Mock(return_value=[upload]))
    monkeypatch.setattr(repository, "object_key_is_referenced", Mock(return_value=False))

    result = run_upload_cleanup(
        database=database,
        object_store=store,
        now=lambda: NOW,
        limit=10,
    )

    mark_failed.assert_called_once_with(session, upload=upload, item=item, failed_at=NOW)
    store.delete_object.assert_called_once_with(object_key=upload.object_key)
    assert result.uploads_expired == 1
    assert result.objects_deleted == 1


def test_cleanup_preserves_referenced_objects_and_tolerates_missing_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = MagicMock()
    database = cast(Database, SimpleNamespace(session_factory=session_factory))
    store = Mock(spec=ObjectStore)
    module = pytest.importorskip("cairn_api.maintenance.upload_cleanup")
    uploads = [Mock(object_key="referenced"), Mock(object_key="missing")]
    session_factory.return_value.__enter__.return_value = MagicMock()
    monkeypatch.setattr(module, "claim_expired_uploads", Mock(return_value=[]))
    monkeypatch.setattr(module, "find_orphan_upload_objects", Mock(return_value=uploads))

    def is_referenced(_session: Session, *, object_key: str) -> bool:
        return object_key == "referenced"

    monkeypatch.setattr(module, "object_key_is_referenced", Mock(side_effect=is_referenced))
    store.delete_object.side_effect = ObjectNotFound()

    result = run_upload_cleanup(
        database=database,
        object_store=store,
        now=lambda: NOW,
        limit=10,
    )

    store.delete_object.assert_called_once_with(object_key="missing")
    assert result.objects_deleted == 0
    assert result.objects_missing == 1


def test_cleanup_command_reports_failure_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = SimpleNamespace(database_url="postgresql+psycopg://test")
    database = MagicMock(spec=Database)
    store = Mock(spec=ObjectStore)
    monkeypatch.setattr(upload_cleanup, "Settings", Mock(return_value=settings))
    monkeypatch.setattr(upload_cleanup, "Database", Mock(return_value=database))
    monkeypatch.setattr(
        "cairn_api.maintenance.upload_cleanup.Boto3ObjectStore.from_settings",
        Mock(return_value=store),
    )
    monkeypatch.setattr(
        upload_cleanup,
        "run_upload_cleanup",
        Mock(side_effect=ObjectStoreUnavailable()),
    )

    assert upload_cleanup.run_upload_cleanup_command() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "upload-cleanup failed" in captured.err
    store.close.assert_called_once_with()
    database.dispose.assert_called_once_with()


def test_cleanup_command_closes_database_when_object_store_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = SimpleNamespace(database_url="postgresql+psycopg://test")
    database = MagicMock(spec=Database)
    monkeypatch.setattr(upload_cleanup, "Settings", Mock(return_value=settings))
    monkeypatch.setattr(upload_cleanup, "Database", Mock(return_value=database))
    monkeypatch.setattr(
        "cairn_api.maintenance.upload_cleanup.Boto3ObjectStore.from_settings",
        Mock(side_effect=ObjectStoreUnavailable()),
    )

    assert upload_cleanup.run_upload_cleanup_command() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "upload-cleanup failed" in captured.err
    database.dispose.assert_called_once_with()
