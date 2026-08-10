from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from cairn_api.auth.models import User
from cairn_api.authorization.types import MembershipRole
from cairn_api.organizations.models import Membership, Organization
from cairn_api.pagination import decode_cursor, encode_cursor


@dataclass(frozen=True)
class MembershipWithUser:
    membership: Membership
    user: User


def get_organization(
    session: Session,
    org_id: UUID,
    *,
    for_update: bool = False,
) -> Organization | None:
    statement = select(Organization).where(Organization.id == org_id)
    if for_update:
        statement = statement.with_for_update(of=Organization)
    return session.scalar(statement)


def get_membership_with_user(
    session: Session,
    *,
    org_id: UUID,
    membership_id: UUID,
    for_update: bool = False,
) -> MembershipWithUser | None:
    statement = (
        select(Membership, User)
        .where(
            Membership.org_id == org_id,
            Membership.id == membership_id,
        )
        .join(User, User.id == Membership.user_id)
    )
    if for_update:
        statement = statement.with_for_update(of=Membership)
    row = session.execute(statement).one_or_none()
    if row is None:
        return None
    return MembershipWithUser(membership=row[0], user=row[1])


def get_membership_for_actor(
    session: Session,
    *,
    org_id: UUID,
    membership_id: UUID,
    for_update: bool = False,
) -> Membership | None:
    statement = select(Membership).where(
        Membership.org_id == org_id,
        Membership.id == membership_id,
    )
    if for_update:
        statement = statement.with_for_update(of=Membership)
    return session.scalar(statement)


def list_memberships(
    session: Session,
    *,
    org_id: UUID,
    cursor: str | None,
    limit: int,
) -> tuple[list[MembershipWithUser], str | None]:
    statement = (
        select(Membership, User)
        .where(Membership.org_id == org_id)
        .join(User, User.id == Membership.user_id)
    )
    if cursor is not None:
        cursor_timestamp, cursor_id = decode_cursor(cursor)
        statement = statement.where(
            or_(
                Membership.created_at > cursor_timestamp,
                and_(
                    Membership.created_at == cursor_timestamp,
                    Membership.id > cursor_id,
                ),
            )
        )
    rows = session.execute(
        statement.order_by(Membership.created_at, Membership.id).limit(limit + 1)
    ).all()
    records = [MembershipWithUser(membership=row[0], user=row[1]) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit and records:
        last = records[-1].membership
        next_cursor = encode_cursor(last.created_at, last.id)
    return records, next_cursor


def count_owners(session: Session, *, org_id: UUID) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.org_id == org_id,
            Membership.role == MembershipRole.OWNER.value,
        )
    )
    return int(count or 0)


def set_membership_role(
    session: Session,
    *,
    membership: Membership,
    role: MembershipRole,
) -> None:
    membership.role = role.value
    session.flush()


__all__ = [
    "MembershipWithUser",
    "count_owners",
    "get_membership_for_actor",
    "get_membership_with_user",
    "get_organization",
    "list_memberships",
    "set_membership_role",
]
