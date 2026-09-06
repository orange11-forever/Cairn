import { afterEach, expect, test, vi } from "vitest";

import {
  deleteKnowledgeResource,
  fetchKnowledgeResource,
  retryKnowledgeResourceVersion,
} from "../../src/api/knowledgeResources.ts";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const RESOURCE_ID = "00000000-0000-4000-8000-000000005001";
const VERSION_ID = "00000000-0000-4000-8000-000000006001";

const resource = {
  id: RESOURCE_ID,
  title: "运行手册.pdf",
  sourceType: "uploaded_file",
  createdAt: "2026-09-05T10:00:00Z",
  updatedAt: "2026-09-05T10:10:00Z",
  latestVersion: {
    id: VERSION_ID,
    status: "failed",
    mediaType: "application/pdf",
    sizeBytes: 2048,
    sha256: "a".repeat(64),
    sourceType: "uploaded_file",
    createdAt: "2026-09-05T10:00:00Z",
    processingStartedAt: "2026-09-05T10:02:00Z",
    readyAt: null,
    errorCode: "parser_failed",
    retryable: true,
  },
} as const;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("resource detail uses the generated credentialed GET boundary", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(resource, { status: 200 });
  }));

  await expect(fetchKnowledgeResource({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    signal: new AbortController().signal,
  })).resolves.toEqual(resource);

  expect(requests).toHaveLength(1);
  expect(requests[0]!.method).toBe("GET");
  expect(requests[0]!.credentials).toBe("include");
  expect(new URL(requests[0]!.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/resources/${RESOURCE_ID}`,
  );
});

test.each([
  ["detail schema", "detail", { title: "missing identity" }],
  ["detail resource", "detail", { ...resource, id: "00000000-0000-4000-8000-000000005099" }],
])("rejects %s contract mismatches", async (_name, _operation, body) => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(body, { status: 200 })));
  const signal = new AbortController().signal;

  const pending = fetchKnowledgeResource({ projectId: PROJECT_ID, resourceId: RESOURCE_ID, signal });

  await expect(pending).rejects.toMatchObject({ kind: "contract", retryable: false });
});

test("rejects an unexpected GET success status", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(resource, { status: 206 })));
  const common = { projectId: PROJECT_ID, resourceId: RESOURCE_ID, signal: new AbortController().signal };
  const pending = fetchKnowledgeResource(common);
  await expect(pending).rejects.toMatchObject({ kind: "contract", retryable: false });
});

test("treats malformed JSON on GET 200 as a nonretryable contract failure", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{broken", {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })));

  const pending = fetchKnowledgeResource({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    signal: new AbortController().signal,
  });

  await expect(pending).rejects.toMatchObject({ kind: "contract", retryable: false });
});

test("preserves detail HTTP correlation metadata", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({
    code: "database_unavailable", message: "知识服务暂时不可用", traceId: "trace-detail-503",
  }), { status: 503, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(fetchKnowledgeResource({ projectId: PROJECT_ID, resourceId: RESOURCE_ID,
    signal: new AbortController().signal })).rejects.toMatchObject({
    kind: "http",
    status: 503,
    code: "database_unavailable",
    traceId: "trace-detail-503",
  });
});

test("preserves Retry-After and a header trace for a non-JSON detail failure", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("private upstream body", {
    status: 503,
    headers: { "Retry-After": "19", "X-Request-ID": "trace-detail-header-503" },
  })));

  await expect(fetchKnowledgeResource({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "http",
    status: 503,
    message: "服务器返回 503",
    traceId: "trace-detail-header-503",
    retryAfterSeconds: 19,
  });
});

test("normalizes unknown thrown detail failures without exposing their value", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => {
    throw { privateCause: "socket-secret" };
  }));

  const pending = fetchKnowledgeResource({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    signal: new AbortController().signal,
  });

  await expect(pending).rejects.toMatchObject({
    kind: "network",
    message: "无法连接服务器，请检查网络",
    retryable: true,
  });
  await expect(pending).rejects.not.toMatchObject({ message: expect.stringContaining("socket-secret") });
});

test("maps an aborted resource detail without exposing its cause", async () => {
  const controller = new AbortController();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const signal = (input as Request).signal;
    return await new Promise<Response>((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), {
        once: true,
      });
    });
  }));
  const pending = fetchKnowledgeResource({ projectId: PROJECT_ID, resourceId: RESOURCE_ID,
    signal: controller.signal });
  controller.abort();
  await expect(pending).rejects.toMatchObject({ kind: "aborted", message: "请求已被取消" });
});

test("retry uses the exact generated credentialed POST boundary and validates the returned version", async () => {
  const requests: Request[] = [];
  const queued = {
    ...resource,
    updatedAt: "2026-09-05T10:11:00Z",
    latestVersion: {
      ...resource.latestVersion,
      status: "queued",
      processingStartedAt: null,
      errorCode: null,
      retryable: false,
    },
  } as const;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(queued, { status: 200 });
  }));

  await expect(retryKnowledgeResourceVersion({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    versionId: VERSION_ID,
    csrfToken: "csrf-current",
    signal: new AbortController().signal,
  })).resolves.toEqual(queued);

  expect(requests).toHaveLength(1);
  expect(requests[0]!.method).toBe("POST");
  expect(requests[0]!.credentials).toBe("include");
  expect(requests[0]!.headers.get("X-CSRF-Token")).toBe("csrf-current");
  expect(new URL(requests[0]!.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/resources/${RESOURCE_ID}/versions/${VERSION_ID}/retry`,
  );
});

test.each([
  ["unexpected status", Response.json(resource, { status: 201 })],
  ["malformed JSON", new Response("{broken", { status: 200 })],
  ["wrong resource", Response.json({ ...resource, id: "00000000-0000-4000-8000-000000005099" })],
  ["wrong version", Response.json({ ...resource, latestVersion: {
    ...resource.latestVersion, id: "00000000-0000-4000-8000-000000006099",
  } })],
])("retry rejects a %s as a nonretryable contract failure", async (_name, response) => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => response));

  await expect(retryKnowledgeResourceVersion({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    versionId: VERSION_ID,
    csrfToken: "csrf-current",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({ kind: "contract", retryable: false });
});

test("retry preserves safe HTTP correlation metadata and Retry-After", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("private upstream body", {
    status: 503,
    headers: { "Retry-After": "23", "X-Request-ID": "trace-retry-503" },
  })));

  await expect(retryKnowledgeResourceVersion({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    versionId: VERSION_ID,
    csrfToken: "csrf-current",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "http",
    status: 503,
    message: "服务器返回 503",
    traceId: "trace-retry-503",
    retryAfterSeconds: 23,
  });
});

test("delete uses the exact generated credentialed DELETE boundary and accepts only empty 204", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return new Response(null, { status: 204 });
  }));

  await expect(deleteKnowledgeResource({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    csrfToken: "csrf-current",
    signal: new AbortController().signal,
  })).resolves.toBeUndefined();

  expect(requests).toHaveLength(1);
  expect(requests[0]!.method).toBe("DELETE");
  expect(requests[0]!.credentials).toBe("include");
  expect(requests[0]!.headers.get("X-CSRF-Token")).toBe("csrf-current");
  expect(new URL(requests[0]!.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/resources/${RESOURCE_ID}`,
  );
});

test.each([200, 202, 206])("delete rejects unexpected success status %i", async (status) => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("unexpected", { status })));

  await expect(deleteKnowledgeResource({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    csrfToken: "csrf-current",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({ kind: "contract", retryable: false });
});

test("delete preserves a structured failure without treating it as removal", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    code: "csrf_invalid",
    message: "请求来源验证失败",
    traceId: "trace-delete-403",
  }, { status: 403 })));

  await expect(deleteKnowledgeResource({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    csrfToken: "csrf-current",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "http",
    status: 403,
    code: "csrf_invalid",
    message: "请求来源验证失败",
    traceId: "trace-delete-403",
  });
});

test.each([
  ["retry", retryKnowledgeResourceVersion, { versionId: VERSION_ID }],
  ["delete", deleteKnowledgeResource, {}],
] as const)("maps an aborted %s operation without exposing its cause", async (
  _name,
  operation,
  extra,
) => {
  const controller = new AbortController();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const requestSignal = (input as Request).signal;
    return await new Promise<Response>((_resolve, reject) => {
      requestSignal.addEventListener(
        "abort",
        () => reject(new DOMException("private abort reason", "AbortError")),
        { once: true },
      );
    });
  }));
  const pending = operation({
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    csrfToken: "csrf-current",
    signal: controller.signal,
    ...extra,
  } as never);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ kind: "aborted", message: "请求已被取消" });
});
