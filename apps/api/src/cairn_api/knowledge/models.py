from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base


class IngestionBatchStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class IngestionItemStatus(StrEnum):
    AWAITING_UPLOAD = "awaiting_upload"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ResourceVersionStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class IngestionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionJobAttemptStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EmbeddingProfileStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ResourceSourceType(StrEnum):
    UPLOAD = "upload"
    ZIP_ENTRY = "zip_entry"
    FEISHU = "feishu"
    TENCENT_DOCS = "tencent_docs"


class JobKind(StrEnum):
    EXPAND_ARCHIVE = "expand_archive"
    INDEX_RESOURCE_VERSION = "index_resource_version"


class JobAttemptTrigger(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


INGESTION_ERROR_CODES = frozenset(
    {
        "archive_duplicate_path",
        "archive_encrypted",
        "archive_limit_exceeded",
        "archive_nested",
        "archive_path_unsafe",
        "database_unavailable",
        "embedding_dimension_mismatch",
        "embedding_unavailable",
        "encrypted_pdf_unsupported",
        "file_too_large",
        "ingestion_retry_exhausted",
        "lease_lost",
        "no_extractable_text",
        "object_store_unavailable",
        "parser_failed",
        "unsupported_media_type",
        "upload_checksum_mismatch",
        "upload_expired",
        "upload_media_type_mismatch",
        "upload_object_missing",
        "upload_size_mismatch",
    }
)
_ERROR_CODE_VALUES_SQL = ",".join(f"'{code}'" for code in sorted(INGESTION_ERROR_CODES))


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        CheckConstraint(
            "status IN ('pending','processing','completed','completed_with_errors','failed')",
            name="status_values",
        ),
        CheckConstraint(
            "item_count >= 0 AND ready_count >= 0 AND failed_count >= 0",
            name="nonnegative_counts",
        ),
        CheckConstraint(
            "ready_count + failed_count <= item_count",
            name="count_bounds",
        ),
        CheckConstraint(
            "(status IN ('completed','completed_with_errors','failed') AND completed_at IS NOT NULL) "
            "OR (status IN ('pending','processing') AND completed_at IS NULL)",
            name="completion_state",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_ingestion_batches_org_id_project_id_created_at_id",
            "org_id",
            "project_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), default=IngestionBatchStatus.PENDING, server_default="pending"
    )
    item_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ready_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionItem(Base):
    __tablename__ = "ingestion_items"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        CheckConstraint(
            "status IN ('awaiting_upload','queued','processing','ready','failed')",
            name="status_values",
        ),
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="sha256_format",
        ),
        CheckConstraint("length(normalized_path) > 0", name="nonempty_path"),
        CheckConstraint(
            "(status = 'failed' AND error_code IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(status = 'ready' AND error_code IS NULL AND completed_at IS NOT NULL) OR "
            "(status IN ('awaiting_upload','queued','processing') AND error_code IS NULL "
            "AND completed_at IS NULL)",
            name="result_state",
        ),
        CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_ERROR_CODE_VALUES_SQL})",
            name="error_code_values",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "batch_id"],
            ["ingestion_batches.org_id", "ingestion_batches.project_id", "ingestion_batches.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "parent_item_id"],
            ["ingestion_items.org_id", "ingestion_items.project_id", "ingestion_items.id"],
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id"],
            [
                "knowledge_resources.org_id",
                "knowledge_resources.project_id",
                "knowledge_resources.id",
            ],
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id", "resource_version_id"],
            [
                "knowledge_resource_versions.org_id",
                "knowledge_resource_versions.project_id",
                "knowledge_resource_versions.resource_id",
                "knowledge_resource_versions.id",
            ],
        ),
        Index(
            "uq_ingestion_items_batch_parent_path",
            "org_id",
            "project_id",
            "batch_id",
            text("COALESCE(parent_item_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "normalized_path",
            unique=True,
        ),
        Index(
            "ix_ingestion_items_org_id_project_id_batch_id_status_id",
            "org_id",
            "project_id",
            "batch_id",
            "status",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    batch_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    parent_item_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    normalized_path: Mapped[str] = mapped_column(String(1024))
    media_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(24), default=IngestionItemStatus.AWAITING_UPLOAD, server_default="awaiting_upload"
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    resource_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeResource(Base):
    __tablename__ = "knowledge_resources"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        CheckConstraint(
            "source_type IN ('upload','zip_entry','feishu','tencent_docs')",
            name="source_type_values",
        ),
        CheckConstraint("length(title) > 0", name="nonempty_title"),
        CheckConstraint(
            "length(source_id) > 0 AND length(external_id) > 0", name="source_identity"
        ),
        CheckConstraint(
            "(deleted_at IS NULL AND deleted_by IS NULL) OR "
            "(deleted_at IS NOT NULL AND deleted_by IS NOT NULL)",
            name="deletion_actor",
        ),
        CheckConstraint(
            "purged_at IS NULL OR (deleted_at IS NOT NULL AND purged_at >= deleted_at)",
            name="purge_order",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "id", "current_version_id"],
            [
                "knowledge_resource_versions.org_id",
                "knowledge_resource_versions.project_id",
                "knowledge_resource_versions.resource_id",
                "knowledge_resource_versions.id",
            ],
            name="fk_knowledge_resources_current_version",
            use_alter=True,
        ),
        Index(
            "uq_knowledge_resources_active_source",
            "org_id",
            "project_id",
            "source_type",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_knowledge_resources_org_id_project_id_created_at_id",
            "org_id",
            "project_id",
            "created_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str] = mapped_column(String(1024))
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeResourceVersion(Base):
    __tablename__ = "knowledge_resource_versions"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        UniqueConstraint("org_id", "project_id", "resource_id", "id"),
        UniqueConstraint(
            "org_id",
            "source_type",
            "source_id",
            "external_id",
            "source_version",
            name="uq_knowledge_resource_versions_source_version",
        ),
        CheckConstraint(
            "source_type IN ('upload','zip_entry','feishu','tencent_docs')",
            name="source_type_values",
        ),
        CheckConstraint("status IN ('queued','processing','ready','failed')", name="status_values"),
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint(
            "(status = 'ready' AND error_code IS NULL AND ready_at IS NOT NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL AND ready_at IS NULL) OR "
            "(status IN ('queued','processing') AND error_code IS NULL AND ready_at IS NULL)",
            name="result_state",
        ),
        CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_ERROR_CODE_VALUES_SQL})",
            name="error_code_values",
        ),
        CheckConstraint(
            "processing_started_at IS NULL OR processing_started_at >= created_at",
            name="processing_order",
        ),
        CheckConstraint(
            "ready_at IS NULL OR "
            "(processing_started_at IS NOT NULL AND ready_at >= processing_started_at)",
            name="ready_order",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id"],
            [
                "knowledge_resources.org_id",
                "knowledge_resources.project_id",
                "knowledge_resources.id",
            ],
            ondelete="CASCADE",
        ),
        Index(
            "ix_knowledge_versions_project_resource_created",
            "org_id",
            "project_id",
            "resource_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    resource_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    source_type: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str] = mapped_column(String(1024))
    source_version: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(1024), unique=True)
    media_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    parser_profile: Mapped[str] = mapped_column(String(64))
    chunking_profile: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default=ResourceVersionStatus.QUEUED, server_default="queued"
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        UniqueConstraint("object_key"),
        UniqueConstraint("org_id", "project_id", "item_id"),
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint(
            "NOT (completed_at IS NOT NULL AND abandoned_at IS NOT NULL)",
            name="completion_state",
        ),
        CheckConstraint("expires_at > created_at", name="expiry_order"),
        ForeignKeyConstraint(
            ["org_id", "project_id", "batch_id"],
            ["ingestion_batches.org_id", "ingestion_batches.project_id", "ingestion_batches.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "item_id"],
            ["ingestion_items.org_id", "ingestion_items.project_id", "ingestion_items.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "resource_version_id"],
            [
                "knowledge_resource_versions.org_id",
                "knowledge_resource_versions.project_id",
                "knowledge_resource_versions.id",
            ],
        ),
        Index(
            "ix_upload_sessions_org_id_project_id_expires_at_id",
            "org_id",
            "project_id",
            "expires_at",
            "id",
            postgresql_where=text("completed_at IS NULL AND abandoned_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    batch_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    item_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    original_file_name: Mapped[str] = mapped_column(String(255))
    declared_media_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(1024))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resource_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )


class EmbeddingProfile(Base):
    __tablename__ = "embedding_profiles"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("scope_org_id", "id"),
        CheckConstraint("dimensions > 0", name="positive_dimensions"),
        CheckConstraint("distance_metric IN ('cosine')", name="distance_metric_values"),
        CheckConstraint("status IN ('active','inactive')", name="status_values"),
        CheckConstraint(
            "length(provider_key) > 0 AND length(model) > 0 AND length(version) > 0",
            name="nonempty_identity",
        ),
        Index(
            "uq_embedding_profiles_global_version",
            "version",
            unique=True,
            postgresql_where=text("org_id IS NULL"),
        ),
        Index(
            "uq_embedding_profiles_org_version",
            "org_id",
            "version",
            unique=True,
            postgresql_where=text("org_id IS NOT NULL"),
        ),
        Index(
            "uq_embedding_profiles_global_active",
            "status",
            unique=True,
            postgresql_where=text("org_id IS NULL AND status = 'active'"),
        ),
        Index(
            "uq_embedding_profiles_org_active",
            "org_id",
            unique=True,
            postgresql_where=text("org_id IS NOT NULL AND status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    scope_org_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        Computed(
            "COALESCE(org_id, '00000000-0000-0000-0000-000000000000'::uuid)",
            persisted=True,
        ),
    )
    provider_key: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    dimensions: Mapped[int] = mapped_column(Integer)
    distance_metric: Mapped[str] = mapped_column(
        String(16), default="cosine", server_default="cosine"
    )
    chunking_config: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    index_config: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default=EmbeddingProfileStatus.INACTIVE, server_default="inactive"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        UniqueConstraint(
            "job_kind",
            "target_id",
            "profile_version",
            name="uq_ingestion_jobs_kind_target_profile",
        ),
        CheckConstraint(
            "job_kind IN ('expand_archive','index_resource_version')", name="kind_values"
        ),
        CheckConstraint(
            "status IN ('queued','running','completed','failed')", name="status_values"
        ),
        CheckConstraint(
            "max_attempts > 0 AND attempt >= 0 AND attempt <= max_attempts", name="attempt_bounds"
        ),
        CheckConstraint(
            "(status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND heartbeat_at IS NOT NULL) OR "
            "(status <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND heartbeat_at IS NULL)",
            name="lease_state",
        ),
        CheckConstraint(
            "status <> 'running' OR lease_expires_at > heartbeat_at",
            name="lease_order",
        ),
        CheckConstraint(
            "(status IN ('completed','failed') AND completed_at IS NOT NULL) OR "
            "(status IN ('queued','running') AND completed_at IS NULL)",
            name="completion_state",
        ),
        CheckConstraint(
            f"last_error_code IS NULL OR last_error_code IN ({_ERROR_CODE_VALUES_SQL})",
            name="error_code_values",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_ingestion_jobs_claim",
            "status",
            "next_attempt_at",
            "created_at",
            "id",
        ),
        Index(
            "ix_ingestion_jobs_org_id_project_id_target_id",
            "org_id",
            "project_id",
            "target_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    job_kind: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    profile_version: Mapped[str] = mapped_column(
        String(64), default="default-v1", server_default="default-v1"
    )
    status: Mapped[str] = mapped_column(
        String(16), default=IngestionJobStatus.QUEUED, server_default="queued"
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionJobAttempt(Base):
    __tablename__ = "ingestion_job_attempts"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "id"),
        UniqueConstraint("job_id", "ordinal", name="uq_ingestion_job_attempts_job_ordinal"),
        CheckConstraint("ordinal > 0", name="positive_ordinal"),
        CheckConstraint("trigger IN ('automatic','manual')", name="trigger_values"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="status_values"
        ),
        CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND error_code IS NULL) OR "
            "(status = 'succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND error_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND error_code IS NOT NULL)",
            name="result_state",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= queued_at",
            name="start_order",
        ),
        CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name="completion_order",
        ),
        CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_ERROR_CODE_VALUES_SQL})",
            name="error_code_values",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "job_id"],
            ["ingestion_jobs.org_id", "ingestion_jobs.project_id", "ingestion_jobs.id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_ingestion_job_attempts_org_id_project_id_job_id_ordinal",
            "org_id",
            "project_id",
            "job_id",
            "ordinal",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    job_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    ordinal: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(
        String(16), default=IngestionJobAttemptStatus.QUEUED, server_default="queued"
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safe_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "resource_id", "resource_version_id", "id"),
        UniqueConstraint(
            "resource_version_id", "ordinal", name="uq_knowledge_chunks_version_ordinal"
        ),
        CheckConstraint("ordinal >= 0", name="nonnegative_ordinal"),
        CheckConstraint("length(text) > 0 AND length(normalized_text) > 0", name="nonempty_text"),
        ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id", "resource_version_id"],
            [
                "knowledge_resource_versions.org_id",
                "knowledge_resource_versions.project_id",
                "knowledge_resource_versions.resource_id",
                "knowledge_resource_versions.id",
            ],
            ondelete="CASCADE",
        ),
        Index("ix_knowledge_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_knowledge_chunks_normalized_text_trgm",
            "normalized_text",
            postgresql_using="gin",
            postgresql_ops={"normalized_text": "gin_trgm_ops"},
        ),
        Index(
            "ix_knowledge_chunks_project_version_ordinal",
            "org_id",
            "project_id",
            "resource_version_id",
            "ordinal",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    resource_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    resource_version_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict[str, object]] = mapped_column(JSONB)
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple'::regconfig, normalized_text)", persisted=True),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id", "embedding_profile_id", name="uq_chunk_embeddings_chunk_profile"
        ),
        CheckConstraint(
            "embedding_profile_scope_org_id = org_id OR "
            "embedding_profile_scope_org_id = "
            "'00000000-0000-0000-0000-000000000000'::uuid",
            name="profile_scope_values",
        ),
        ForeignKeyConstraint(
            ["embedding_profile_scope_org_id", "embedding_profile_id"],
            ["embedding_profiles.scope_org_id", "embedding_profiles.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "resource_id", "resource_version_id", "chunk_id"],
            [
                "knowledge_chunks.org_id",
                "knowledge_chunks.project_id",
                "knowledge_chunks.resource_id",
                "knowledge_chunks.resource_version_id",
                "knowledge_chunks.id",
            ],
            ondelete="CASCADE",
        ),
        Index(
            "ix_chunk_embeddings_org_id_project_id_profile_id",
            "org_id",
            "project_id",
            "embedding_profile_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    resource_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    resource_version_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    chunk_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    embedding_profile_scope_org_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    embedding_profile_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    embedding: Mapped[list[float]] = mapped_column(Vector())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchRateLimitBucket(Base):
    __tablename__ = "search_rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "subject_type",
            "subject_id",
            "window_started_at",
            name="uq_search_rate_limit_buckets_window",
        ),
        CheckConstraint("subject_type IN ('user','organization')", name="subject_type_values"),
        CheckConstraint("request_count >= 0", name="nonnegative_count"),
        CheckConstraint("window_expires_at > window_started_at", name="window_order"),
        Index("ix_search_rate_limit_buckets_expires_at", "window_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


__all__ = [
    "INGESTION_ERROR_CODES",
    "ChunkEmbedding",
    "EmbeddingProfile",
    "EmbeddingProfileStatus",
    "IngestionBatch",
    "IngestionBatchStatus",
    "IngestionItem",
    "IngestionItemStatus",
    "IngestionJob",
    "IngestionJobAttempt",
    "IngestionJobAttemptStatus",
    "IngestionJobStatus",
    "JobAttemptTrigger",
    "JobKind",
    "KnowledgeChunk",
    "KnowledgeResource",
    "KnowledgeResourceVersion",
    "ResourceSourceType",
    "ResourceVersionStatus",
    "SearchRateLimitBucket",
    "UploadSession",
]
