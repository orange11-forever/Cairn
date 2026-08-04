from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from cairn_api.auth.models import User
from cairn_api.auth.security import hash_password, normalize_email
from cairn_api.db.session import Database
from cairn_api.organizations.models import Membership, Organization
from cairn_api.settings import Settings

DEMO_USER_ID = UUID("00000000-0000-4000-8000-000000001001")
DEMO_ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000002001")
DEMO_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000003001")
DEMO_EMAIL = "demo@cairn.dev"
DEMO_PASSWORD = "cairn-demo-2026"


def seed_demo_identity(settings: Settings, database: Database) -> None:
    if settings.environment == "production":
        raise RuntimeError("demo identity seed is disabled in production")

    normalized_email = normalize_email(DEMO_EMAIL)
    with database.session_factory.begin() as session:
        session.execute(
            insert(Organization)
            .values(
                id=DEMO_ORGANIZATION_ID,
                slug="cairn-demo",
                name="Cairn Demo",
            )
            .on_conflict_do_nothing()
        )
        organization = session.scalar(
            select(Organization).where(Organization.slug == "cairn-demo")
        )
        if organization is None:
            raise RuntimeError("demo organization could not be created")

        session.execute(
            insert(User)
            .values(
                id=DEMO_USER_ID,
                email=DEMO_EMAIL,
                normalized_email=normalized_email,
                display_name="演示用户",
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=True,
            )
            .on_conflict_do_nothing()
        )
        user = session.scalar(select(User).where(User.normalized_email == normalized_email))
        if user is None:
            raise RuntimeError("demo user could not be created")

        session.execute(
            insert(Membership)
            .values(
                id=DEMO_MEMBERSHIP_ID,
                org_id=organization.id,
                user_id=user.id,
                role="owner",
            )
            .on_conflict_do_nothing()
        )


def main() -> None:
    settings = Settings()
    database = Database(settings.database_url)
    try:
        seed_demo_identity(settings, database)
        with database.session_factory() as session:
            organization_id = session.scalar(
                select(Organization.id).where(Organization.slug == "cairn-demo")
            )
            user_id = session.scalar(
                select(User.id).where(User.normalized_email == normalize_email(DEMO_EMAIL))
            )
        print(f"Seeded demo identity: organization={organization_id} user={user_id}")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
