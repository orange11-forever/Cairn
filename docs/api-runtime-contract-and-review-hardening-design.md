# API Runtime Contract and Review Hardening Design

Date: 2026-08-11

## Context

An audit after an interrupted Stage 3A session found that the Stage 3A worktree was clean and that `app.py` and the existing routers were byte-for-byte unchanged from `main`. The audit nevertheless exposed three pre-existing API contract defects:

1. An unexpected `500` response can bypass CORS headers.
2. A normalized `405` response drops Starlette's safe `Allow` header.
3. Auth and organization operations omit error responses that their runtime paths can return from OpenAPI.

The existing review passed because it concentrated on the requested auth-proxy acceptance criteria and asserted only a subset of the surrounding error contract. This change therefore fixes the defects and strengthens the review boundary that should have found them.

During baseline verification, a separate deterministic problem appeared under WSL with Docker Desktop: environment variables passed to `docker.exe` are not visible to the Windows process unless their names are included in `WSLENV`. Compose consequently used its default PostgreSQL port and database while `verify:core` connected to the configured isolated values. That verifier defect must be fixed first so the repository's required `pnpm verify` gate is trustworthy.

## Goals

- Keep every JSON API error normalized as `{message, code, trace_id}`.
- Apply configured CORS policy to unexpected `500` responses as well as normal and handled-error responses.
- Preserve protocol headers, beginning with `Allow` on `405`, when normalizing framework errors.
- Make OpenAPI describe the error statuses that auth and organization operations can actually return.
- Make WSL plus Docker Desktop honor isolated Compose interpolation values.
- Add a repeatable review checklist and executable regression coverage without adding a required PR approval or a second CI entry point.

## Non-goals

- No Stage 3A knowledge-ingestion behavior is changed.
- No redesign of the complete error schema or authentication model.
- No mandatory hosted-review approval is added; `pnpm verify` remains the single required gate.
- No attempt is made to enumerate undocumented errors for unrelated routers in this patch.

## Design

### 1. Trustworthy Docker invocation under WSL

The Docker command helper will derive the child environment for a selected command. On Linux, when the selected client is `docker.exe`, it will preserve the caller's environment and append the Compose interpolation variable names used by `deploy/compose/core.yml` to `WSLENV`:

- `CAIRN_POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

Existing `WSLENV` entries and flags remain intact, duplicate names are not added, and native Linux Docker and Windows execution remain unchanged. Both the reusable Compose runner and `verify:core` will use the derived environment.

This is deliberately narrower than forwarding every environment variable across the WSL boundary. It exposes only values already required by this Compose file and avoids changing unrelated child-process behavior.

### 2. CORS at the outer application boundary

Configured CORS handling must wrap the complete application exception path. A small internal `FastAPI` subclass will wrap the stack returned by FastAPI's normal `build_middleware_stack` with `CORSMiddleware` when origins are configured. This puts CORS outside Starlette's server-error middleware, so an unexpected exception converted there still receives CORS headers.

The public factory continues to return a `FastAPI` instance. Application state, lifespan, OpenAPI access, dependency overrides, routes, and exception handlers therefore keep their current interfaces, and middleware construction remains lazy. When no origins are configured, the subclass returns FastAPI's normal stack unchanged.

### 3. Safe framework-header propagation

The `StarletteHTTPException` handler will pass through only explicitly safe protocol headers. For `405`, it will retain `Allow`; arbitrary exception headers will not be copied. The response body and request-ID behavior remain normalized.

### 4. OpenAPI error matrices

Auth and organization route declarations will use reusable response maps so runtime and specification remain aligned:

- Login: `401`, `403`, `409`, `422`, `429`, `503`.
- Session restore: `401`, `503`.
- Logout: `403`, `503`.
- Organization detail: `401`, `404`, `422`, `503`.
- Membership list: existing `401`, `403`, `404`, `422`, `503`.
- Membership role update: existing `401`, `403`, `404`, `409`, `422`, `503`.

Every declared error response uses `ErrorBody`. Statuses are based on reachable route, dependency, validation, and service paths rather than a blanket list.

### 5. Review process hardening

The public review contract will live in `docs/review.md`. It will require reviewers to inspect both the diff and the affected boundary, including:

- success, validation, authentication/authorization, infrastructure, and unexpected-exception paths;
- status, body schema, request/trace ID, security/protocol headers, and OpenAPI/SDK impact;
- tests that prove the negative paths, not just source-shape checks;
- sequential specification review followed by quality review.

Private repository agent instructions will mirror these expectations in `AGENTS.md` and `.codex/agents/*.toml`. A repository-governance test will validate the public machine-relevant review policy while continuing to ensure private agent files are not tracked. The existing zero-approval PR policy and the single `pnpm verify` gate remain unchanged.

## Test strategy

Implementation follows red-green-refactor cycles:

1. A Docker-environment test first demonstrates that a WSL `docker.exe` child lacks the required `WSLENV` names, then verifies preservation and de-duplication.
2. A CORS regression forces an unexpected exception with an allowed `Origin` and asserts the normalized `500`, request ID, and CORS headers.
3. A method-not-allowed regression asserts both the normalized body and the route-derived `Allow` value.
4. A table-driven OpenAPI regression asserts the exact expected error-status matrix and `ErrorBody` schema reference for auth and organization operations.
5. A governance test exercises the public review policy invariants through the repository's normal web test command.

After focused tests pass, run API tests, web tests, static checks, builds, and the full `pnpm verify`. The full verification must start an isolated PostgreSQL project on the configured non-default port and clean its container, network, and volume on success or failure.

## Delivery and Stage 3A integration

The patch is developed on `fix/api-runtime-contract-hardening` from `main`. After sequential specification and quality reviews pass, it can be merged independently. Stage 3A should then incorporate that commit before its own work continues; this keeps the unrelated history auditable and prevents the interrupted feature branch from being blamed for older defects.
