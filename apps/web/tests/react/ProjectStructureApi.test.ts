import { afterEach, expect, test, vi } from "vitest";
import { createStage, updateStage, fetchStages, createMilestone, updateMilestone, fetchMilestones } from "../../src/api/projects.ts";
const projectId = "00000000-0000-4000-8000-000000004001";
const objectId = "00000000-0000-4000-8000-000000006001";
const signal = () => new AbortController().signal;
const stage = {
  archived: false,
  id: objectId,
  projectId,
  revision: 1,
  name: "Design",
  position: 0,
  createdAt: "2026-10-08T00:00:00Z",
  updatedAt: "2026-10-08T00:00:00Z"
};
const milestone = {
  ...stage,
  description: null,
  acceptanceCriteria: null,
  dueAt: null,
  stageId: null
};
const operations = [{
  name: "stage list",
  method: "GET",
  path: "stages",
  status: 200,
  data: {
    items: [stage],
    nextCursor: null
  },
  call: (actionSignal: AbortSignal) => fetchStages({
    projectId,
    cursor: "next",
    signal: actionSignal
  })
}, {
  name: "milestone list",
  method: "GET",
  path: "milestones",
  status: 200,
  data: {
    items: [milestone],
    nextCursor: null
  },
  call: (actionSignal: AbortSignal) => fetchMilestones({
    projectId,
    cursor: null,
    signal: actionSignal
  })
}, {
  name: "stage create",
  method: "POST",
  path: "stages",
  status: 201,
  data: stage,
  call: (actionSignal: AbortSignal) => createStage({
    projectId,
    body: {
      name: "Design",
      position: 0,
      expectedProjectRevision: 1
    },
    csrfToken: "csrf",
    signal: actionSignal
  })
}, {
  name: "milestone create",
  method: "POST",
  path: "milestones",
  status: 201,
  data: milestone,
  call: (actionSignal: AbortSignal) => createMilestone({
    projectId,
    body: {
      name: "Review",
      stageId: null,
      expectedProjectRevision: 1
    },
    csrfToken: "csrf",
    signal: actionSignal
  })
}, {
  name: "stage edit",
  method: "PATCH",
  path: `stages/${objectId}`,
  status: 200,
  data: stage,
  call: (actionSignal: AbortSignal) => updateStage({
    projectId,
    objectId,
    body: {
      name: "Ready",
      expectedRevision: 1,
      expectedProjectRevision: 2
    },
    csrfToken: "csrf",
    signal: actionSignal
  })
}, {
  name: "milestone edit",
  method: "PATCH",
  path: `milestones/${objectId}`,
  status: 200,
  data: milestone,
  call: (actionSignal: AbortSignal) => updateMilestone({
    projectId,
    objectId,
    body: {
      description: null,
      dueAt: null,
      stageId: null,
      acceptanceCriteria: null,
      expectedRevision: 1,
      expectedProjectRevision: 2
    },
    csrfToken: "csrf",
    signal: actionSignal
  })
}];
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
test.each(operations)("$name uses the scoped credentialed generated request", async operation => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: Request) => {
    requests.push(input);
    return Response.json(operation.data, {
      status: operation.status
    });
  }));
  await expect(operation.call(signal())).resolves.toEqual(operation.data);
  const request = requests[0]!;
  expect(request.method).toBe(operation.method);
  expect(request.credentials).toBe("include");
  expect(new URL(request.url).pathname).toBe(`/api/v1/projects/${projectId}/${operation.path}`);
  if (operation.method !== "GET") {
    expect(request.headers.get("X-CSRF-Token")).toBe("csrf");
    expect(await request.json()).toMatchObject({
      expectedProjectRevision: operation.method === "POST" ? 1 : 2
    });
  }
});
test.each(operations)("$name rejects malformed successful JSON as a contract failure", async operation => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{broken", {
    status: operation.status,
    headers: {
      "Content-Type": "application/json"
    }
  })));
  await expect(operation.call(signal())).rejects.toMatchObject({
    kind: "contract",
    retryable: false
  });
});
test.each(operations)("$name preserves traced HTTP failure and distinguishes network/abort", async operation => {
  for (const status of [401, 403, 404, 409, 422, 503, 500]) {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({
      code: "failed",
      message: "Failure",
      traceId: `r-${status}`
    }, {
      status
    })));
    await expect(operation.call(signal())).rejects.toMatchObject({
      kind: "http",
      status,
      traceId: `r-${status}`
    });
  }
  vi.stubGlobal("fetch", vi.fn(async () => {
    throw new Error("connection lost");
  }));
  await expect(operation.call(signal())).rejects.toMatchObject({
    kind: "network"
  });
  const controller = new AbortController();
  controller.abort();
  await expect(operation.call(controller.signal)).rejects.toMatchObject({
    kind: "aborted"
  });
});
test.each(operations)("$name rejects a response from another project", async operation => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const foreign = {
    ...stage,
    ...milestone,
    projectId: "00000000-0000-4000-8000-000000004002"
  };
  const body = operation.method === "GET" ? {
    items: [foreign],
    nextCursor: null
  } : foreign;
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(body, {
    status: operation.status
  })));
  await expect(operation.call(signal())).rejects.toMatchObject({
    kind: "contract"
  });
});
