import { afterEach, expect, test, vi } from "vitest";

import {
  createFeishuSource, disableFeishuSource, fetchFeishuSync, fetchFeishuSyncs,
  fetchKnowledgeSources, patchFeishuSource, queueFeishuSync,
} from "../../src/api/knowledgeSources.ts";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const SOURCE_ID = "00000000-0000-4000-8000-000000011001";
const SYNC_ID = "00000000-0000-4000-8000-000000012001";
const RESOURCE_ID = "00000000-0000-4000-8000-000000013001";
const VERSION_ID = "00000000-0000-4000-8000-000000014001";
const source = {
  id: SOURCE_ID, projectId: PROJECT_ID, provider: "feishu", name: "团队手册",
  documentId: "Doc123", credentialRef: "team_feishu", accessPolicy: "project_members",
  status: "configured", accessState: "unverified", syncIntervalSeconds: null,
  nextSyncAt: null, lastCheckedAt: null, lastSuccessAt: null, lastErrorCode: null,
  disabledAt: null, createdAt: "2026-09-29T00:00:00Z", updatedAt: "2026-09-29T00:00:00Z",
} as const;
const sync = {
  id: SYNC_ID, projectId: PROJECT_ID, sourceId: SOURCE_ID, status: "completed",
  attempt: 1, createdAt: "2026-09-29T00:00:00Z", completedAt: "2026-09-29T00:01:00Z",
  errorCode: null, failureCode: null, resourceId: RESOURCE_ID, resourceVersionId: VERSION_ID,
  resourceStatus: "queued", nextAttemptAt: null, trigger: "manual",
} as const;
const signal = () => new AbortController().signal;
const response = (body: unknown, status = 200) => Response.json(body, { status });

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("source list validates generated page and project identity", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    requests.push(request); return response({ items: [source], nextCursor: "more" });
  }));
  await expect(fetchKnowledgeSources({ projectId: PROJECT_ID, cursor: "cursor", signal: signal() }))
    .resolves.toEqual({ items: [source], nextCursor: "more" });
  expect(requests[0]?.credentials).toBe("include");
  expect(new URL(requests[0]!.url).searchParams.get("cursor")).toBe("cursor");
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => response({ items: [{ ...source, projectId: SYNC_ID }], nextCursor: null })));
  await expect(fetchKnowledgeSources({ projectId: PROJECT_ID, cursor: null, signal: signal() }))
    .rejects.toMatchObject({ kind: "contract" });
});

test("create, patch and queue use current CSRF and exact IDs/statuses", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    requests.push(request);
    return request.method === "POST" && request.url.endsWith("/feishu") ? response(source, 201) :
      request.method === "PATCH" ? response({ ...source, name: "新名称" }) : response(sync, 202);
  }));
  await createFeishuSource({ projectId: PROJECT_ID, body: {
    name: source.name, documentId: source.documentId, credentialRef: source.credentialRef,
    accessPolicy: "project_members",
  }, csrfToken: "csrf-current", signal: signal() });
  await patchFeishuSource({ projectId: PROJECT_ID, sourceId: SOURCE_ID,
    body: { name: "新名称" }, csrfToken: "csrf-current", signal: signal() });
  await queueFeishuSync({ projectId: PROJECT_ID, sourceId: SOURCE_ID,
    csrfToken: "csrf-current", signal: signal() });
  expect(requests.map((request) => request.headers.get("X-CSRF-Token"))).toEqual([
    "csrf-current", "csrf-current", "csrf-current",
  ]);
  expect(requests.every((request) => request.credentials === "include")).toBe(true);
  expect(JSON.parse(await requests[2]!.text())).toEqual({});
});

test.each([
  ["wrong project", { ...sync, projectId: VERSION_ID }],
  ["wrong source", { ...sync, sourceId: VERSION_ID }],
  ["wrong sync", { ...sync, id: VERSION_ID }],
  ["unpaired result IDs", { ...sync, resourceVersionId: null }],
  ["unpaired resource status", { ...sync, resourceId: null, resourceVersionId: null }],
])("sync detail rejects %s", async (_name, body) => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => response(body)));
  await expect(fetchFeishuSync({ projectId: PROJECT_ID, sourceId: SOURCE_ID, syncId: SYNC_ID,
    signal: signal() })).rejects.toMatchObject({ kind: "contract", retryable: false });
});

test("history validates every result and disable requires an empty 204", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => response({ items: [{ ...sync, sourceId: VERSION_ID }], nextCursor: null })));
  await expect(fetchFeishuSyncs({ projectId: PROJECT_ID, sourceId: SOURCE_ID, cursor: null,
    signal: signal() })).rejects.toMatchObject({ kind: "contract" });
  vi.stubGlobal("fetch", vi.fn(async () => response({ unexpected: true }, 200)));
  await expect(disableFeishuSource({ projectId: PROJECT_ID, sourceId: SOURCE_ID,
    csrfToken: "csrf-current", signal: signal() })).rejects.toMatchObject({ kind: "contract" });
});

test("late 401 after abort stays aborted and does not expose upstream text", async () => {
  const controller = new AbortController();
  let finish!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async () => new Promise<Response>((resolve) => { finish = resolve; })));
  const pending = fetchKnowledgeSources({ projectId: PROJECT_ID, cursor: null, signal: controller.signal });
  controller.abort();
  finish(response({ code: "session_invalid", message: "private upstream text", traceId: "t" }, 401));
  await expect(pending).rejects.toMatchObject({ kind: "aborted" });
});

test("HTTP failures preserve safe code and trace, with a fixed message", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({
    code: "source_conflict", message: "secret upstream value", traceId: "trace-409",
  }, 409)));
  await expect(createFeishuSource({ projectId: PROJECT_ID, body: {
    name: source.name, documentId: source.documentId, credentialRef: source.credentialRef,
    accessPolicy: "project_members",
  }, csrfToken: "csrf-current", signal: signal() })).rejects.toMatchObject({
    kind: "http", status: 409, code: "source_conflict", traceId: "trace-409",
    message: "该飞书文档已登记，请在来源列表中查看",
  });
});
