import os
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from cairn_api.knowledge.models import IngestionJob, JobKind
from cairn_api.organizations.models import Organization
from cairn_api.projects.models import Project
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def _validated_test_url() -> str:
    value = os.environ.get("CAIRN_TEST_DATABASE_URL")
    if not value:
        pytest.skip("CAIRN_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    parsed = make_url(value)
    if parsed.get_backend_name() != "postgresql" or parsed.get_driver_name() != "psycopg":
        pytest.fail("CAIRN_TEST_DATABASE_URL must use postgresql+psycopg")
    if parsed.database != "cairn_test":
        pytest.fail("integration tests require the database name cairn_test")
    return value


@pytest.fixture(scope="session")
def migrated_engine() -> Generator[Engine, None, None]:
    test_database_url = _validated_test_url()
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.upgrade(config, "head")
    engine = create_engine(test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_worker_facts(migrated_engine: Engine) -> Generator[None, None, None]:
    yield
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE chunk_embeddings, knowledge_chunks, embedding_profiles, "
                "ingestion_job_attempts, ingestion_jobs, upload_sessions, ingestion_items, "
                "knowledge_resource_versions, knowledge_resources, ingestion_batches, "
                "outbox_events, audit_logs, projects, organizations CASCADE"
            )
        )


def seed_job(
    engine: Engine,
    *,
    job_kind: JobKind = JobKind.INDEX_RESOURCE_VERSION,
    target_id: UUID | None = None,
    now: datetime | None = None,
) -> tuple[UUID, UUID, UUID]:
    job_id = uuid4()
    org_id = uuid4()
    project_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(Organization(id=org_id, slug=f"org-{org_id.hex[:10]}", name="Worker Org"))
        session.add(Project(id=project_id, org_id=org_id, name="Worker Project"))
        session.flush()
        session.add(
            IngestionJob(
                id=job_id,
                org_id=org_id,
                project_id=project_id,
                job_kind=job_kind,
                target_id=target_id or uuid4(),
                next_attempt_at=now or datetime.now(UTC),
            )
        )
    return job_id, org_id, project_id
