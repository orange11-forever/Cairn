import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";

import {
  knowledgeKeys,
  useKnowledgeChunkContextQuery,
  useKnowledgeSearchQuery,
} from "../../src/queries/knowledge.ts";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const RESOURCE_ID = "00000000-0000-4000-8000-000000005001";
const RESOURCE_VERSION_ID = "00000000-0000-4000-8000-000000006001";
const CHUNK_ID = "00000000-0000-4000-8000-000000007001";
const validContext = {
  resourceId: RESOURCE_ID,
  resourceVersionId: RESOURCE_VERSION_ID,
  before: null,
  hit: {
    id: CHUNK_ID,
    ordinal: 1,
    text: "命中原文",
    locator: { type: "pdf", page: 2 },
  },
  after: null,
} as const;

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper(client: QueryClient) {
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("knowledge resource caches stay isolated across organizations", () => {
  const queryClient = new QueryClient();
  const projectId = "00000000-0000-4000-8000-000000004001";
  const organizationA = "00000000-0000-4000-8000-000000002001";
  const organizationB = "00000000-0000-4000-8000-000000002002";

  queryClient.setQueryData(
    knowledgeKeys.resources(organizationA, projectId),
    { pages: [{ items: [{ title: "组织 A 私有资料" }] }] },
  );

  expect(queryClient.getQueryData(
    knowledgeKeys.resources(organizationB, projectId),
  )).toBeUndefined();
});

test("knowledge search keys isolate tenant and search inputs", () => {
  const maybeSearchKey = Reflect.get(knowledgeKeys, "search");
  expect(maybeSearchKey).toBeTypeOf("function");
  const searchKey = maybeSearchKey as (
    organizationId: string,
    projectId: string,
    query: string,
    limit: number,
  ) => readonly unknown[];
  const projectId = "00000000-0000-4000-8000-000000004001";

  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-b", projectId, "租约", 8),
  );
  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-a", projectId, "索引", 8),
  );
  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-a", projectId, "租约", 20),
  );
});

test("citation context keys isolate tenant, project, resource version, and chunk", () => {
  expect(knowledgeKeys.searches("org-a", "project-a")).toEqual([
    "project-knowledge", "org-a", "project-a", "search",
  ]);
  expect(knowledgeKeys.citationContext(
    "org-a", "project-a", "resource-a", "version-a", "chunk-a",
  )).toEqual([
    "project-knowledge",
    "org-a",
    "project-a",
    "citation-context",
    "resource-a",
    "version-a",
    "chunk-a",
  ]);
  expect(knowledgeKeys.citationContext(
    "org-b", "project-a", "resource-a", "version-a", "chunk-a",
  )).not.toEqual(knowledgeKeys.citationContext(
    "org-a", "project-a", "resource-a", "version-a", "chunk-a",
  ));
});

test("the citation hook requests the exact citation and stores it under its full key", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(validContext);
  }));
  const client = queryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeChunkContextQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(requests).toHaveLength(1);
  expect(new URL(requests[0]!.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/resources/${RESOURCE_ID}/chunks/${CHUNK_ID}`,
  );
  expect(client.getQueryData(knowledgeKeys.citationContext(
    "org-a", PROJECT_ID, RESOURCE_ID, RESOURCE_VERSION_ID, CHUNK_ID,
  ))).toEqual(validContext);
});

test("remounting a citation context always reauthorizes", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(validContext);
  }));
  const client = queryClient();
  const session = new AbortController();
  const props = {
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  };

  const first = renderHook(() => useKnowledgeChunkContextQuery(props), {
    wrapper: wrapper(client),
  });
  await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
  first.unmount();
  const second = renderHook(() => useKnowledgeChunkContextQuery(props), {
    wrapper: wrapper(client),
  });
  await waitFor(() => expect(requests).toHaveLength(2));
  await waitFor(() => expect(second.result.current.isSuccess).toBe(true));
});

test("session abort cancels a pending citation context request", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    return await new Promise<Response>((_resolve, reject) => {
      request.signal.addEventListener("abort", () => {
        reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
  }));
  const session = new AbortController();
  const client = queryClient();
  renderHook(() => useKnowledgeChunkContextQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await waitFor(() => expect(requests).toHaveLength(1));
  session.abort(new DOMException("Session ended", "AbortError"));
  await waitFor(() => expect(requests[0]!.signal.aborted).toBe(true));
});

test("unmounting a citation context aborts its pending Query request", async () => {
  const requests: Request[] = [];
  const fetchSettled = deferred<void>();
  let resolveFetch: ((response: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    try {
      return await new Promise<Response>((resolve, reject) => {
        resolveFetch = resolve;
        request.signal.addEventListener("abort", () => {
          reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
        }, { once: true });
      });
    } finally {
      fetchSettled.resolve();
    }
  }));
  const session = new AbortController();
  const client = queryClient();
  const rendered = renderHook(() => useKnowledgeChunkContextQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await waitFor(() => expect(requests).toHaveLength(1));

  try {
    rendered.unmount();
    await waitFor(() => expect(requests[0]!.signal.aborted).toBe(true));
  } finally {
    resolveFetch?.(Response.json(validContext));
    await fetchSettled.promise;
    await vi.waitFor(() => expect(client.isFetching()).toBe(0));
  }
});

test("knowledge search stays idle until a submitted search exists", () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();

  const { result } = renderHook(() => useKnowledgeSearchQuery({
    organizationId: "org-a",
    projectId: "00000000-0000-4000-8000-000000004001",
    search: null,
    csrfToken: "csrf-search",
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });

  expect(result.current.fetchStatus).toBe("idle");
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("knowledge search queries isolate organization, project, query, and limit caches", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json({ retrievalMode: "hybrid", results: [] });
  }));
  const client = queryClient();
  const session = new AbortController();
  const cases = [
    { organizationId: "org-a", projectId: "project-a", query: "租约", limit: 8 },
    { organizationId: "org-b", projectId: "project-a", query: "租约", limit: 8 },
    { organizationId: "org-a", projectId: "project-b", query: "租约", limit: 8 },
    { organizationId: "org-a", projectId: "project-a", query: "索引", limit: 8 },
    { organizationId: "org-a", projectId: "project-a", query: "租约", limit: 20 },
  ];

  for (const searchCase of cases) {
    const rendered = renderHook(() => useKnowledgeSearchQuery({
      organizationId: searchCase.organizationId,
      projectId: searchCase.projectId,
      search: { query: searchCase.query, limit: searchCase.limit },
      csrfToken: "csrf-search",
      sessionSignal: session.signal,
    }), { wrapper: wrapper(client) });
    await waitFor(() => expect(rendered.result.current.isSuccess).toBe(true));
    rendered.unmount();
  }

  expect(requests).toHaveLength(cases.length);
  for (const searchCase of cases) {
    expect(client.getQueryData(knowledgeKeys.search(
      searchCase.organizationId,
      searchCase.projectId,
      searchCase.query,
      searchCase.limit,
    ))).toEqual({ retrievalMode: "hybrid", results: [] });
  }
  expect(new URL(requests[0]?.url ?? "").pathname).toContain("/projects/project-a/knowledge/search");
  expect(requests[0]?.headers.get("X-CSRF-Token")).toBe("csrf-search");
});

test("knowledge search queries preserve session cancellation", async () => {
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requestSignal = (input as Request).signal;
    return await new Promise<Response>((_resolve, reject) => {
      requestSignal?.addEventListener(
        "abort",
        () => reject(requestSignal?.reason ?? new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    });
  }));
  const client = queryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeSearchQuery({
    organizationId: "org-a",
    projectId: "project-a",
    search: { query: "权限撤销", limit: 8 },
    csrfToken: "csrf-search",
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await waitFor(() => expect(requestSignal).toBeDefined());

  act(() => session.abort());

  await waitFor(() => expect(result.current.error).toMatchObject({
    kind: "aborted",
    context: "POST /api/v1/projects/{project_id}/knowledge/search",
  }));
});

test("switching submitted search aborts the old Query and observes only the new response", async () => {
  const requests: Request[] = [];
  const queryA = deferred<Response>();
  const lateResponseConsumed = deferred<void>();
  const lateResponse = Response.json({ retrievalMode: "keyword_fallback", results: [] });
  const readLateResponse = lateResponse.text.bind(lateResponse);
  vi.spyOn(lateResponse, "text").mockImplementation(async () => {
    const body = await readLateResponse();
    lateResponseConsumed.resolve();
    return body;
  });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const body = await request.clone().json() as { query: string };
    return body.query === "查询甲"
      ? queryA.promise
      : Response.json({ retrievalMode: "hybrid", results: [] });
  }));
  const client = queryClient();
  const session = new AbortController();
  const { result, rerender } = renderHook(
    ({ query }) => useKnowledgeSearchQuery({
      organizationId: "org-a",
      projectId: "project-a",
      search: { query, limit: 10 },
      csrfToken: "csrf-search",
      sessionSignal: session.signal,
    }),
    { initialProps: { query: "查询甲" }, wrapper: wrapper(client) },
  );
  await waitFor(() => expect(requests).toHaveLength(1));
  rerender({ query: "查询乙" });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(requests[0]!.signal.aborted).toBe(true);
  await act(async () => {
    queryA.resolve(lateResponse);
    await lateResponseConsumed.promise;
  });
  expect(lateResponse.bodyUsed).toBe(true);
  await waitFor(() => {
    expect(result.current.data).toEqual({ retrievalMode: "hybrid", results: [] });
  });
});
