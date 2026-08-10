from datetime import UTC, datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from cairn_api.organizations.models import Organization
from sqlalchemy import (
    Connection,
    Engine,
    MetaData,
    Table,
    create_engine,
    delete,
    func,
    insert,
    inspect,
    select,
)
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
def test_acl_migration_creates_normalized_active_grant_contract(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    columns = {
        column["name"]
        for column in inspector.get_columns("resource_acl_entries")
    }
    assert columns == {
        "id",
        "org_id",
        "resource_type",
        "resource_id",
        "principal_type",
        "principal_id",
        "permission",
        "granted_by_type",
        "granted_by_id",
        "granted_at",
        "revoked_by_type",
        "revoked_by_id",
        "revoked_at",
    }
    checks = {
        item["name"]
        for item in inspector.get_check_constraints("resource_acl_entries")
    }
    assert checks >= {
        "ck_resource_acl_entries_resource_type",
        "ck_resource_acl_entries_principal_type",
        "ck_resource_acl_entries_permission",
        "ck_resource_acl_entries_principal_id_nonempty",
        "ck_resource_acl_entries_granted_actor",
        "ck_resource_acl_entries_revoked_actor",
    }
    foreign_keys = {
        item["name"]: item
        for item in inspector.get_foreign_keys("resource_acl_entries")
    }
    assert set(foreign_keys) == {
        "fk_resource_acl_entries_org_id_organizations",
        "fk_resource_acl_entries_granted_by_id_users",
        "fk_resource_acl_entries_revoked_by_id_users",
    }
    for name, constrained_columns, referred_table, ondelete in (
        (
            "fk_resource_acl_entries_org_id_organizations",
            ["org_id"],
            "organizations",
            "CASCADE",
        ),
        (
            "fk_resource_acl_entries_granted_by_id_users",
            ["granted_by_id"],
            "users",
            None,
        ),
        (
            "fk_resource_acl_entries_revoked_by_id_users",
            ["revoked_by_id"],
            "users",
            None,
        ),
    ):
        foreign_key = foreign_keys[name]
        assert foreign_key["constrained_columns"] == constrained_columns
        assert foreign_key["referred_table"] == referred_table
        assert foreign_key["referred_columns"] == ["id"]
        assert foreign_key.get("options", {}).get("ondelete") == ondelete
    indexes = {
        item["name"]: item
        for item in inspector.get_indexes("resource_acl_entries")
    }
    assert set(indexes) == {
        "uq_resource_acl_entries_active_principal",
        "ix_resource_acl_entries_org_resource_active",
        "ix_resource_acl_entries_org_principal_active",
        "ix_resource_acl_entries_org_resource_granted",
    }
    assert indexes["uq_resource_acl_entries_active_principal"]["column_names"] == [
        "org_id",
        "resource_type",
        "resource_id",
        "principal_type",
        "principal_id",
    ]
    assert indexes["uq_resource_acl_entries_active_principal"]["unique"] is True
    assert indexes["ix_resource_acl_entries_org_resource_active"]["column_names"] == [
        "org_id",
        "resource_type",
        "resource_id",
        "granted_at",
        "id",
    ]
    assert indexes["ix_resource_acl_entries_org_principal_active"]["column_names"] == [
        "org_id",
        "principal_type",
        "principal_id",
        "resource_type",
        "resource_id",
    ]
    assert indexes["ix_resource_acl_entries_org_resource_granted"]["column_names"] == [
        "org_id",
        "resource_type",
        "resource_id",
        "granted_at",
        "id",
    ]
    for name in (
        "uq_resource_acl_entries_active_principal",
        "ix_resource_acl_entries_org_resource_active",
        "ix_resource_acl_entries_org_principal_active",
    ):
        assert "revoked_at IS NULL" in str(
            indexes[name].get("dialect_options", {}).get("postgresql_where")
        )


@pytest.mark.integration
def test_acl_database_preserves_revoked_history_but_rejects_duplicate_active_grants(
    migrated_connection: Connection,
) -> None:
    acl = Table("resource_acl_entries", MetaData(), autoload_with=migrated_connection)
    organizations = Table("organizations", MetaData(), autoload_with=migrated_connection)
    projects = Table("projects", MetaData(), autoload_with=migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000009102")
    project_id = UUID("00000000-0000-4000-8000-000000009202")
    principal_id = "00000000-0000-4000-8000-000000009302"
    identity = {
        "org_id": org_id,
        "resource_type": "project",
        "resource_id": project_id,
        "principal_type": "user",
        "principal_id": principal_id,
    }
    migrated_connection.execute(
        insert(organizations),
        {"id": org_id, "slug": "acl-history", "name": "ACL History"},
    )
    migrated_connection.execute(
        insert(projects),
        {"id": project_id, "org_id": org_id, "name": "ACL History"},
    )
    migrated_connection.execute(
        insert(acl),
        {
            "id": UUID("00000000-0000-4000-8000-000000009402"),
            **identity,
            "permission": "read",
            "granted_by_type": "system",
        },
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(acl),
            {
                "id": UUID("00000000-0000-4000-8000-000000009403"),
                **identity,
                "permission": "write",
                "granted_by_type": "system",
            },
        )

    migrated_connection.execute(
        insert(acl),
        {
            "id": UUID("00000000-0000-4000-8000-000000009404"),
            **identity,
            "permission": "write",
            "granted_by_type": "system",
            "revoked_by_type": "system",
            "revoked_at": datetime.now(UTC),
        },
    )
    assert migrated_connection.scalar(
        select(func.count()).select_from(acl).where(acl.c.resource_id == project_id)
    ) == 2


@pytest.mark.integration
def test_acl_rows_are_deleted_when_their_organization_is_deleted(
    migrated_connection: Connection,
) -> None:
    acl = Table("resource_acl_entries", MetaData(), autoload_with=migrated_connection)
    organizations = Table("organizations", MetaData(), autoload_with=migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000009104")
    acl_id = UUID("00000000-0000-4000-8000-000000009406")
    migrated_connection.execute(
        insert(organizations),
        {"id": org_id, "slug": "acl-cascade", "name": "ACL Cascade"},
    )
    migrated_connection.execute(
        insert(acl),
        {
            "id": acl_id,
            "org_id": org_id,
            "resource_type": "project",
            "resource_id": UUID("00000000-0000-4000-8000-000000009204"),
            "principal_type": "org",
            "principal_id": str(org_id),
            "permission": "read",
            "granted_by_type": "system",
        },
    )

    migrated_connection.execute(delete(organizations).where(organizations.c.id == org_id))

    assert migrated_connection.scalar(
        select(func.count()).select_from(acl).where(acl.c.id == acl_id)
    ) == 0


@pytest.mark.integration
@pytest.mark.parametrize(
    ("actor_location", "expected_constraint"),
    [
        ("grant", "fk_resource_acl_entries_granted_by_id_users"),
        ("revocation", "fk_resource_acl_entries_revoked_by_id_users"),
    ],
)
def test_acl_database_rejects_unknown_user_actor_uuids(
    migrated_connection: Connection,
    actor_location: str,
    expected_constraint: str,
) -> None:
    acl = Table("resource_acl_entries", MetaData(), autoload_with=migrated_connection)
    organizations = Table("organizations", MetaData(), autoload_with=migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000009105")
    unknown_user_id = UUID("00000000-0000-4000-8000-000000009502")
    values: dict[str, object] = {
        "id": UUID("00000000-0000-4000-8000-000000009407"),
        "org_id": org_id,
        "resource_type": "project",
        "resource_id": UUID("00000000-0000-4000-8000-000000009205"),
        "principal_type": "org",
        "principal_id": str(org_id),
        "permission": "read",
        "granted_by_type": "system",
    }
    if actor_location == "grant":
        values.update(
            granted_by_type="user",
            granted_by_id=unknown_user_id,
        )
    else:
        values.update(
            revoked_by_type="user",
            revoked_by_id=unknown_user_id,
            revoked_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
    migrated_connection.execute(
        insert(organizations),
        {"id": org_id, "slug": "acl-unknown-actor", "name": "Unknown Actor"},
    )

    with pytest.raises(IntegrityError) as exc_info, migrated_connection.begin_nested():
        migrated_connection.execute(insert(acl), values)

    assert expected_constraint in str(exc_info.value.orig)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("granted_by_type", "granted_by_id"),
    [
        ("system", UUID("00000000-0000-4000-8000-000000009501")),
        ("user", None),
    ],
)
def test_acl_database_rejects_invalid_grant_actor_shapes(
    migrated_connection: Connection,
    granted_by_type: str,
    granted_by_id: UUID | None,
) -> None:
    acl = Table("resource_acl_entries", MetaData(), autoload_with=migrated_connection)
    organizations = Table("organizations", MetaData(), autoload_with=migrated_connection)
    users = Table("users", MetaData(), autoload_with=migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000009103")
    migrated_connection.execute(
        insert(organizations),
        {"id": org_id, "slug": "acl-actor", "name": "ACL Actor"},
    )
    migrated_connection.execute(
        insert(users),
        {
            "id": UUID("00000000-0000-4000-8000-000000009501"),
            "email": "acl-actor@example.com",
            "normalized_email": "acl-actor@example.com",
            "password_hash": "not-used-by-this-constraint-test",
            "is_active": True,
        },
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(acl),
            {
                "id": UUID("00000000-0000-4000-8000-000000009405"),
                "org_id": org_id,
                "resource_type": "project",
                "resource_id": UUID("00000000-0000-4000-8000-000000009203"),
                "principal_type": "org",
                "principal_id": str(org_id),
                "permission": "read",
                "granted_by_type": granted_by_type,
                "granted_by_id": granted_by_id,
            },
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("revoked_at", "revoked_by_type", "revoked_by_id"),
    [
        (None, "user", UUID("00000000-0000-4000-8000-000000009503")),
        (datetime(2026, 8, 10, tzinfo=UTC), None, None),
        (datetime(2026, 8, 10, tzinfo=UTC), "user", None),
        (
            datetime(2026, 8, 10, tzinfo=UTC),
            "system",
            UUID("00000000-0000-4000-8000-000000009503"),
        ),
    ],
)
def test_acl_database_rejects_invalid_revoked_actor_shapes(
    migrated_connection: Connection,
    revoked_at: datetime | None,
    revoked_by_type: str | None,
    revoked_by_id: UUID | None,
) -> None:
    acl = Table("resource_acl_entries", MetaData(), autoload_with=migrated_connection)
    organizations = Table("organizations", MetaData(), autoload_with=migrated_connection)
    users = Table("users", MetaData(), autoload_with=migrated_connection)
    org_id = UUID("00000000-0000-4000-8000-000000009106")
    actor_id = UUID("00000000-0000-4000-8000-000000009503")
    migrated_connection.execute(
        insert(organizations),
        {"id": org_id, "slug": "acl-revoked-actor", "name": "Revoked Actor"},
    )
    migrated_connection.execute(
        insert(users),
        {
            "id": actor_id,
            "email": "acl-revoked-actor@example.com",
            "normalized_email": "acl-revoked-actor@example.com",
            "password_hash": "not-used-by-this-constraint-test",
            "is_active": True,
        },
    )

    with pytest.raises(IntegrityError) as exc_info, migrated_connection.begin_nested():
        migrated_connection.execute(
            insert(acl),
            {
                "id": UUID("00000000-0000-4000-8000-000000009408"),
                "org_id": org_id,
                "resource_type": "project",
                "resource_id": UUID("00000000-0000-4000-8000-000000009206"),
                "principal_type": "org",
                "principal_id": str(org_id),
                "permission": "read",
                "granted_by_type": "system",
                "revoked_at": revoked_at,
                "revoked_by_type": revoked_by_type,
                "revoked_by_id": revoked_by_id,
            },
        )

    assert "ck_resource_acl_entries_revoked_actor" in str(exc_info.value.orig)


@pytest.mark.integration
def test_acl_migration_backfills_existing_projects_as_system_org_read(
    test_database_url: str,
) -> None:
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    engine = create_engine(test_database_url, pool_pre_ping=True)
    org_id = UUID("00000000-0000-4000-8000-000000009101")
    project_id = UUID("00000000-0000-4000-8000-000000009201")
    try:
        command.downgrade(config, "0003_project_task_graph")
        metadata = MetaData()
        organizations = Table("organizations", metadata, autoload_with=engine)
        projects = Table("projects", metadata, autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                insert(organizations),
                {"id": org_id, "slug": "acl-backfill", "name": "ACL Backfill"},
            )
            connection.execute(
                insert(projects),
                {"id": project_id, "org_id": org_id, "name": "Existing Project"},
            )
        command.upgrade(config, "head")
        acl = Table("resource_acl_entries", MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            row = connection.execute(
                select(acl).where(acl.c.resource_id == project_id)
            ).one()
        assert row.org_id == org_id
        assert row.resource_type == "project"
        assert row.principal_type == "org"
        assert row.principal_id == str(org_id)
        assert row.permission == "read"
        assert row.granted_by_type == "system"
        assert row.granted_by_id is None
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(delete(Organization).where(Organization.id == org_id))
        engine.dispose()
