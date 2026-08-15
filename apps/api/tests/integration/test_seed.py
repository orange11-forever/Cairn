from uuid import UUID

import pytest
from cairn_api.auth.models import User
from cairn_api.auth.security import hash_password, verify_password
from cairn_api.db.session import Database
from cairn_api.organizations.models import Membership, Organization
from cairn_api.seed import seed_demo_identity
from cairn_api.settings import Settings
from sqlalchemy import Engine, func, select, update


@pytest.fixture()
def development_settings(test_database_url: str) -> Settings:
    return Settings(
        environment="development",
        database_url=test_database_url,
        csrf_secret="test-only-csrf-secret-with-at-least-32-bytes",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


@pytest.mark.integration
def test_demo_seed_is_idempotent(
    database: Database,
    migrated_engine: Engine,
    development_settings: Settings,
) -> None:
    seed_demo_identity(development_settings, database)
    seed_demo_identity(development_settings, database)

    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Organization)) == 1
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(Membership)) == 1
        organization = session.scalar(select(Organization))
        user = session.scalar(select(User))
        membership = session.scalar(select(Membership))

    assert organization is not None
    assert organization.id == UUID("00000000-0000-4000-8000-000000002001")
    assert organization.slug == "cairn-demo"
    assert user is not None
    assert user.id == UUID("00000000-0000-4000-8000-000000001001")
    assert user.email == "demo@cairn.dev"
    assert user.display_name == "演示用户"
    assert verify_password("cairn-demo-2026", user.password_hash)
    assert membership is not None
    assert membership.id == UUID("00000000-0000-4000-8000-000000003001")
    assert membership.role == "owner"


@pytest.mark.integration
def test_demo_seed_does_not_overwrite_changed_user_fields(
    database: Database,
    migrated_engine: Engine,
    development_settings: Settings,
) -> None:
    seed_demo_identity(development_settings, database)
    changed_hash = hash_password("locally-changed-password")
    with database.session_factory.begin() as session:
        session.execute(
            update(User)
            .where(User.normalized_email == "demo@cairn.dev")
            .values(display_name="本地用户", password_hash=changed_hash)
        )

    seed_demo_identity(development_settings, database)

    with database.session_factory() as session:
        user = session.scalar(select(User).where(User.normalized_email == "demo@cairn.dev"))
    assert user is not None
    assert user.display_name == "本地用户"
    assert user.password_hash == changed_hash


@pytest.mark.integration
def test_demo_seed_rejects_production(
    database: Database,
    migrated_engine: Engine,
    test_database_url: str,
) -> None:
    settings = Settings(
        environment="production",
        database_url=test_database_url,
        app_url="https://app.example.com",
        session_cookie_secure=True,
        csrf_secret="production-only-csrf-secret-with-at-least-32-bytes",
        auth_rate_limit_secret="production-only-auth-rate-limit-secret-with-at-least-32-bytes",
        object_store_access_key="production-object-store-access-key",
        object_store_secret_key="production-object-store-secret-key",
        object_store_public_endpoint_url="https://objects.example.com",
        embedding_api_key="production-embedding-api-key",
        search_audit_secret="production-search-audit-secret-at-least-32-bytes",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    with pytest.raises(RuntimeError, match="production"):
        seed_demo_identity(settings, database)
