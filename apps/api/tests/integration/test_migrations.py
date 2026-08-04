from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cairn_api.audit.models import AuditLog
from cairn_api.auth.models import AuthSession, User
from cairn_api.organizations.models import Organization
from sqlalchemy import Connection, Engine, delete, insert, inspect, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError


@pytest.mark.integration
def test_identity_migration_creates_expected_tables(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    assert set(inspector.get_table_names()) >= {
        "organizations",
        "users",
        "memberships",
        "auth_sessions",
        "audit_logs",
    }
    assert {column["name"] for column in inspector.get_columns("users")} >= {
        "id",
        "email",
        "normalized_email",
        "display_name",
        "password_hash",
        "is_active",
        "created_at",
    }


@pytest.mark.integration
def test_identity_constraints_and_tenant_indexes(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)

    organization_constraints = inspector.get_unique_constraints("organizations")
    assert any(item["column_names"] == ["slug"] for item in organization_constraints)
    user_constraints = inspector.get_unique_constraints("users")
    assert any(item["column_names"] == ["normalized_email"] for item in user_constraints)
    membership_constraints = inspector.get_unique_constraints("memberships")
    assert any(item["column_names"] == ["org_id", "user_id"] for item in membership_constraints)

    for table in ("memberships", "auth_sessions", "audit_logs"):
        for index in inspector.get_indexes(table):
            columns = index["column_names"]
            if table == "auth_sessions" and columns == ["token_digest"]:
                continue
            assert columns and columns[0] == "org_id"


@pytest.mark.integration
def test_organization_slug_constraint_rejects_invalid_values(migrated_connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        migrated_connection.execute(
            insert(Organization),
            {"id": uuid4(), "slug": "Not A Slug", "name": "Invalid"},
        )


@pytest.mark.integration
def test_session_requires_real_membership(migrated_connection: Connection) -> None:
    org_id = uuid4()
    user_id = uuid4()
    migrated_connection.execute(
        insert(Organization),
        {"id": org_id, "slug": "no-member", "name": "No Member"},
    )
    migrated_connection.execute(
        insert(User),
        {
            "id": user_id,
            "email": "no-member@example.com",
            "normalized_email": "no-member@example.com",
            "password_hash": "not-used-by-this-constraint-test",
            "is_active": True,
        },
    )
    with pytest.raises(IntegrityError):
        migrated_connection.execute(
            insert(AuthSession),
            {
                "id": uuid4(),
                "org_id": org_id,
                "user_id": user_id,
                "token_digest": b"t" * 32,
                "csrf_digest": b"c" * 32,
                "expires_at": datetime.now(UTC) + timedelta(days=7),
            },
        )


@pytest.mark.integration
def test_audit_rows_reject_update_and_delete(migrated_engine: Engine) -> None:
    audit_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(AuditLog),
            {
                "id": audit_id,
                "actor_type": "anonymous",
                "action": "auth.login_failed",
                "resource_type": "session",
                "trace_id": "req-audit-trigger",
                "details": {},
            },
        )

    for statement in (
        update(AuditLog).where(AuditLog.id == audit_id).values(action="changed"),
        delete(AuditLog).where(AuditLog.id == audit_id),
    ):
        with migrated_engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(DBAPIError):
                connection.execute(statement)
            transaction.rollback()


@pytest.mark.integration
def test_audit_insert_maps_metadata_column_to_details(migrated_engine: Engine) -> None:
    audit_id = uuid4()
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(AuditLog),
            {
                "id": audit_id,
                "actor_type": "anonymous",
                "action": "auth.login_failed",
                "resource_type": "session",
                "trace_id": "req-details",
                "details": {"reason": "unknown_user"},
            },
        )
        details = connection.scalar(select(AuditLog.details).where(AuditLog.id == audit_id))
    assert details == {"reason": "unknown_user"}
