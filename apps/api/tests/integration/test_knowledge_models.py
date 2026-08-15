from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, MetaData, Table, insert, select
from sqlalchemy.exc import IntegrityError


def _tables(connection: Connection) -> dict[str, Table]:
    metadata = MetaData()
    return {
        name: Table(name, metadata, autoload_with=connection)
        for name in (
            "organizations",
            "users",
            "projects",
            "ingestion_batches",
            "ingestion_items",
            "knowledge_resources",
            "knowledge_resource_versions",
            "ingestion_jobs",
            "ingestion_job_attempts",
            "knowledge_chunks",
            "embedding_profiles",
            "chunk_embeddings",
        )
    }


def _seed_projects(
    connection: Connection, tables: dict[str, Table]
) -> tuple[UUID, UUID, UUID, UUID]:
    org_a = uuid4()
    org_b = uuid4()
    project_a = uuid4()
    project_b = uuid4()
    connection.execute(
        insert(tables["organizations"]),
        [
            {"id": org_a, "slug": f"knowledge-{org_a.hex}", "name": "Org A"},
            {"id": org_b, "slug": f"knowledge-{org_b.hex}", "name": "Org B"},
        ],
    )
    connection.execute(
        insert(tables["projects"]),
        [
            {"id": project_a, "org_id": org_a, "name": "Project A"},
            {"id": project_b, "org_id": org_b, "name": "Project B"},
        ],
    )
    return org_a, project_a, org_b, project_b


def _insert_resource_version(
    connection: Connection,
    tables: dict[str, Table],
    *,
    org_id: UUID,
    project_id: UUID,
    source_id: str,
) -> tuple[UUID, UUID]:
    resource_id = uuid4()
    version_id = uuid4()
    connection.execute(
        insert(tables["knowledge_resources"]),
        {
            "id": resource_id,
            "org_id": org_id,
            "project_id": project_id,
            "title": "Knowledge",
            "source_type": "upload",
            "source_id": source_id,
            "external_id": "document.txt",
        },
    )
    connection.execute(
        insert(tables["knowledge_resource_versions"]),
        {
            "id": version_id,
            "org_id": org_id,
            "project_id": project_id,
            "resource_id": resource_id,
            "source_type": "upload",
            "source_id": source_id,
            "external_id": "document.txt",
            "source_version": "a" * 64,
            "object_key": f"org/{org_id}/{source_id}/document.txt",
            "media_type": "text/plain",
            "size_bytes": 7,
            "sha256": "a" * 64,
            "parser_profile": "text-v1",
            "chunking_profile": "default-v1",
        },
    )
    return resource_id, version_id


@pytest.mark.integration
def test_batch_rejects_a_project_from_another_organization(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, _project_a, _org_b, project_b = _seed_projects(migrated_connection, tables)
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["ingestion_batches"]),
            {"id": uuid4(), "org_id": org_a, "project_id": project_b},
        )


@pytest.mark.integration
def test_item_rejects_a_batch_from_another_project(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, org_b, project_b = _seed_projects(migrated_connection, tables)
    batch_id = uuid4()
    migrated_connection.execute(
        insert(tables["ingestion_batches"]),
        {"id": batch_id, "org_id": org_a, "project_id": project_a},
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["ingestion_items"]),
            {
                "id": uuid4(),
                "org_id": org_b,
                "project_id": project_b,
                "batch_id": batch_id,
                "normalized_path": "document.txt",
                "media_type": "text/plain",
                "size_bytes": 7,
                "sha256": "a" * 64,
            },
        )


@pytest.mark.integration
def test_resource_current_version_rejects_cross_project_reference(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, org_b, project_b = _seed_projects(migrated_connection, tables)
    resource_a, _version_a = _insert_resource_version(
        migrated_connection,
        tables,
        org_id=org_a,
        project_id=project_a,
        source_id="upload-a",
    )
    _resource_b, version_b = _insert_resource_version(
        migrated_connection,
        tables,
        org_id=org_b,
        project_id=project_b,
        source_id="upload-b",
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            tables["knowledge_resources"]
            .update()
            .where(tables["knowledge_resources"].c.id == resource_a)
            .values(current_version_id=version_b)
        )


@pytest.mark.integration
def test_chunk_rejects_a_version_from_another_resource(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    resource_a, _version_a = _insert_resource_version(
        migrated_connection,
        tables,
        org_id=org_a,
        project_id=project_a,
        source_id="upload-a",
    )
    _resource_b, version_b = _insert_resource_version(
        migrated_connection,
        tables,
        org_id=org_a,
        project_id=project_a,
        source_id="upload-b",
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["knowledge_chunks"]),
            {
                "id": uuid4(),
                "org_id": org_a,
                "project_id": project_a,
                "resource_id": resource_a,
                "resource_version_id": version_b,
                "ordinal": 0,
                "kind": "text",
                "text": "wrong resource",
                "normalized_text": "wrong resource",
                "locator": {"type": "text", "lineStart": 1, "lineEnd": 1},
            },
        )


@pytest.mark.integration
def test_embedding_rejects_cross_tenant_chunk_identity(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, org_b, _project_b = _seed_projects(migrated_connection, tables)
    resource_a, version_a = _insert_resource_version(
        migrated_connection,
        tables,
        org_id=org_a,
        project_id=project_a,
        source_id="upload-a",
    )
    chunk_id = uuid4()
    migrated_connection.execute(
        insert(tables["knowledge_chunks"]),
        {
            "id": chunk_id,
            "org_id": org_a,
            "project_id": project_a,
            "resource_id": resource_a,
            "resource_version_id": version_a,
            "ordinal": 0,
            "kind": "text",
            "text": "content",
            "normalized_text": "content",
            "locator": {"type": "text", "lineStart": 1, "lineEnd": 1},
        },
    )
    profile_id = migrated_connection.execute(
        tables["embedding_profiles"]
        .insert()
        .values(
            id=uuid4(),
            org_id=org_b,
            provider_key="org-b",
            model="test",
            dimensions=3,
            distance_metric="cosine",
            chunking_config={},
            index_config={"strategy": "exact"},
            version="org-b-v1",
            status="active",
        )
        .returning(tables["embedding_profiles"].c.id)
    ).scalar_one()
    values = {
        "id": uuid4(),
        "org_id": org_a,
        "project_id": project_a,
        "resource_id": resource_a,
        "resource_version_id": version_a,
        "chunk_id": chunk_id,
        "embedding_profile_id": profile_id,
        "embedding": [0.1, 0.2, 0.3],
    }
    if "embedding_profile_scope_org_id" in tables["chunk_embeddings"].c:
        values["embedding_profile_scope_org_id"] = org_a
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["chunk_embeddings"]),
            values,
        )

    migrated_connection.execute(
        insert(tables["chunk_embeddings"]),
        {
            **values,
            "id": uuid4(),
            "embedding_profile_scope_org_id": UUID(int=0),
            "embedding_profile_id": UUID("00000000-0000-4000-8000-000000000501"),
        },
    )


@pytest.mark.integration
def test_source_version_idempotency_rejects_duplicate_resource_version(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    _insert_resource_version(
        migrated_connection,
        tables,
        org_id=org_a,
        project_id=project_a,
        source_id="same-upload",
    )
    resource_id = uuid4()
    migrated_connection.execute(
        insert(tables["knowledge_resources"]),
        {
            "id": resource_id,
            "org_id": org_a,
            "project_id": project_a,
            "title": "Replacement",
            "source_type": "upload",
            "source_id": "replacement-resource",
            "external_id": "replacement.txt",
        },
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["knowledge_resource_versions"]),
            {
                "id": uuid4(),
                "org_id": org_a,
                "project_id": project_a,
                "resource_id": resource_id,
                "source_type": "upload",
                "source_id": "same-upload",
                "external_id": "document.txt",
                "source_version": "a" * 64,
                "object_key": "replacement/object",
                "media_type": "text/plain",
                "size_bytes": 7,
                "sha256": "a" * 64,
                "parser_profile": "text-v1",
                "chunking_profile": "default-v1",
            },
        )


@pytest.mark.integration
def test_source_version_idempotency_rejects_same_source_across_projects(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    project_b = uuid4()
    migrated_connection.execute(
        insert(tables["projects"]),
        {"id": project_b, "org_id": org_a, "name": "Project B in Org A"},
    )
    _insert_resource_version(
        migrated_connection,
        tables,
        org_id=org_a,
        project_id=project_a,
        source_id="shared-source",
    )
    resource_b = uuid4()
    migrated_connection.execute(
        insert(tables["knowledge_resources"]),
        {
            "id": resource_b,
            "org_id": org_a,
            "project_id": project_b,
            "title": "Same source in another project",
            "source_type": "upload",
            "source_id": "shared-source-resource-b",
            "external_id": "document.txt",
        },
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["knowledge_resource_versions"]),
            {
                "id": uuid4(),
                "org_id": org_a,
                "project_id": project_b,
                "resource_id": resource_b,
                "source_type": "upload",
                "source_id": "shared-source",
                "external_id": "document.txt",
                "source_version": "a" * 64,
                "object_key": f"org/{org_a}/shared-source/project-b",
                "media_type": "text/plain",
                "size_bytes": 7,
                "sha256": "a" * 64,
                "parser_profile": "text-v1",
                "chunking_profile": "default-v1",
            },
        )


@pytest.mark.integration
def test_unknown_ingestion_error_codes_are_rejected_everywhere(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    batch_id = uuid4()
    migrated_connection.execute(
        insert(tables["ingestion_batches"]),
        {"id": batch_id, "org_id": org_a, "project_id": project_a},
    )
    resource_id = uuid4()
    migrated_connection.execute(
        insert(tables["knowledge_resources"]),
        {
            "id": resource_id,
            "org_id": org_a,
            "project_id": project_a,
            "title": "Invalid errors",
            "source_type": "upload",
            "source_id": "invalid-errors",
            "external_id": "document.txt",
        },
    )
    job_id = uuid4()
    migrated_connection.execute(
        insert(tables["ingestion_jobs"]),
        {
            "id": job_id,
            "org_id": org_a,
            "project_id": project_a,
            "job_kind": "index_resource_version",
            "target_id": uuid4(),
        },
    )
    invalid_rows = (
        (
            "ingestion_items",
            {
                "id": uuid4(),
                "org_id": org_a,
                "project_id": project_a,
                "batch_id": batch_id,
                "normalized_path": "invalid.txt",
                "media_type": "text/plain",
                "size_bytes": 7,
                "sha256": "a" * 64,
                "status": "failed",
                "error_code": "embeding_unavailable",
                "completed_at": datetime.now(UTC),
            },
        ),
        (
            "knowledge_resource_versions",
            {
                "id": uuid4(),
                "org_id": org_a,
                "project_id": project_a,
                "resource_id": resource_id,
                "source_type": "upload",
                "source_id": "invalid-version-error",
                "external_id": "document.txt",
                "source_version": "b" * 64,
                "object_key": f"org/{org_a}/invalid-version-error",
                "media_type": "text/plain",
                "size_bytes": 7,
                "sha256": "b" * 64,
                "parser_profile": "text-v1",
                "chunking_profile": "default-v1",
                "status": "failed",
                "error_code": "embeding_unavailable",
            },
        ),
        (
            "ingestion_job_attempts",
            {
                "id": uuid4(),
                "org_id": org_a,
                "project_id": project_a,
                "job_id": job_id,
                "ordinal": 1,
                "trigger": "automatic",
                "status": "failed",
                "error_code": "embeding_unavailable",
                "started_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
            },
        ),
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            tables["ingestion_jobs"]
            .update()
            .where(tables["ingestion_jobs"].c.id == job_id)
            .values(last_error_code="embeding_unavailable")
        )
    for table_name, values in invalid_rows:
        with pytest.raises(IntegrityError), migrated_connection.begin_nested():
            migrated_connection.execute(insert(tables[table_name]), values)


@pytest.mark.integration
def test_lease_and_attempt_timestamps_must_move_forward(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    now = datetime.now(UTC)
    job_id = uuid4()
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["ingestion_jobs"]),
            {
                "id": job_id,
                "org_id": org_a,
                "project_id": project_a,
                "job_kind": "index_resource_version",
                "target_id": uuid4(),
                "status": "running",
                "lease_owner": "worker-a",
                "heartbeat_at": now,
                "lease_expires_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
        )

    job_id = uuid4()
    migrated_connection.execute(
        insert(tables["ingestion_jobs"]),
        {
            "id": job_id,
            "org_id": org_a,
            "project_id": project_a,
            "job_kind": "index_resource_version",
            "target_id": uuid4(),
        },
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["ingestion_job_attempts"]),
            {
                "id": uuid4(),
                "org_id": org_a,
                "project_id": project_a,
                "job_id": job_id,
                "ordinal": 1,
                "trigger": "automatic",
                "status": "failed",
                "queued_at": now,
                "started_at": datetime(2026, 1, 2, tzinfo=UTC),
                "completed_at": datetime(2026, 1, 1, tzinfo=UTC),
                "error_code": "parser_failed",
            },
        )


@pytest.mark.integration
def test_ready_version_timestamp_must_follow_processing(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    resource_id = uuid4()
    migrated_connection.execute(
        insert(tables["knowledge_resources"]),
        {
            "id": resource_id,
            "org_id": org_a,
            "project_id": project_a,
            "title": "Invalid ready time",
            "source_type": "upload",
            "source_id": "invalid-ready-time-resource",
            "external_id": "document.txt",
        },
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(tables["knowledge_resource_versions"]),
            {
                "id": uuid4(),
                "org_id": org_a,
                "project_id": project_a,
                "resource_id": resource_id,
                "source_type": "upload",
                "source_id": "invalid-ready-time",
                "external_id": "document.txt",
                "source_version": "c" * 64,
                "object_key": f"org/{org_a}/invalid-ready-time",
                "media_type": "text/plain",
                "size_bytes": 7,
                "sha256": "c" * 64,
                "parser_profile": "text-v1",
                "chunking_profile": "default-v1",
                "status": "ready",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "processing_started_at": datetime(2026, 1, 3, tzinfo=UTC),
                "ready_at": datetime(2026, 1, 2, tzinfo=UTC),
            },
        )


@pytest.mark.integration
def test_job_attempt_history_rejects_direct_delete_but_allows_job_cascade(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    job_id = uuid4()
    attempt_id = uuid4()
    migrated_connection.execute(
        insert(tables["ingestion_jobs"]),
        {
            "id": job_id,
            "org_id": org_a,
            "project_id": project_a,
            "job_kind": "index_resource_version",
            "target_id": uuid4(),
        },
    )
    migrated_connection.execute(
        insert(tables["ingestion_job_attempts"]),
        {
            "id": attempt_id,
            "org_id": org_a,
            "project_id": project_a,
            "job_id": job_id,
            "ordinal": 1,
            "trigger": "automatic",
        },
    )

    now = datetime.now(UTC)
    migrated_connection.execute(
        tables["ingestion_job_attempts"]
        .update()
        .where(tables["ingestion_job_attempts"].c.id == attempt_id)
        .values(status="running", started_at=now)
    )
    migrated_connection.execute(
        tables["ingestion_job_attempts"]
        .update()
        .where(tables["ingestion_job_attempts"].c.id == attempt_id)
        .values(status="succeeded", completed_at=now)
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            tables["ingestion_job_attempts"]
            .update()
            .where(tables["ingestion_job_attempts"].c.id == attempt_id)
            .values(status="queued", started_at=None, completed_at=None)
        )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            tables["ingestion_job_attempts"]
            .delete()
            .where(tables["ingestion_job_attempts"].c.id == attempt_id)
        )

    migrated_connection.execute(
        tables["ingestion_jobs"].delete().where(tables["ingestion_jobs"].c.id == job_id)
    )
    assert (
        migrated_connection.scalar(
            select(tables["ingestion_job_attempts"].c.id).where(
                tables["ingestion_job_attempts"].c.id == attempt_id
            )
        )
        is None
    )


@pytest.mark.integration
def test_batch_summary_is_derived_from_items_even_when_caller_lies(
    migrated_connection: Connection,
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    batch_id = uuid4()
    migrated_connection.execute(
        insert(tables["ingestion_batches"]),
        {
            "id": batch_id,
            "org_id": org_a,
            "project_id": project_a,
            "status": "failed",
            "item_count": 1,
            "failed_count": 1,
            "completed_at": datetime.now(UTC),
        },
    )
    batch = migrated_connection.execute(
        select(tables["ingestion_batches"]).where(tables["ingestion_batches"].c.id == batch_id)
    ).one()
    assert (batch.status, batch.item_count, batch.ready_count, batch.failed_count) == (
        "pending",
        0,
        0,
        0,
    )
    assert batch.completed_at is None

    item_id = uuid4()
    migrated_connection.execute(
        insert(tables["ingestion_items"]),
        {
            "id": item_id,
            "org_id": org_a,
            "project_id": project_a,
            "batch_id": batch_id,
            "normalized_path": "failed.txt",
            "media_type": "text/plain",
            "size_bytes": 7,
            "sha256": "a" * 64,
            "status": "failed",
            "error_code": "parser_failed",
            "completed_at": datetime.now(UTC),
        },
    )
    failed_batch = migrated_connection.execute(
        select(tables["ingestion_batches"]).where(tables["ingestion_batches"].c.id == batch_id)
    ).one()
    assert (
        failed_batch.status,
        failed_batch.item_count,
        failed_batch.ready_count,
        failed_batch.failed_count,
    ) == ("failed", 1, 0, 1)
    assert failed_batch.completed_at is not None

    migrated_connection.execute(
        tables["ingestion_items"]
        .update()
        .where(tables["ingestion_items"].c.id == item_id)
        .values(status="ready", error_code=None)
    )
    ready_batch = migrated_connection.execute(
        select(tables["ingestion_batches"]).where(tables["ingestion_batches"].c.id == batch_id)
    ).one()
    assert (
        ready_batch.status,
        ready_batch.item_count,
        ready_batch.ready_count,
        ready_batch.failed_count,
    ) == ("completed", 1, 1, 0)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("table_name", "values"),
    [
        (
            "knowledge_resources",
            {"deleted_at": datetime(2026, 8, 12, tzinfo=UTC), "deleted_by": None},
        ),
    ],
)
def test_state_constraints_reject_internally_inconsistent_rows(
    migrated_connection: Connection,
    table_name: str,
    values: dict[str, object],
) -> None:
    tables = _tables(migrated_connection)
    org_a, project_a, _org_b, _project_b = _seed_projects(migrated_connection, tables)
    if table_name == "ingestion_batches":
        row = {"id": uuid4(), "org_id": org_a, "project_id": project_a, **values}
    else:
        row = {
            "id": uuid4(),
            "org_id": org_a,
            "project_id": project_a,
            "title": "Invalid deletion",
            "source_type": "upload",
            "source_id": "invalid-deletion",
            "external_id": "document.txt",
            **values,
        }
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(insert(tables[table_name]), row)
