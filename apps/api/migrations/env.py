from logging.config import fileConfig

from alembic import context
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession, User
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.db.base import Base
from cairn_api.knowledge.models import (
    ChunkEmbedding,
    EmbeddingProfile,
    IngestionBatch,
    IngestionItem,
    IngestionJob,
    IngestionJobAttempt,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    SearchRateLimitBucket,
    UploadSession,
)
from cairn_api.organizations.models import Membership, Organization
from cairn_api.projects.models import (
    Milestone,
    OutboxEvent,
    Project,
    ProjectStage,
    Task,
    TaskDependency,
)
from cairn_api.settings import Settings
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", Settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata
_MAPPED_TYPES = (
    AuditLog,
    AuthSession,
    ChunkEmbedding,
    EmbeddingProfile,
    IngestionBatch,
    IngestionItem,
    IngestionJob,
    IngestionJobAttempt,
    KnowledgeChunk,
    KnowledgeResource,
    KnowledgeResourceVersion,
    Membership,
    Milestone,
    Organization,
    OutboxEvent,
    Project,
    ProjectStage,
    ResourceAclEntry,
    SearchRateLimitBucket,
    Task,
    TaskDependency,
    User,
    UploadSession,
)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
