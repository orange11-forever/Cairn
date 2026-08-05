from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Self, cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from cairn_api.maintenance import auth_cleanup
from cairn_api.maintenance.auth_cleanup import CleanupCounts, cleanup_auth_state
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


class _RowsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    def __init__(self, batches: list[list[object]]) -> None:
        self._batches = iter(batches)
        self.statements: list[object] = []
        self.deleted: list[object] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @contextmanager
    def begin(self) -> Generator[None, None, None]:
        yield

    def scalars(self, statement: object) -> _RowsResult:
        self.statements.append(statement)
        return _RowsResult(next(self._batches))

    def execute(self, statement: object) -> _RowsResult | SimpleNamespace:
        self.statements.append(statement)
        if getattr(statement, "is_delete", False):
            self.deleted.append(statement)
            if getattr(statement, "_returning", ()):
                empty: list[object] = []
                return _RowsResult(next(self._batches, empty))
            return SimpleNamespace(rowcount=0)
        if getattr(statement, "is_select", False):
            empty: list[object] = []
            return _RowsResult(next(self._batches, empty))
        return SimpleNamespace(rowcount=0)


class _FakeFactory:
    def __init__(self, sessions: list[_FakeSession]) -> None:
        self.sessions = iter(sessions)

    def __call__(self) -> _FakeSession:
        return next(self.sessions)


def _digest(index: int) -> bytes:
    return index.to_bytes(4, "big") * 8


def test_cleanup_runs_bounded_batches_in_stable_order() -> None:
    session_one = _FakeSession(
        [
            [UUID(int=index) for index in range(1000)],
            [UUID(int=index) for index in range(1000, 2000)],
            [UUID(int=index) for index in range(2000, 2002)],
        ]
    )
    session_two = _FakeSession(
        [
            [("email", _digest(index)) for index in range(1000)],
            [("email", _digest(index)) for index in range(1000, 2000)],
            [("ip", _digest(index)) for index in range(2000, 2002)],
        ]
    )
    factory = _FakeFactory(
        [session_one, session_one, session_one, session_two, session_two, session_two]
    )
    clock = MagicMock(return_value=datetime(2026, 8, 5, tzinfo=UTC))

    result = cleanup_auth_state(
        cast(sessionmaker[Session], factory),
        now=clock,
        batch_size=1000,
    )

    assert result == CleanupCounts(sessions_deleted=2002, rate_limits_deleted=2002)
    assert len(session_one.deleted) == 3
    assert len(session_two.deleted) == 3
    assert all("ORDER BY" in str(statement).upper() for statement in session_one.statements[::2])
    assert clock.call_count == 1


def test_cleanup_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        cleanup_auth_state(MagicMock(), now=lambda: datetime.now(UTC), batch_size=0)


def test_rate_limit_cleanup_locks_and_deletes_each_batch_atomically() -> None:
    session_cleanup = _FakeSession([[]])
    rate_limit_cleanup = _FakeSession([[("email", b"e" * 32)]])
    factory = _FakeFactory([session_cleanup, rate_limit_cleanup])

    result = cleanup_auth_state(
        cast(sessionmaker[Session], factory),
        now=lambda: datetime(2026, 8, 5, tzinfo=UTC),
        batch_size=1000,
    )

    assert result == CleanupCounts(sessions_deleted=0, rate_limits_deleted=1)
    assert len(rate_limit_cleanup.statements) == 1
    statement = rate_limit_cleanup.statements[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]
    assert "DELETE FROM auth_rate_limits" in sql
    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" in sql
    assert "RETURNING" in sql


def test_session_cleanup_locks_and_deletes_each_batch_atomically() -> None:
    session_cleanup = _FakeSession([[uuid4()]])
    rate_limit_cleanup = _FakeSession([[]])
    factory = _FakeFactory([session_cleanup, rate_limit_cleanup])

    result = cleanup_auth_state(
        cast(sessionmaker[Session], factory),
        now=lambda: datetime(2026, 8, 5, tzinfo=UTC),
        batch_size=1000,
    )

    assert result == CleanupCounts(sessions_deleted=1, rate_limits_deleted=0)
    assert len(session_cleanup.statements) == 1
    statement = session_cleanup.statements[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]
    assert "DELETE FROM auth_sessions" in sql
    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" in sql
    assert "RETURNING" in sql


def test_cleanup_command_returns_nonzero_without_success_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = MagicMock()
    monkeypatch.setattr(auth_cleanup, "Settings", MagicMock())
    monkeypatch.setattr(auth_cleanup, "Database", MagicMock(return_value=database))
    monkeypatch.setattr(
        auth_cleanup,
        "cleanup_auth_state",
        MagicMock(side_effect=SQLAlchemyError("database unavailable")),
    )

    assert auth_cleanup.run_auth_cleanup() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "auth-cleanup failed" in captured.err
    database.dispose.assert_called_once_with()
