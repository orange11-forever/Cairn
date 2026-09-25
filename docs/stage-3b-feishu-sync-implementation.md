# Stage 3B durable Feishu sync — implementation slice

2026-09-25. Settled specification for durable manual Feishu sync, built on explicit project sharing and source revocation. Independent specification and quality reviews and the post-fix `pnpm verify` passed; see the [acceptance record](stage-3b-feishu-sync-acceptance.md). Management UI, periodic sync, upstream permission/deletion propagation and real-tenant acceptance remain outside this slice.

## API and persistence

- POST `/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs` accepts strict empty JSON object, returns202. GET same path plus `/{sync_id}` returns200. Only current owner/admin with project manage. Reuse current role/lock ordering, CSRF,404 concealment, request-ID/traceId/no-store/CORS/Allow/503/500 and OpenAPI/SDK conventions.
- POST configured source only. Under project/source locks reuse any queued/running sync (no duplicate audit/event), otherwise atomically create request, job, audit/outbox. GET may observe old runs of a disabled source because configuration remains admin-visible.
- Response: id, projectId, sourceId, status(queued/running/completed/failed), attempt, createdAt, completedAt, errorCode, resourceId and resourceVersionId (nullable). Completed sync means snapshot persisted/index queued; existing resource APIs expose subsequent indexing status.
- New knowledge_source_syncs: id,org_id,project_id,source_id,requested_by,created_at and nullable result resource/version IDs. Status/attempt/error/completion are read from ingestion_jobs. New kind sync_feishu_source, target_id=sync UUID, profile_version=feishu-sync-v1, retaining job uniqueness.
- Migration0007 after current0006 adds table, source composite unique(org_id,project_id,id) for tenant-safe sync FK, job-kind check. Result FK binds org/project/resource/version. Downgrade safely rejects populated sync requests/jobs instead of deleting facts.
- Reuse current error codes: map Feishu/credential failures to safe parser_failed with original retryable flag and bounded Retry-After; storage failures use object_store_unavailable. Never persist raw upstream error text. No new error-enum migration needed.
- Queued audit/outbox include safe syncId and jobId for correlation, without document IDs, credential aliases or names.

## Worker

- Register default sync handler. Resolve credentials lazily inside sync execution; ordinary upload startup/preflight remains independent of Feishu configuration. Upload-required handler set may remain minimal; default runtime still registers new kind and claim filtering handles custom runtimes.
- Resolve trusted claim→job→sync→source by org/project. Validate configured/project_members/provider before client creation or I/O. FeishuCredentialResolver uses persisted org and alias; read uses persisted document ID. Tests inject fake resolver/client.
- Snapshot UTF8 text/plain, verify hash, reject empty content; title trimmed to512 with nonempty source-name fallback. source_version=canonical decimal revision (max255 chars). Existing reader does not promise upstream atomic snapshot.
- Recheck heartbeat ownership and current scalar source facts after read. Persisted source identity/alias must still equal what was used to read.
- After the Feishu read, lock/revalidate sync job and attempt using current scalar facts or populate_existing, then lock project (avoids project-FK insert deadlocks), existing resource, source and sync result. This avoids sync-row→job vs reclaim-job→sync-row cycles. Do not hold job locks across the Feishu read. Existing index publisher uses version FOR NO KEY UPDATE→resource→source without project; the non-key version lock permits the KEY SHARE required by a duplicate sync result FK and avoids a version/resource lock cycle. Publication changes only non-key version status/timing fields. Do not hold source then wait for a resource held by publisher. Queue API does not lock existing job rows while holding source.
- Find resources by source identity including deleted rows; never resurrect deleted resources. Under locks recheck source and choose current active org/global embedding profile.
- Duplicate revision+hash reuses version/index job without extra object/version/job, regardless of existing indexing status; it never silently requeues a failed index. Existing resource API exposes failure and explicit retry. Same revision/different hash is a bounded retryable failure. Older fetched revision is a terminal parser_failed(retryable=False) before object write, preserving newer stored/published facts. Existing shared history remains on transient/upstream403/404 failures; upstream deletion/permission propagation remains separate from manual disable.
- Write unique immutable object key using only trusted org/project/source/version UUIDs. Register rollback cleanup with existing Worker transaction convention. Storage/lease/DB failures leave no partial DB facts and never delete another attempt's object. Crash-orphan cleanup remains separate.
- Atomically create resource/version/index_resource_version job, sync result, audit/outbox and complete sync job. Keep old current_version until indexing publishes. No ingestion batches/items for source sync.
- Extend lease terminalization for sync kind, avoiding treating sync UUID as version UUID; preserve retry budget/attempts/fencing.
- Prevent late old Feishu index publication replacing newer published revision. Numeric compare applies to canonical decimal revisions produced by this slice; retain prior synthetic/local behavior. Stale publication is safe terminal failure preserving current pointer/chunks. Test real publication ordering.
- Explicit retry classification uses WorkerFailure(..., retryable=...) rather than for_code(parser_failed): credentials, disabled/changed source identity, malformed snapshot, upstream401/403/404 and stale revision are terminal; transport/429/5xx and reader feishu_document_changed retain bounded automatic retry. Empty content uses terminal no_extractable_text. Same-revision hash mismatch remains retryable as above. Unknown ordinary handler exceptions retain the existing runner's safe bounded retry behavior.

## Verification

Consumer-boundary tests cover concurrent queue coalescing; both endpoint contracts and current-role changes; tenant/result integrity and populated downgrade refusal; credential and upstream failures; malformed snapshots; duplicate, conflicting, newer and stale revisions; lease loss/reclaim/exhaustion; object and transaction rollback; and sync through indexing to authorized search.

A deterministic concurrent duplicate-sync/index regression reproduces the original implicit foreign-key deadlock before the version lock correction and requires both jobs to complete in one attempt afterward. Deletion, source revocation and stale publication regressions retain their existing fencing assertions.

Run `pnpm verify` for SDK/runtime contracts, Python and Web tests, static checks, real PostgreSQL/MinIO, builds, browser flow and production authentication-proxy verification. Review both the diff and affected boundaries in specification→quality order under [the review policy](review.md).
