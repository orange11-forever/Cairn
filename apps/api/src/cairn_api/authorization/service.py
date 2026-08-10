from uuid import UUID

from sqlalchemy.orm import Session

from cairn_api.audit.repository import add_audit_log
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import RequestAuditContext
from cairn_api.authorization import repository
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.schemas import AclEntryResponse, AclPage
from cairn_api.authorization.types import (
    ActorType,
    MembershipRole,
    PrincipalRef,
    PrincipalType,
    ProjectPermission,
    ResourceType,
)
from cairn_api.errors import ApiProblem
from cairn_api.projects.models import OutboxEvent


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 100:
        raise ApiProblem(status_code=422, code="invalid_page_limit", message="分页大小无效")


class ProjectAclService:
    def __init__(
        self,
        session: Session,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._session = session
        self._policy = policy or AuthorizationPolicy(session)

    def list_acl(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> AclPage:
        _validate_limit(limit)
        self._policy.require_project(identity, project_id, ProjectPermission.MANAGE)
        entries, next_cursor = repository.list_active_entries(
            self._session,
            org_id=identity.organization.id,
            resource_type=ResourceType.PROJECT,
            resource_id=project_id,
            cursor=cursor,
            limit=limit,
        )
        return AclPage(
            items=[AclEntryResponse.model_validate(entry) for entry in entries],
            next_cursor=next_cursor,
        )

    def set_acl(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        principal_type: str,
        principal_id: str,
        permission: ProjectPermission,
        audit: RequestAuditContext,
    ) -> AclEntryResponse:
        with self._session.begin():
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.MANAGE,
                for_update=True,
            )
            principal = self._principal(
                identity=identity,
                principal_type=principal_type,
                principal_id=principal_id,
            )
            current = repository.get_active_entry(
                self._session,
                org_id=identity.organization.id,
                resource_type=ResourceType.PROJECT,
                resource_id=project_id,
                principal=principal,
                for_update=True,
            )
            if current is not None and current.permission == permission.value:
                return AclEntryResponse.model_validate(current)
            old_permission = None if current is None else current.permission
            if current is not None:
                repository.revoke_entry(
                    self._session,
                    entry=current,
                    actor_type=ActorType.USER,
                    actor_id=identity.user.id,
                )
            entry = repository.create_entry(
                self._session,
                org_id=identity.organization.id,
                resource_type=ResourceType.PROJECT,
                resource_id=project_id,
                principal=principal,
                permission=permission,
                actor_type=ActorType.USER,
                actor_id=identity.user.id,
            )
            self._record_change(
                identity=identity,
                audit=audit,
                project_id=project_id,
                event_type="project.acl_granted",
                principal=principal,
                old_permission=old_permission,
                new_permission=permission.value,
            )
        return AclEntryResponse.model_validate(entry)

    def revoke_acl(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        principal_type: str,
        principal_id: str,
        audit: RequestAuditContext,
    ) -> None:
        with self._session.begin():
            self._policy.require_project(
                identity,
                project_id,
                ProjectPermission.MANAGE,
                for_update=True,
            )
            principal = self._principal(
                identity=identity,
                principal_type=principal_type,
                principal_id=principal_id,
            )
            current = repository.get_active_entry(
                self._session,
                org_id=identity.organization.id,
                resource_type=ResourceType.PROJECT,
                resource_id=project_id,
                principal=principal,
                for_update=True,
            )
            if current is None:
                return
            repository.revoke_entry(
                self._session,
                entry=current,
                actor_type=ActorType.USER,
                actor_id=identity.user.id,
            )
            self._record_change(
                identity=identity,
                audit=audit,
                project_id=project_id,
                event_type="project.acl_revoked",
                principal=principal,
                old_permission=current.permission,
                new_permission=None,
            )

    def _principal(
        self,
        *,
        identity: IdentityContextResponse,
        principal_type: str,
        principal_id: str,
    ) -> PrincipalRef:
        try:
            kind = PrincipalType(principal_type)
            if kind is PrincipalType.GROUP:
                raise ValueError("groups are not implemented")
            if kind is PrincipalType.ROLE:
                return PrincipalRef(kind, MembershipRole(principal_id).value)
            parsed = UUID(principal_id)
            canonical = str(parsed)
            if kind is PrincipalType.ORG and parsed != identity.organization.id:
                raise ValueError("organization principal must be current")
            if kind is PrincipalType.USER and not repository.is_current_org_member(
                self._session,
                org_id=identity.organization.id,
                user_id=parsed,
            ):
                raise ValueError("user principal must be a current member")
            return PrincipalRef(kind, canonical)
        except (ValueError, TypeError) as exc:
            raise ApiProblem(
                status_code=422,
                code="invalid_principal",
                message="授权主体无效",
            ) from exc

    def _record_change(
        self,
        *,
        identity: IdentityContextResponse,
        audit: RequestAuditContext,
        project_id: UUID,
        event_type: str,
        principal: PrincipalRef,
        old_permission: str | None,
        new_permission: str | None,
    ) -> None:
        change: dict[str, object] = {
            "projectId": str(project_id),
            "principalType": principal.principal_type.value,
            "principalId": principal.principal_id,
            "oldPermission": old_permission,
            "newPermission": new_permission,
        }
        add_audit_log(
            self._session,
            org_id=identity.organization.id,
            actor_type=ActorType.USER.value,
            actor_id=identity.user.id,
            action=event_type,
            resource_type=ResourceType.PROJECT.value,
            resource_id=project_id,
            trace_id=audit.trace_id,
            ip=audit.ip,
            user_agent=audit.user_agent,
            details=change,
        )
        self._session.add(
            OutboxEvent(
                org_id=identity.organization.id,
                event_type=event_type,
                aggregate_type=ResourceType.PROJECT.value,
                aggregate_id=project_id,
                payload=change,
            )
        )


__all__ = ["ProjectAclService"]
