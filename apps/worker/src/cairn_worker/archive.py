import hashlib
import mimetypes
import re
import stat
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO, Protocol, cast
from uuid import UUID, uuid5
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo

from cairn_api.audit.repository import add_audit_log
from cairn_api.knowledge import repository
from cairn_api.knowledge.media import (
    MediaDescriptor,
    MediaValidationError,
    SupportedMediaType,
    validate_upload_intent,
    verify_signature,
)
from cairn_api.knowledge.models import (
    IngestionItem,
    IngestionItemStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobAttemptStatus,
    IngestionJobStatus,
    JobKind,
    KnowledgeResource,
    KnowledgeResourceVersion,
    ResourceSourceType,
    ResourceVersionStatus,
    UploadSession,
)
from cairn_api.knowledge.object_store import (
    ObjectNotFound,
    ObjectStat,
    ObjectStore,
    ObjectStoreUnavailable,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cairn_worker.errors import WorkerFailure, safe_detail_for
from cairn_worker.leases import ClaimedJob, finish_job

ARCHIVE_EXPANDED_MAX_BYTES = 500 * 1024 * 1024
ARCHIVE_ENTRY_LIMIT = 200
ARCHIVE_ENTRY_MAX_BYTES = 50 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0
_ARCHIVE_SOURCE_MAX_BYTES = 100 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024
_ENTRY_SPOOL_BYTES = 8 * 1024 * 1024
_NORMALIZED_PATH_MAX_LENGTH = 1024
_RESOURCE_TITLE_MAX_LENGTH = 512
_WINDOWS_DRIVE = re.compile(r"[A-Za-z]:")
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OPC_MEDIA_TYPES = frozenset(
    {
        SupportedMediaType.DOCX,
        SupportedMediaType.PPTX,
        SupportedMediaType.XLSX,
    }
)


class Heartbeat(Protocol):
    def ensure_owned(self) -> None: ...


SessionFactory = Callable[[], Session]
Now = Callable[[], datetime]


@dataclass(frozen=True)
class ArchiveEntryPlan:
    zip_name: str
    normalized_path: str
    media: MediaDescriptor | None
    error_code: str | None


@dataclass(frozen=True)
class WorkerContext:
    session: Any
    session_factory: Any
    heartbeat: Any
    object_store: Any
    now: Now


@dataclass
class _PreparedEntry:
    plan: ArchiveEntryPlan
    size_bytes: int
    sha256: str
    source: BinaryIO
    object_key: str | None = None


class _RetryableEntrySpool:
    def __init__(self, source: BinaryIO) -> None:
        self._source = source

    def _call(self, method: str, *args: object) -> Any:
        try:
            return getattr(self._source, method)(*args)
        except OSError:
            raise _spool_io_failure() from None

    def read(self, size: int = -1) -> bytes:
        return cast(bytes, self._call("read", size))

    def write(self, payload: bytes) -> int:
        return cast(int, self._call("write", payload))

    def seek(self, offset: int, whence: int = 0) -> int:
        return cast(int, self._call("seek", offset, whence))

    def tell(self) -> int:
        return cast(int, self._call("tell"))

    def seekable(self) -> bool:
        return cast(bool, self._call("seekable"))

    def readable(self) -> bool:
        return cast(bool, self._call("readable"))

    def writable(self) -> bool:
        return cast(bool, self._call("writable"))

    def close(self) -> None:
        self._call("close")


@dataclass(frozen=True)
class _ArchiveTarget:
    upload: UploadSession
    parent: IngestionItem
    completed: bool


def _failure(code: str) -> WorkerFailure:
    return WorkerFailure.for_code(code, "")


def _malformed_archive_failure() -> WorkerFailure:
    return WorkerFailure("parser_failed", "", retryable=False)


def _spool_io_failure() -> WorkerFailure:
    return WorkerFailure("parser_failed", "", retryable=True)


def _normalize_path(zip_name: str) -> tuple[str, bool]:
    normalized = unicodedata.normalize("NFKC", zip_name)
    if "\x00" in normalized:
        raise _failure("archive_path_unsafe")
    normalized = normalized.replace("\\", "/")
    is_directory = normalized.endswith("/")
    if normalized.startswith("/") or _WINDOWS_DRIVE.match(normalized) is not None:
        raise _failure("archive_path_unsafe")
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise _failure("archive_path_unsafe")
        parts.append(part)
    if not parts:
        if is_directory:
            return "", True
        raise _failure("archive_path_unsafe")
    return "/".join(parts), is_directory


def _is_symlink(info: ZipInfo) -> bool:
    unix_mode = info.external_attr >> 16
    return info.create_system == 3 and stat.S_IFMT(unix_mode) == stat.S_IFLNK


def _descriptor(path: str, size_bytes: int) -> MediaDescriptor | None:
    file_name = PurePosixPath(path).name
    guessed, _encoding = mimetypes.guess_type(file_name, strict=False)
    if guessed is None:
        return None
    try:
        return validate_upload_intent(
            file_name=file_name,
            declared_media_type=guessed,
            size_bytes=size_bytes,
        )
    except MediaValidationError as error:
        if error.code == "unsupported_media_type":
            return None
        raise _failure(error.code) from None


def _metadata_plans(archive: ZipFile) -> list[tuple[ZipInfo, ArchiveEntryPlan]]:
    plans: list[tuple[ZipInfo, ArchiveEntryPlan]] = []
    duplicate_keys: set[str] = set()
    expanded_bytes = 0
    compressed_bytes = 0
    for info in archive.infolist():
        normalized_path, path_is_directory = _normalize_path(info.orig_filename)
        is_directory = info.is_dir() or path_is_directory
        if len(normalized_path) > _NORMALIZED_PATH_MAX_LENGTH or (
            not is_directory
            and len(PurePosixPath(normalized_path).name) > _RESOURCE_TITLE_MAX_LENGTH
        ):
            raise _failure("archive_path_unsafe")
        if info.flag_bits & 0x1:
            raise _failure("archive_encrypted")
        if _is_symlink(info):
            raise _failure("archive_path_unsafe")
        duplicate_key = normalized_path.casefold()
        if duplicate_key in duplicate_keys:
            raise _failure("archive_duplicate_path")
        duplicate_keys.add(duplicate_key)
        if is_directory:
            continue
        if len(plans) >= ARCHIVE_ENTRY_LIMIT:
            raise _failure("archive_limit_exceeded")
        if info.file_size > ARCHIVE_ENTRY_MAX_BYTES:
            raise _failure("archive_limit_exceeded")
        expanded_bytes += info.file_size
        compressed_bytes += info.compress_size
        if expanded_bytes > ARCHIVE_EXPANDED_MAX_BYTES:
            raise _failure("archive_limit_exceeded")
        if info.file_size > 0 and (
            info.compress_size == 0
            or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise _failure("archive_limit_exceeded")
        descriptor = _descriptor(normalized_path, info.file_size)
        if descriptor is not None and descriptor.is_archive:
            raise _failure("archive_nested")
        plans.append(
            (
                info,
                ArchiveEntryPlan(
                    zip_name=info.orig_filename,
                    normalized_path=normalized_path,
                    media=descriptor,
                    error_code=None if descriptor is not None else "unsupported_media_type",
                ),
            )
        )
    if expanded_bytes > 0 and (
        compressed_bytes == 0 or expanded_bytes / compressed_bytes > MAX_COMPRESSION_RATIO
    ):
        raise _failure("archive_limit_exceeded")
    return plans


def _copy_archive(source: BinaryIO) -> tuple[BinaryIO, int, str]:
    target = cast(
        BinaryIO,
        SpooledTemporaryFile(  # noqa: SIM115 -- caller owns and closes the returned spool.
            max_size=_ENTRY_SPOOL_BYTES, mode="w+b"
        ),
    )
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        while True:
            chunk = source.read(_COPY_CHUNK_BYTES)
            if not chunk:
                break
            size_bytes += len(chunk)
            if size_bytes > _ARCHIVE_SOURCE_MAX_BYTES:
                raise _failure("archive_limit_exceeded")
            digest.update(chunk)
            target.write(chunk)
        target.seek(0)
        return target, size_bytes, digest.hexdigest()
    except BaseException:
        target.close()
        raise


def _verify_signature(prepared: _PreparedEntry, prefix: bytes) -> None:
    descriptor = prepared.plan.media
    if descriptor is None:
        if prefix.startswith(_ZIP_SIGNATURES):
            raise _failure("archive_nested")
        return
    if descriptor.is_archive:
        raise _failure("archive_nested")
    opc_members: tuple[str, ...] = ()
    if descriptor.media_type in _OPC_MEDIA_TYPES:
        try:
            prepared.source.seek(0)
            with ZipFile(prepared.source) as opc:
                opc_members = tuple(opc.namelist())
        except OSError:
            raise _spool_io_failure() from None
        except (BadZipFile, LargeZipFile, EOFError):
            raise _failure("upload_media_type_mismatch") from None
    try:
        prepared.source.seek(0)
        verify_signature(descriptor=descriptor, prefix=prefix, opc_members=opc_members)
    except MediaValidationError as error:
        raise _failure(error.code) from None


def _prepare_entries(archive_source: BinaryIO) -> list[_PreparedEntry]:
    prepared_entries: list[_PreparedEntry] = []
    try:
        with ZipFile(archive_source) as archive:
            plans = _metadata_plans(archive)
            actual_expanded = 0
            for info, plan in plans:
                target = cast(
                    BinaryIO,
                    _RetryableEntrySpool(
                        cast(
                            BinaryIO,
                            SpooledTemporaryFile(  # noqa: SIM115
                                max_size=_ENTRY_SPOOL_BYTES, mode="w+b"
                            ),
                        )
                    ),
                )
                try:
                    digest = hashlib.sha256()
                    size_bytes = 0
                    prefix = bytearray()
                    with archive.open(info, "r") as entry:
                        while True:
                            chunk = entry.read(_COPY_CHUNK_BYTES)
                            if not chunk:
                                break
                            size_bytes += len(chunk)
                            actual_expanded += len(chunk)
                            if (
                                size_bytes > ARCHIVE_ENTRY_MAX_BYTES
                                or actual_expanded > ARCHIVE_EXPANDED_MAX_BYTES
                            ):
                                raise _failure("archive_limit_exceeded")
                            if len(prefix) < 8192:
                                prefix.extend(chunk[: 8192 - len(prefix)])
                            digest.update(chunk)
                            target.write(chunk)
                    if size_bytes != info.file_size:
                        raise _malformed_archive_failure()
                    target.seek(0)
                    prepared = _PreparedEntry(
                        plan=plan,
                        size_bytes=size_bytes,
                        sha256=digest.hexdigest(),
                        source=target,
                    )
                    _verify_signature(prepared, bytes(prefix))
                    target.seek(0)
                    prepared_entries.append(prepared)
                except BaseException:
                    target.close()
                    raise
        return prepared_entries
    except WorkerFailure:
        for prepared in prepared_entries:
            prepared.source.close()
        raise
    except OSError:
        for prepared in prepared_entries:
            prepared.source.close()
        raise _spool_io_failure() from None
    except (BadZipFile, LargeZipFile, EOFError, RuntimeError, ValueError):
        for prepared in prepared_entries:
            prepared.source.close()
        raise _malformed_archive_failure() from None


def inspect_archive(source: BinaryIO) -> list[ArchiveEntryPlan]:
    archive_source, _size_bytes, _checksum = _copy_archive(source)
    prepared: list[_PreparedEntry] = []
    try:
        prepared = _prepare_entries(archive_source)
        return [entry.plan for entry in prepared]
    finally:
        for entry in prepared:
            entry.source.close()
        archive_source.close()


def _target(session: Session, claim: ClaimedJob, *, lock: bool) -> _ArchiveTarget:
    job_statement = select(IngestionJob).where(
        IngestionJob.id == claim.job_id,
        IngestionJob.org_id == claim.org_id,
        IngestionJob.project_id == claim.project_id,
        IngestionJob.job_kind == JobKind.EXPAND_ARCHIVE,
        IngestionJob.target_id == claim.target_id,
    )
    target_statement = (
        select(UploadSession, IngestionItem)
        .join(
            IngestionItem,
            (IngestionItem.org_id == UploadSession.org_id)
            & (IngestionItem.project_id == UploadSession.project_id)
            & (IngestionItem.id == UploadSession.item_id),
        )
        .where(
            UploadSession.org_id == claim.org_id,
            UploadSession.project_id == claim.project_id,
            UploadSession.item_id == claim.target_id,
        )
    )
    if lock:
        job_statement = job_statement.with_for_update()
        target_statement = target_statement.with_for_update()
    job = session.scalar(job_statement)
    row = session.execute(target_statement).one_or_none()
    if job is None or row is None:
        raise _failure("parser_failed")
    upload, parent = row
    if upload.completed_at is None or upload.abandoned_at is not None:
        raise _failure("parser_failed")
    return _ArchiveTarget(
        upload=upload,
        parent=parent,
        completed=job.status == IngestionJobStatus.COMPLETED,
    )


def _object_key(claim: ClaimedJob, upload_id: UUID, entry: _PreparedEntry) -> str:
    path_id = uuid5(upload_id, entry.plan.normalized_path)
    return (
        f"orgs/{claim.org_id}/projects/{claim.project_id}/uploads/{upload_id}/"
        f"zip-entries/{path_id}/{entry.sha256}"
    )


def _matches(stat_result: ObjectStat, entry: _PreparedEntry) -> bool:
    descriptor = entry.plan.media
    assert descriptor is not None
    content_type = (
        stat_result.content_type.partition(";")[0].strip().lower()
        if stat_result.content_type is not None
        else None
    )
    return (
        stat_result.size_bytes == entry.size_bytes
        and stat_result.checksum_sha256 == entry.sha256
        and content_type == descriptor.media_type
    )


def _put_entry(store: ObjectStore, entry: _PreparedEntry, object_key: str) -> bool:
    try:
        existing = store.stat(object_key=object_key)
    except ObjectNotFound:
        existing = None
    except ObjectStoreUnavailable:
        raise _failure("object_store_unavailable") from None
    if existing is not None:
        if not _matches(existing, entry):
            raise _failure("object_store_unavailable")
        return False
    descriptor = entry.plan.media
    assert descriptor is not None
    try:
        entry.source.seek(0)
        store.put_object(
            object_key=object_key,
            source=entry.source,
            size_bytes=entry.size_bytes,
            content_type=descriptor.media_type,
            checksum_sha256=entry.sha256,
        )
        return True
    except ObjectStoreUnavailable:
        try:
            raced = store.stat(object_key=object_key)
        except (ObjectNotFound, ObjectStoreUnavailable):
            raise _failure("object_store_unavailable") from None
        if not _matches(raced, entry):
            raise _failure("object_store_unavailable")
        return False


def _cleanup_object(
    session_factory: SessionFactory,
    store: ObjectStore,
    object_key: str,
    claim: ClaimedJob,
    now: datetime,
) -> None:
    try:
        with session_factory() as session, session.begin():
            job = session.scalar(
                select(IngestionJob)
                .where(
                    IngestionJob.id == claim.job_id,
                    IngestionJob.org_id == claim.org_id,
                    IngestionJob.project_id == claim.project_id,
                    IngestionJob.job_kind == claim.job_kind,
                    IngestionJob.target_id == claim.target_id,
                )
                .with_for_update()
            )
            attempt = session.scalar(
                select(IngestionJobAttempt)
                .where(
                    IngestionJobAttempt.id == claim.attempt_id,
                    IngestionJobAttempt.job_id == claim.job_id,
                    IngestionJobAttempt.org_id == claim.org_id,
                    IngestionJobAttempt.project_id == claim.project_id,
                )
                .with_for_update()
            )
            if (
                job is None
                or attempt is None
                or job.status != IngestionJobStatus.RUNNING
                or job.lease_owner != claim.lease_owner
                or job.lease_expires_at is None
                or job.lease_expires_at <= now
                or attempt.status != IngestionJobAttemptStatus.RUNNING
            ):
                return
            references = session.scalar(
                select(func.count(KnowledgeResourceVersion.id)).where(
                    KnowledgeResourceVersion.org_id == claim.org_id,
                    KnowledgeResourceVersion.project_id == claim.project_id,
                    KnowledgeResourceVersion.object_key == object_key,
                )
            )
            if int(references or 0) == 0:
                store.delete_object(object_key=object_key)
    except Exception:  # noqa: BLE001 -- rollback cleanup is deliberately best-effort.
        return


def _register_rollback_cleanup(
    context: WorkerContext,
    store: ObjectStore,
    object_key: str,
    claim: ClaimedJob,
) -> None:
    session = cast(Session, context.session)
    callbacks = session.info.setdefault("cairn_rollback_cleanup", [])
    callbacks.append(
        lambda: _cleanup_object(
            cast(SessionFactory, context.session_factory),
            store,
            object_key,
            claim,
            context.now(),
        )
    )


def _resource_and_version(
    session: Session,
    *,
    claim: ClaimedJob,
    upload: UploadSession,
    entry: _PreparedEntry,
) -> tuple[KnowledgeResource, KnowledgeResourceVersion]:
    source_id = str(upload.id)
    path = entry.plan.normalized_path
    resource = session.scalar(
        select(KnowledgeResource)
        .where(
            KnowledgeResource.org_id == claim.org_id,
            KnowledgeResource.project_id == claim.project_id,
            KnowledgeResource.source_type == ResourceSourceType.ZIP_ENTRY,
            KnowledgeResource.source_id == source_id,
            KnowledgeResource.external_id == path,
            KnowledgeResource.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if resource is None:
        resource = KnowledgeResource(
            org_id=claim.org_id,
            project_id=claim.project_id,
            title=PurePosixPath(path).name,
            source_type=ResourceSourceType.ZIP_ENTRY,
            source_id=source_id,
            external_id=path,
            created_by=None,
        )
        session.add(resource)
        session.flush()
    version = session.scalar(
        select(KnowledgeResourceVersion)
        .where(
            KnowledgeResourceVersion.org_id == claim.org_id,
            KnowledgeResourceVersion.project_id == claim.project_id,
            KnowledgeResourceVersion.source_type == ResourceSourceType.ZIP_ENTRY,
            KnowledgeResourceVersion.source_id == source_id,
            KnowledgeResourceVersion.external_id == path,
            KnowledgeResourceVersion.source_version == entry.sha256,
        )
        .with_for_update()
    )
    if version is None:
        descriptor = entry.plan.media
        assert descriptor is not None and entry.object_key is not None
        version = KnowledgeResourceVersion(
            org_id=claim.org_id,
            project_id=claim.project_id,
            resource_id=resource.id,
            source_type=ResourceSourceType.ZIP_ENTRY,
            source_id=source_id,
            external_id=path,
            source_version=entry.sha256,
            object_key=entry.object_key,
            media_type=descriptor.media_type,
            size_bytes=entry.size_bytes,
            sha256=entry.sha256,
            parser_profile=repository.PARSER_PROFILE,
            chunking_profile=repository.CHUNKING_PROFILE,
            status=ResourceVersionStatus.QUEUED,
        )
        session.add(version)
        session.flush()
    elif version.resource_id != resource.id or version.object_key != entry.object_key:
        raise _failure("parser_failed")
    return resource, version


def _publish(claim: ClaimedJob, context: WorkerContext, prepared: list[_PreparedEntry]) -> None:
    session = cast(Session, context.session)
    context.heartbeat.ensure_owned()
    target = _target(session, claim, lock=True)
    if target.completed:
        return
    now = context.now()
    existing_children = {
        item.normalized_path: item
        for item in session.scalars(
            select(IngestionItem)
            .where(
                IngestionItem.org_id == claim.org_id,
                IngestionItem.project_id == claim.project_id,
                IngestionItem.batch_id == target.parent.batch_id,
                IngestionItem.parent_item_id == target.parent.id,
            )
            .with_for_update()
        )
    }
    supported_count = 0
    failed_count = 0
    for entry in prepared:
        child = existing_children.get(entry.plan.normalized_path)
        if child is None:
            child = IngestionItem(
                org_id=claim.org_id,
                project_id=claim.project_id,
                batch_id=target.parent.batch_id,
                parent_item_id=target.parent.id,
                normalized_path=entry.plan.normalized_path,
                media_type=(
                    entry.plan.media.media_type
                    if entry.plan.media is not None
                    else "application/octet-stream"
                ),
                size_bytes=entry.size_bytes,
                sha256=entry.sha256,
            )
            session.add(child)
            session.flush()
            existing_children[entry.plan.normalized_path] = child
        elif child.sha256 != entry.sha256 or child.size_bytes != entry.size_bytes:
            raise _failure("parser_failed")
        if entry.plan.media is None:
            child.status = IngestionItemStatus.FAILED
            child.error_code = "unsupported_media_type"
            child.error_detail = safe_detail_for("unsupported_media_type")
            child.completed_at = now
            child.resource_id = None
            child.resource_version_id = None
            failed_count += 1
            continue
        resource, version = _resource_and_version(
            session, claim=claim, upload=target.upload, entry=entry
        )
        child.status = IngestionItemStatus.QUEUED
        child.error_code = None
        child.error_detail = None
        child.completed_at = None
        child.resource_id = resource.id
        child.resource_version_id = version.id
        existing_job = session.scalar(
            select(IngestionJob).where(
                IngestionJob.org_id == claim.org_id,
                IngestionJob.project_id == claim.project_id,
                IngestionJob.job_kind == JobKind.INDEX_RESOURCE_VERSION,
                IngestionJob.target_id == version.id,
                IngestionJob.profile_version == repository.INGESTION_PROFILE_VERSION,
            )
        )
        if existing_job is None:
            repository.create_ingestion_job(
                session,
                org_id=claim.org_id,
                project_id=claim.project_id,
                job_kind=JobKind.INDEX_RESOURCE_VERSION,
                target_id=version.id,
                next_attempt_at=now,
            )
        supported_count += 1
    target.parent.status = IngestionItemStatus.READY
    target.parent.error_code = None
    target.parent.error_detail = None
    target.parent.completed_at = now
    repository.refresh_batch_summary(
        session,
        org_id=claim.org_id,
        project_id=claim.project_id,
        batch_id=target.parent.batch_id,
        now=now,
    )
    details: dict[str, object] = {
        "projectId": str(claim.project_id),
        "batchId": str(target.parent.batch_id),
        "itemId": str(target.parent.id),
        "jobId": str(claim.job_id),
        "supportedCount": supported_count,
        "failedCount": failed_count,
    }
    add_audit_log(
        session,
        org_id=claim.org_id,
        actor_type="system",
        actor_id=None,
        action="knowledge.archive_expanded",
        resource_type="ingestion_job",
        resource_id=claim.job_id,
        trace_id=f"worker:{claim.attempt_id}",
        ip=None,
        user_agent=None,
        details=details,
    )
    repository.add_project_outbox_event(
        session,
        org_id=claim.org_id,
        project_id=claim.project_id,
        event_type="knowledge.archive_expanded",
        payload={**details, "status": IngestionJobStatus.COMPLETED.value},
    )
    finish_job(session, claim=claim, now=now)


def handle_expand_archive(claim: ClaimedJob, context: WorkerContext) -> None:
    if claim.job_kind != JobKind.EXPAND_ARCHIVE:
        raise _failure("parser_failed")
    session = cast(Session, context.session)
    target = _target(session, claim, lock=False)
    if target.completed:
        return
    context.heartbeat.ensure_owned()
    try:
        source_context = context.object_store.open_object(object_key=target.upload.object_key)
        with source_context as source:
            archive_source, size_bytes, checksum = _copy_archive(source)
    except ObjectNotFound:
        raise _failure("upload_object_missing") from None
    except ObjectStoreUnavailable:
        raise _failure("object_store_unavailable") from None
    if size_bytes != target.upload.size_bytes:
        archive_source.close()
        raise _failure("upload_size_mismatch")
    if checksum != target.upload.sha256:
        archive_source.close()
        raise _failure("upload_checksum_mismatch")
    prepared: list[_PreparedEntry] = []
    try:
        prepared = _prepare_entries(archive_source)
        for entry in prepared:
            context.heartbeat.ensure_owned()
            if entry.plan.media is None:
                continue
            object_key = _object_key(claim, target.upload.id, entry)
            entry.object_key = object_key
            if _put_entry(cast(ObjectStore, context.object_store), entry, object_key):
                _register_rollback_cleanup(
                    context,
                    cast(ObjectStore, context.object_store),
                    object_key,
                    claim,
                )
        _publish(claim, context, prepared)
    finally:
        for entry in prepared:
            entry.source.close()
        archive_source.close()


def build_archive_handler(
    *, object_store: Any, session_factory: Any, now: Now | None = None
) -> Callable[[Any, ClaimedJob, Any], None]:
    current_time = now or (lambda: datetime.now(UTC))

    def handler(session: Any, claim: ClaimedJob, heartbeat: Any) -> None:
        handle_expand_archive(
            claim,
            WorkerContext(
                session=session,
                session_factory=session_factory,
                heartbeat=heartbeat,
                object_store=object_store,
                now=current_time,
            ),
        )

    return handler


__all__ = [
    "ARCHIVE_ENTRY_LIMIT",
    "ARCHIVE_ENTRY_MAX_BYTES",
    "ARCHIVE_EXPANDED_MAX_BYTES",
    "MAX_COMPRESSION_RATIO",
    "ArchiveEntryPlan",
    "WorkerContext",
    "build_archive_handler",
    "handle_expand_archive",
    "inspect_archive",
]
