from unittest.mock import MagicMock

import pytest
from cairn_api.auth.service import AuthService, RequestAuditContext
from cairn_api.errors import ApiProblem
from cairn_api.settings import Settings
from sqlalchemy.orm import Session


def test_restore_rejects_non_ascii_session_tokens_as_invalid() -> None:
    session = MagicMock(spec=Session)
    service = AuthService(
        session,
        Settings(_env_file=None),  # pyright: ignore[reportCallIssue]
    )

    with pytest.raises(ApiProblem) as raised:
        service.restore(
            session_token="\N{LATIN SMALL LETTER E WITH ACUTE}",
            audit=RequestAuditContext(trace_id="req-cookie", ip=None, user_agent=None),
        )

    assert raised.value.status_code == 401
    assert raised.value.code == "session_invalid"
    session.begin.assert_not_called()
