from uuid import UUID

from sqlalchemy.orm import Session

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization.policy import can_change_membership_role
from cairn_api.authorization.types import ActorType, MembershipRole
from cairn_api.errors import ApiProblem
from cairn_api.organizations import repository
from cairn_api.organizations.repository import MembershipWithUser
from cairn_api.organizations.schemas import MembershipDetailResponse, MembershipPage
from cairn_api.projects.models import OutboxEvent


def _not_found() -> ApiProblem:
    return ApiProblem(status_code=404, code="not_found", message="请求的资源不存在")


def _forbidden() -> ApiProblem:
    return ApiProblem(
        status_code=403,
        code="forbidden",
        message="没有执行该操作的权限",
    )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 100:
        raise ApiProblem(status_code=422, code="invalid_page_limit", message="分页大小无效")


def _membership_response(record: MembershipWithUser) -> MembershipDetailResponse:
    membership = record.membership
    return MembershipDetailResponse(
        id=membership.id,
        user_id=membership.user_id,
        email=record.user.email,
        display_name=(
            record.user.display_name
            if record.user.display_name is not None
            else record.user.email
        ),
        role=MembershipRole(membership.role),
        created_at=membership.created_at,
    )


class OrganizationService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_memberships(
        self,
        *,
        identity: IdentityContextResponse,
        organization_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> MembershipPage:
        if organization_id != identity.organization.id:
            raise _not_found()
        if MembershipRole(identity.membership.role) not in {
            MembershipRole.OWNER,
            MembershipRole.ADMIN,
        }:
            raise _forbidden()
        _validate_limit(limit)
        memberships, next_cursor = repository.list_memberships(
            self._session,
            org_id=organization_id,
            cursor=cursor,
            limit=limit,
        )
        return MembershipPage(
            items=[_membership_response(record) for record in memberships],
            next_cursor=next_cursor,
        )

    def update_membership_role(
        self,
        *,
        identity: IdentityContextResponse,
        organization_id: UUID,
        membership_id: UUID,
        requested_role: MembershipRole,
        audit: RequestAuditContext,
    ) -> MembershipDetailResponse:
        if organization_id != identity.organization.id:
            raise _not_found()
        with self._session.begin():
            organization = repository.get_organization(
                self._session,
                organization_id,
                for_no_key_update=True,
            )
            if organization is None:
                raise _not_found()
            actor = repository.get_membership_for_actor(
                self._session,
                org_id=organization_id,
                membership_id=identity.membership.id,
                for_update=True,
            )
            target = repository.get_membership_with_user(
                self._session,
                org_id=organization_id,
                membership_id=membership_id,
                for_update=True,
            )
            if actor is None or target is None:
                raise _not_found()
            actor_role = MembershipRole(actor.role)
            current_role = MembershipRole(target.membership.role)
            if not can_change_membership_role(actor_role, current_role, requested_role):
                raise _forbidden()
            if current_role is requested_role:
                return _membership_response(target)
            if (
                current_role is MembershipRole.OWNER
                and requested_role is not MembershipRole.OWNER
                and repository.count_owners(self._session, org_id=organization_id) <= 1
            ):
                raise ApiProblem(
                    status_code=409,
                    code="last_owner_required",
                    message="组织必须保留至少一名所有者",
                )
            repository.set_membership_role(
                self._session,
                membership=target.membership,
                role=requested_role,
            )
            self._record_role_change(
                identity=identity,
                audit=audit,
                organization_id=organization_id,
                target_membership_id=membership_id,
                old_role=current_role,
                new_role=requested_role,
            )
            return _membership_response(target)

    def _record_role_change(
        self,
        *,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        organization_id: UUID,
        target_membership_id: UUID,
        old_role: MembershipRole,
        new_role: MembershipRole,
    ) -> None:
        details: dict[str, object] = {
            "organizationId": str(organization_id),
            "membershipId": str(target_membership_id),
            "oldRole": old_role.value,
            "newRole": new_role.value,
        }
        add_audit_log(
            self._session,
            org_id=organization_id,
            actor_type=ActorType.USER.value,
            actor_id=identity.user.id,
            action="membership.role_changed",
            resource_type="membership",
            resource_id=target_membership_id,
            trace_id=audit.trace_id,
            ip=audit.ip,
            user_agent=audit.user_agent,
            details=details,
        )
        self._session.add(
            OutboxEvent(
                org_id=organization_id,
                event_type="membership.role_changed",
                aggregate_type="organization",
                aggregate_id=organization_id,
                payload=details,
            )
        )


__all__ = ["OrganizationService"]
