import { afterEach, expect, test, vi } from "vitest";

import { fetchProject } from "../../src/api/projects.ts";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const project = {
  id: PROJECT_ID,
  name: "核心攫取验收",
  description: "真实项目名称",
  createdAt: "2026-08-01T08:00:00Z",
  updatedAt: "2026-08-08T08:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("project detail uses the generated credentialed GET and validates its identity", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(project);
  }));

  await expect(fetchProject({ projectId: PROJECT_ID, signal: new AbortController().signal }))
    .resolves.toEqual(project);
  expect(requests).toHaveLength(1);
  expect(requests[0]!.credentials).toBe("include");
  expect(requests[0]!.method).toBe("GET");
  expect(new URL(requests[0]!.url).pathname).toBe(`/api/v1/projects/${PROJECT_ID}`);
});

test.each([
  ["wrong identity", Response.json({ ...project, id: "00000000-0000-4000-8000-000000004099" })],
  ["invalid schema", Response.json({ ...project, updatedAt: "invalid" })],
  ["unexpected success", Response.json(project, { status: 206 })],
])("project detail rejects %s as a contract failure", async (_name, response) => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => response));
  await expect(fetchProject({ projectId: PROJECT_ID, signal: new AbortController().signal }))
    .rejects.toMatchObject({ kind: "contract", retryable: false });
});

test("project detail treats malformed successful JSON as a contract failure", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{malformed", {
    status: 200, headers: { "Content-Type": "application/json" },
  })));
  await expect(fetchProject({ projectId: PROJECT_ID, signal: new AbortController().signal }))
    .rejects.toMatchObject({ kind: "contract", retryable: false });
});

test.each([401, 404, 503])("project detail preserves HTTP %s and trace ID", async (status) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    code: "not_found", message: "项目不可用", traceId: `trace-${status}`,
  }), { status, headers: { "Content-Type": "application/json" } })));
  await expect(fetchProject({ projectId: PROJECT_ID, signal: new AbortController().signal }))
    .rejects.toMatchObject({ kind: "http", status, traceId: `trace-${status}` });
});

test("project detail distinguishes network and abort", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("private network cause"); }));
  await expect(fetchProject({ projectId: PROJECT_ID, signal: new AbortController().signal }))
    .rejects.toMatchObject({ kind: "network", retryable: true });
  const controller = new AbortController();
  controller.abort();
  await expect(fetchProject({ projectId: PROJECT_ID, signal: controller.signal }))
    .rejects.toMatchObject({ kind: "aborted" });
});

test("an aborted project-detail request cannot surface a late session-invalid 401", async () => {
  const controller = new AbortController();
  let release!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { release = resolve; })));
  const pending = fetchProject({ projectId: PROJECT_ID, signal: controller.signal });
  controller.abort();
  release(new Response(JSON.stringify({ code: "session_invalid", message: "已过期", traceId: "late" }), {
    status: 401, headers: { "Content-Type": "application/json" },
  }));
  await expect(pending).rejects.toMatchObject({ kind: "aborted" });
});
