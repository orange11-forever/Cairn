from __future__ import annotations

from _thread import LockType
from collections.abc import Callable, Generator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic, sleep
from typing import Literal, cast

from sqlalchemy import Connection, Engine, event, text
from sqlalchemy.orm import Session, SessionTransaction

WAIT_SECONDS = 5.0
FUTURE_SECONDS = 10.0
POLL_SECONDS = 0.01
LOCK_TIMEOUT_MILLISECONDS = 6_000
STATEMENT_TIMEOUT_MILLISECONDS = 8_000
WorkerRole = Literal["holder", "waiter"]


def set_race_transaction_deadlines(connection: Connection) -> None:
    connection.execute(
        text(
            """
            SELECT set_config('lock_timeout', :lock_timeout, true),
                   set_config('statement_timeout', :statement_timeout, true)
            """
        ),
        {
            "lock_timeout": f"{LOCK_TIMEOUT_MILLISECONDS}ms",
            "statement_timeout": f"{STATEMENT_TIMEOUT_MILLISECONDS}ms",
        },
    ).one()


def set_race_session_deadlines(
    _session: Session,
    _transaction: SessionTransaction,
    connection: Connection,
) -> None:
    set_race_transaction_deadlines(connection)


def install_race_session_deadlines(session: Session) -> None:
    event.listen(session, "after_begin", set_race_session_deadlines)


def _raise_completed_worker_exception[T](futures: Sequence[Future[T]]) -> None:
    for future in futures:
        if future.done() and not future.cancelled():
            future.result()


@contextmanager
def _prefer_completed_worker_exception[T](
    futures: Sequence[Future[T]],
) -> Generator[None, None, None]:
    try:
        yield
    finally:
        _raise_completed_worker_exception(futures)


def _assert_workers_still_running[T](
    futures: Sequence[Future[T]],
    *,
    awaited_condition: str,
) -> None:
    _raise_completed_worker_exception(futures)
    if any(future.done() for future in futures):
        raise AssertionError(
            f"worker completed before {awaited_condition} was observed"
        )


def wait_for_race_event[T](
    signal: Event,
    futures: Sequence[Future[T]],
    *,
    awaited_condition: str,
    timeout: float = WAIT_SECONDS,
) -> None:
    with _prefer_completed_worker_exception(futures):
        deadline = monotonic() + timeout
        while not signal.is_set():
            _assert_workers_still_running(
                futures,
                awaited_condition=awaited_condition,
            )
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AssertionError(
                    f"{awaited_condition} was not observed "
                    "before the coordination deadline"
                )
            wait(futures, timeout=min(POLL_SECONDS, remaining))


def shutdown_race_executor[T](
    executor: ThreadPoolExecutor,
    futures: Sequence[Future[T]],
    *,
    cancel_signal: Event,
    force_cancel: Callable[[], None],
    primary_exception: BaseException | None,
    timeout: float = FUTURE_SECONDS,
    force_timeout: float = FUTURE_SECONDS,
) -> None:
    cancel_signal.set()
    for future in futures:
        future.cancel()
    _, unfinished = wait(futures, timeout=timeout)
    force_cancel_error: BaseException | None = None
    if unfinished:
        try:
            force_cancel()
        except BaseException as error:  # noqa: BLE001 - cleanup must preserve primary
            force_cancel_error = error
            if primary_exception is not None:
                primary_exception.add_note(f"force cancellation failed: {error}")
        _, unfinished = wait(unfinished, timeout=force_timeout)
    if unfinished:
        message = (
            "race workers did not finish before the cleanup deadline: "
            f"unfinished={len(unfinished)}"
        )
        if primary_exception is not None:
            primary_exception.add_note(message)
        executor.shutdown(wait=False, cancel_futures=True)
        if primary_exception is not None:
            raise primary_exception
        _raise_completed_worker_exception(futures)
        if force_cancel_error is not None:
            raise force_cancel_error
        raise AssertionError(message)

    executor.shutdown(wait=True, cancel_futures=True)
    if primary_exception is None:
        _raise_completed_worker_exception(futures)
        if force_cancel_error is not None:
            raise force_cancel_error


@dataclass
class LockGate:
    roles: dict[int, WorkerRole] = field(default_factory=dict[int, WorkerRole])
    backend_pids: dict[WorkerRole, int] = field(default_factory=dict[WorkerRole, int])
    holder_locked: Event = field(default_factory=Event)
    waiter_entered: Event = field(default_factory=Event)
    release_holder: Event = field(default_factory=Event)
    guard: LockType = field(default_factory=Lock)

    def register(self, session: Session, role: WorkerRole) -> None:
        with self.guard:
            self.roles[id(session)] = role

    def before_locked_read(self, session: Session) -> WorkerRole | None:
        with self.guard:
            role = self.roles.get(id(session))
        if role is None:
            return None
        backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(backend_pid, int)
        with self.guard:
            self.backend_pids[role] = backend_pid
        if role == "waiter":
            self.waiter_entered.set()
        return role

    def after_locked_read(self, role: WorkerRole | None) -> None:
        if role != "holder":
            return
        self.holder_locked.set()
        if not self.release_holder.wait(WAIT_SECONDS):
            raise AssertionError("holder was not released before the coordination deadline")

    def pid(self, role: WorkerRole) -> int:
        with self.guard:
            return self.backend_pids[role]

    def pids(self) -> tuple[int, ...]:
        with self.guard:
            return tuple(self.backend_pids.values())


def terminate_race_backends(engine: Engine, gate: LockGate) -> None:
    backend_pids = gate.pids()
    if not backend_pids:
        return
    with engine.connect() as connection:
        set_race_transaction_deadlines(connection)
        for backend_pid in backend_pids:
            connection.scalar(
                text("SELECT pg_terminate_backend(:backend_pid)"),
                {"backend_pid": backend_pid},
            )


def assert_waiting_on_lock[T](
    engine: Engine,
    gate: LockGate,
    futures: Sequence[Future[T]] = (),
) -> None:
    with _prefer_completed_worker_exception(futures):
        _assert_workers_still_running(
            futures,
            awaited_condition="the PostgreSQL blocking edge",
        )
        waiter_pid = gate.pid("waiter")
        holder_pid = gate.pid("holder")
        deadline = monotonic() + WAIT_SECONDS
        last_activity: dict[str, object] | None = None
        statement = text(
            """
            SELECT pg_blocking_pids(pid) AS blocking_pids,
                   state,
                   wait_event_type,
                   wait_event
            FROM pg_stat_activity
            WHERE pid = :waiter_pid
            """
        )
        with engine.connect() as connection:
            set_race_transaction_deadlines(connection)
            while monotonic() < deadline:
                _assert_workers_still_running(
                    futures,
                    awaited_condition="the PostgreSQL blocking edge",
                )
                row = (
                    connection.execute(
                        statement,
                        {"waiter_pid": waiter_pid},
                    )
                    .mappings()
                    .one_or_none()
                )
                last_activity = dict(row) if row is not None else None
                blockers = cast(
                    Sequence[int],
                    (
                        ()
                        if row is None or row["blocking_pids"] is None
                        else row["blocking_pids"]
                    ),
                )
                if holder_pid in blockers:
                    return
                sleep(POLL_SECONDS)
        raise AssertionError(
            "waiter backend did not block on holder backend: "
            f"holder_pid={holder_pid}, waiter_pid={waiter_pid}, "
            f"activity={last_activity}"
        )


__all__ = [
    "FUTURE_SECONDS",
    "LOCK_TIMEOUT_MILLISECONDS",
    "STATEMENT_TIMEOUT_MILLISECONDS",
    "WAIT_SECONDS",
    "LockGate",
    "WorkerRole",
    "assert_waiting_on_lock",
    "install_race_session_deadlines",
    "set_race_session_deadlines",
    "set_race_transaction_deadlines",
    "shutdown_race_executor",
    "terminate_race_backends",
    "wait_for_race_event",
]
