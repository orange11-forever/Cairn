from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.auth.service import AuthService, RequestAuditContext
from cairn_api.db.session import get_db
from cairn_api.middleware import new_request_id
from cairn_api.settings import Settings


def get_request_settings(request: Request) -> Settings:
    value = request.app.state.settings
    if not isinstance(value, Settings):
        raise TypeError("application settings are unavailable")
    return value


def get_audit_context(request: Request) -> RequestAuditContext:
    trace_id = getattr(request.state, "request_id", None)
    return RequestAuditContext(
        trace_id=trace_id if isinstance(trace_id, str) else new_request_id(),
        ip=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("user-agent"),
    )


def get_current_identity(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> IdentityContextResponse:
    settings = get_request_settings(request)
    return AuthService(session, settings).restore(
        session_token=request.cookies.get(settings.session_cookie_name),
        audit=get_audit_context(request),
    )


CurrentIdentity = Annotated[IdentityContextResponse, Depends(get_current_identity)]
