from uuid import UUID

from sqlalchemy.orm import Session

from cairn_api.audit.models import AuditLog


def add_audit_log(
    session: Session,
    *,
    org_id: UUID | None,
    actor_type: str,
    actor_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    trace_id: str,
    ip: str | None,
    user_agent: str | None,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditLog(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=trace_id,
            ip=ip,
            user_agent=user_agent,
            details=details or {},
        )
    )
