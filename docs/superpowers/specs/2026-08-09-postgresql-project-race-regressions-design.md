# PostgreSQL Project Race Regression Design

**Date:** 2026-08-09

## Goal

Add two deterministic integration regressions that exercise the real PostgreSQL locking and transaction behavior behind project-task mutations:

1. two competing status transitions for the same task; and
2. two concurrent dependency additions that are individually acyclic but would jointly close a cycle.

The tests protect the business invariants and the associated audit/outbox atomicity. They do not change production behavior.

## Scope

The change adds a focused integration test module under `apps/api/tests/integration/`. Each worker calls `ProjectService` with its own SQLAlchemy `Session`, so the test covers the service transaction, repository locking, PostgreSQL visibility rules, audit write, and outbox write.

The tests use the existing `CAIRN_TEST_DATABASE_URL` guard and migrated PostgreSQL fixture. They do not run against SQLite, mocks, or an in-memory database.

### Non-goals

- No production-only synchronization hooks.
- No changes to the task state machine or dependency algorithm.
- No concurrent HTTP-client coverage in this change.
- No load, throughput, or soak testing.

## Considered Approaches

### A. Service-level workers with PostgreSQL lock observation — chosen

Run two `ProjectService` calls in separate threads and separate Sessions. Use test-only repository wrappers to pause the first call after it has acquired the relevant row lock. Record the second worker's PostgreSQL backend PID and confirm with `pg_blocking_pids()` that it is waiting for the first transaction before releasing the first worker.

This provides deterministic overlap without arbitrary sleeps and exercises the full service transaction, including audit and outbox writes.

### B. Concurrent HTTP requests

This would additionally cover routing, authentication, and CSRF. However, ASGI worker scheduling and connection-pool assignment make it substantially harder to identify the blocked database backend and control the critical section. Those layers already have sequential contract coverage and do not own the concurrency invariant.

### C. Repository-level transaction scripts

Direct SQL or repository calls would make orchestration simpler, but would duplicate the service algorithm and would not prove that rejected mutations avoid audit/outbox side effects. It would provide weaker regression coverage for the behavior being protected.

## Test Architecture

The new integration module will contain small test helpers for:

- constructing the seeded demo identity used by `ProjectService`;
- opening one Session per worker;
- recording the worker Session's PostgreSQL backend PID from its checked-out DBAPI connection;
- waiting, with a monotonic deadline, until `pg_blocking_pids(waiter_pid)` reports the expected blocker;
- running a worker in a bounded `ThreadPoolExecutor`; and
- querying final task, dependency, audit, and outbox state.

All coordination primitives and futures have explicit timeouts. A timeout reports the known backend PIDs and PostgreSQL activity/lock state so a failure distinguishes missing lock contention from an incorrect business result.

The tests install repository wrappers only after fixture data is created. The wrappers delegate to the real repository implementation. The first designated worker pauses after the real locked read returns; the second worker records its PID before entering that read. The main test confirms the second backend is blocked, then releases the first worker. This keeps synchronization test-only and ensures the race reaches PostgreSQL rather than relying on scheduler luck.

## Regression 1: Competing Task Transitions

### Setup

Create a project and a task, then advance the task to `in_progress`. Capture baseline counts for `task.status_changed` audit logs and outbox events.

### Concurrent operations

- Worker A requests `in_progress -> done`.
- Worker B requests `in_progress -> cancelled`.
- Worker A acquires and holds the task row lock.
- Worker B is started and must be observed waiting on Worker A's PostgreSQL backend.
- Release Worker A to commit; Worker B then re-reads the committed `done` status.

### Expected result

- Worker A succeeds with status `done`.
- Worker B raises `ApiProblem(409, "invalid_state_transition")`.
- The stored task status is `done`.
- The concurrent attempt adds exactly one `task.status_changed` audit log.
- The concurrent attempt adds exactly one `task.status_changed` outbox event.
- The successful audit resource ID and outbox payload identify the target task and final status.
- The rejected worker's trace ID has no audit row.

This protects both serialization and atomic side effects. The existing conditional update remains a second line of defense, but the test proves the intended PostgreSQL row-lock behavior is present.

## Regression 2: Concurrent Cycle Closure

### Setup

Create one project with four tasks `A`, `B`, `C`, and `D`. Add two committed dependency edges:

```text
B -> C
D -> A
```

Capture baseline counts for `task.dependency_added` audit logs and outbox events.

### Concurrent operations

- Worker A adds `A -> B`.
- Worker B adds `C -> D`.

The two operations have disjoint endpoint sets. Task-row locking therefore cannot accidentally serialize them. Together with the existing edges they would form:

```text
A -> B -> C -> D -> A
```

Worker A acquires and holds the owning project row lock. Worker B reaches the same project lock and must be observed waiting on Worker A's PostgreSQL backend. After Worker A commits, Worker B re-evaluates reachability against the newly committed edge and rejects the cycle.

### Expected result

- Worker A succeeds and returns the new `A -> B` dependency.
- Worker B raises `ApiProblem(409, "dependency_cycle")`.
- Final persisted edges are exactly `B -> C`, `D -> A`, and `A -> B`.
- The concurrent attempt adds exactly one `task.dependency_added` audit log.
- The concurrent attempt adds exactly one `task.dependency_added` outbox event.
- Audit and outbox data identify Worker A's committed dependency.
- The rejected worker's trace ID has no audit row.

This topology is deliberate: a two-task `A -> B` versus `B -> A` race would share endpoint locks and could pass even if the project-level serialization were removed.

## Error Handling and Diagnostics

Worker functions return a normalized success-or-`ApiProblem` result; unexpected exceptions propagate through the future and fail the test. Each Session is closed in its worker thread.

Lock observation uses a short bounded catalog poll rather than a fixed orchestration delay. If the expected blocker is not observed before the deadline, the assertion includes `pg_stat_activity` details for both PIDs. Thread futures also use a larger overall timeout so a broken lock order produces a bounded failure instead of hanging the suite.

## Verification

Run the new module against the repository's PostgreSQL 16 integration environment, then run the relevant API test group and the repository verification command. At minimum:

```bash
pytest apps/api/tests/integration/test_project_concurrency.py
pytest apps/api/tests/integration/test_projects_api.py apps/api/tests/test_project_service.py
pnpm verify
```

The exact project scripts/environment wrapper used by the repository may supply `CAIRN_TEST_DATABASE_URL` and command prefixes, but the tests themselves remain normal `pytest` integration tests.
