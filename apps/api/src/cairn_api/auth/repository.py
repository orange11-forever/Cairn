from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from cairn_api.auth.models import AuthSession, User
from cairn_api.organizations.models import Membership, Organization


@dataclass(frozen=True)
class MembershipRecord:
    membership: Membership
    organization: Organization


@dataclass(frozen=True)
class SessionRecord:
    auth_session: AuthSession
    user: User
    membership: Membership
    organization: Organization


def get_user_by_normalized_email(session: Session, normalized_email: str) -> User | None:
    return session.scalar(select(User).where(User.normalized_email == normalized_email))


def get_memberships_for_user(session: Session, user: User) -> list[MembershipRecord]:
    rows = session.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at, Membership.id)
    ).all()
    return [MembershipRecord(membership=row[0], organization=row[1]) for row in rows]


def get_session_record(session: Session, token_digest: bytes) -> SessionRecord | None:
    row = session.execute(
        select(AuthSession, User, Membership, Organization)
        .join(User, User.id == AuthSession.user_id)
        .join(
            Membership,
            and_(
                Membership.org_id == AuthSession.org_id,
                Membership.user_id == AuthSession.user_id,
            ),
        )
        .join(Organization, Organization.id == AuthSession.org_id)
        .where(AuthSession.token_digest == token_digest)
    ).one_or_none()
    if row is None:
        return None
    return SessionRecord(
        auth_session=row[0],
        user=row[1],
        membership=row[2],
        organization=row[3],
    )
