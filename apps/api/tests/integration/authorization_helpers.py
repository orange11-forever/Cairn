from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

from cairn_api.app import create_app
from cairn_api.auth.models import User
from cairn_api.auth.security import hash_password
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.organizations.models import Membership, Organization
from cairn_api.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import select

APP_ORIGIN = "http://localhost:5500"
TEST_PASSWORD = "authorization-test-password"


@dataclass(frozen=True)
class SeededActor:
    organization_id: UUID
    user_id: UUID
    membership_id: UUID
    email: str
    password: str
    role: MembershipRole


def seed_actor(
    database: Database,
    role: MembershipRole,
    org_id: UUID | None = None,
) -> SeededActor:
    organization_id = org_id or uuid4()
    user_id = uuid4()
    membership_id = uuid4()
    email = f"actor-{user_id}@example.com"
    with database.session_factory.begin() as session:
        if org_id is None:
            session.add(
                Organization(
                    id=organization_id,
                    slug=f"actor-{organization_id}",
                    name="Authorization test organization",
                )
            )
        elif session.get(Organization, organization_id) is None:
            raise ValueError("org_id must identify an existing organization")
        session.add(
            User(
                id=user_id,
                email=email,
                normalized_email=email,
                display_name=f"Test {role.value}",
                password_hash=hash_password(TEST_PASSWORD),
            )
        )
        session.flush()
        session.add(
            Membership(
                id=membership_id,
                org_id=organization_id,
                user_id=user_id,
                role=role.value,
            )
        )
    return SeededActor(
        organization_id=organization_id,
        user_id=user_id,
        membership_id=membership_id,
        email=email,
        password=TEST_PASSWORD,
        role=role,
    )


@contextmanager
def authenticated_client(
    settings: Settings,
    database: Database,
    actor: SeededActor,
) -> Generator[TestClient, None, None]:
    with TestClient(
        create_app(settings, database),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/v1/login",
            headers={"Origin": APP_ORIGIN},
            json={"email": actor.email, "password": actor.password},
        )
        assert response.status_code == 200
        client.headers.update(
            {
                "Origin": APP_ORIGIN,
                "X-CSRF-Token": response.json()["csrfToken"],
            }
        )
        yield client


def load_active_acl_entries(
    database: Database,
    project_id: UUID,
) -> list[ResourceAclEntry]:
    with database.session_factory() as session:
        return list(
            session.scalars(
                select(ResourceAclEntry).where(
                    ResourceAclEntry.resource_id == project_id,
                    ResourceAclEntry.revoked_at.is_(None),
                )
            ).all()
        )
