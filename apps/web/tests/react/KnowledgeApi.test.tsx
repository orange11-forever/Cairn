import { afterEach, expect, test, vi } from "vitest";

import { fetchKnowledgeResources } from "../../src/api/knowledge.ts";

function requestDetails(input: RequestInfo | URL) {
  const request = input as Request;
  return { url: new URL(request.url), method: request.method, headers: request.headers, request };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("knowledge resource pages reject malformed successful responses", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ items: [], nextCursor: null })),
  );
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  await expect(fetchKnowledgeResources({
    projectId: "00000000-0000-4000-8000-000000004001",
    cursor: null,
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "contract",
    context: "GET /api/v1/projects/{project_id}/knowledge/resources",
  });
});

test("knowledge resource failures preserve the normalized API error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({
      code: "database_unavailable",
      message: "知识服务暂时不可用",
      traceId: "trace-knowledge-503",
    }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    })),
  );

  await expect(fetchKnowledgeResources({
    projectId: "00000000-0000-4000-8000-000000004001",
    cursor: null,
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "http",
    status: 503,
    code: "database_unavailable",
    message: "知识服务暂时不可用",
    traceId: "trace-knowledge-503",
    context: "GET /api/v1/projects/{project_id}/knowledge/resources",
  });
});

test("knowledge resource requests preserve session cancellation", async () => {
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      requestSignal = (input as Request).signal;
      return await new Promise<Response>((_resolve, reject) => {
        requestSignal?.addEventListener(
          "abort",
          () => reject(requestSignal?.reason ?? new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    }),
  );
  const controller = new AbortController();

  const pending = fetchKnowledgeResources({
    projectId: "00000000-0000-4000-8000-000000004001",
    cursor: null,
    signal: controller.signal,
  });
  await vi.waitFor(() => expect(requestSignal).toBeDefined());
  controller.abort();

  await expect(pending).rejects.toMatchObject({
    kind: "aborted",
    context: "GET /api/v1/projects/{project_id}/knowledge/resources",
  });
});

test("knowledge resource requests normalize infrastructure failures", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => { throw new TypeError("socket closed"); }),
  );

  await expect(fetchKnowledgeResources({
    projectId: "00000000-0000-4000-8000-000000004001",
    cursor: null,
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "network",
    message: "无法连接服务器，请检查网络",
    context: "GET /api/v1/projects/{project_id}/knowledge/resources",
  });
});

test("knowledge search posts the generated request with session CSRF", async () => {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(input as Request);
      return Response.json({
        retrievalMode: "hybrid",
        results: [{
          chunkId: "00000000-0000-4000-8000-000000006001",
          excerpt: "原子发布只暴露完整索引。",
          locator: { type: "pdf", page: 3 },
          mediaType: "application/pdf",
          resourceId: "00000000-0000-4000-8000-000000007001",
          resourceVersionId: "00000000-0000-4000-8000-000000008001",
          score: 0.92,
          title: "索引设计",
        }],
      });
    }),
  );
  const knowledgeApi = await import("../../src/api/knowledge.ts");
  const maybeSearch = Reflect.get(knowledgeApi, "searchKnowledge");
  expect(maybeSearch).toBeTypeOf("function");
  const searchKnowledge = maybeSearch as (input: {
    projectId: string;
    query: string;
    limit: number;
    csrfToken: string;
    signal: AbortSignal;
  }) => Promise<{ retrievalMode: string; results: unknown[] }>;

  const response = await searchKnowledge({
    projectId: "00000000-0000-4000-8000-000000004001",
    query: "原子索引",
    limit: 12,
    csrfToken: "csrf-knowledge-token",
    signal: new AbortController().signal,
  });

  expect(response.retrievalMode).toBe("hybrid");
  expect(response.results).toHaveLength(1);
  expect(calls).toHaveLength(1);
  const { url, method, headers, request } = requestDetails(calls[0] as Request);
  expect(url.pathname).toBe(
    "/api/v1/projects/00000000-0000-4000-8000-000000004001/knowledge/search",
  );
  expect(method).toBe("POST");
  expect(headers.get("X-CSRF-Token")).toBe("csrf-knowledge-token");
  await expect(request.json()).resolves.toEqual({ query: "原子索引", limit: 12 });
});

test("knowledge search rejects unsupported retrieval modes", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ retrievalMode: "semantic", results: [] })),
  );
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const { searchKnowledge } = await import("../../src/api/knowledge.ts");

  await expect(searchKnowledge({
    projectId: "00000000-0000-4000-8000-000000004001",
    query: "发布边界",
    limit: 8,
    csrfToken: "csrf-knowledge-token",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "contract",
    context: "POST /api/v1/projects/{project_id}/knowledge/search",
  });
});

test("knowledge search preserves rate-limit errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({
      code: "rate_limited",
      message: "搜索请求过于频繁",
      traceId: "trace-search-429",
    }), {
      status: 429,
      headers: { "Content-Type": "application/json", "Retry-After": "17" },
    })),
  );
  const { searchKnowledge } = await import("../../src/api/knowledge.ts");

  await expect(searchKnowledge({
    projectId: "00000000-0000-4000-8000-000000004001",
    query: "租约",
    limit: 8,
    csrfToken: "csrf-knowledge-token",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "http",
    status: 429,
    code: "rate_limited",
    message: "搜索请求过于频繁",
    traceId: "trace-search-429",
    retryAfterSeconds: 17,
    context: "POST /api/v1/projects/{project_id}/knowledge/search",
  });
});

test("knowledge search ignores malformed retry-after values", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({
      code: "rate_limited",
      message: "搜索请求过于频繁",
      traceId: "trace-search-invalid-retry",
    }), {
      status: 429,
      headers: { "Content-Type": "application/json", "Retry-After": "17.5" },
    })),
  );
  const { searchKnowledge } = await import("../../src/api/knowledge.ts");

  await expect(searchKnowledge({
    projectId: "00000000-0000-4000-8000-000000004001",
    query: "租约",
    limit: 8,
    csrfToken: "csrf-knowledge-token",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "http",
    status: 429,
    retryAfterSeconds: null,
  });
});

test("knowledge search preserves session cancellation", async () => {
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      requestSignal = (input as Request).signal;
      return await new Promise<Response>((_resolve, reject) => {
        requestSignal?.addEventListener(
          "abort",
          () => reject(requestSignal?.reason ?? new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    }),
  );
  const { searchKnowledge } = await import("../../src/api/knowledge.ts");
  const controller = new AbortController();

  const pending = searchKnowledge({
    projectId: "00000000-0000-4000-8000-000000004001",
    query: "权限撤销",
    limit: 8,
    csrfToken: "csrf-knowledge-token",
    signal: controller.signal,
  });
  await vi.waitFor(() => expect(requestSignal).toBeDefined());
  controller.abort();

  await expect(pending).rejects.toMatchObject({
    kind: "aborted",
    context: "POST /api/v1/projects/{project_id}/knowledge/search",
  });
});
