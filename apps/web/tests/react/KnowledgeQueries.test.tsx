import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";

import { knowledgeKeys, useKnowledgeSearchQuery } from "../../src/queries/knowledge.ts";

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper(client: QueryClient) {
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
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
