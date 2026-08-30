import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, expect, test, vi } from "vitest";

import { ApiError } from "../../src/api/errors.ts";
import { shouldRetry } from "../../src/app/queryClient.ts";
import { KnowledgeCitationContext } from "../../src/components/knowledge/KnowledgeCitationContext.tsx";
import { KnowledgeSearch } from "../../src/components/knowledge/KnowledgeSearch.tsx";

const ORGANIZATION_ID = "00000000-0000-4000-8000-000000002001";
const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const RESOURCE_ID = "00000000-0000-4000-8000-000000005001";
const VERSION_ID = "00000000-0000-4000-8000-000000006001";
const CHUNK_ID = "00000000-0000-4000-8000-000000007001";

const citation = {
  resourceId: RESOURCE_ID,
  resourceVersionId: VERSION_ID,
  chunkId: CHUNK_ID,
  title: "运行手册.pdf",
  mediaType: "application/pdf",
  excerpt: "搜索摘录",
  locator: { type: "pdf", page: 2 },
  score: 0.9,
} as const;

const context = {
  resourceId: RESOURCE_ID,
  resourceVersionId: VERSION_ID,
  before: {
    id: "00000000-0000-4000-8000-000000007000",
    ordinal: 1,
    text: "前文<script data-hostile>never-run</script>",
    locator: { type: "pdf", page: 1 },
  },
  hit: {
    id: CHUNK_ID,
    ordinal: 2,
    text: "命中第一行\n命中第二行",
    locator: { type: "pdf", page: 2 },
  },
  after: {
    id: "00000000-0000-4000-8000-000000007002",
    ordinal: 3,
    text: `后文${"无空格".repeat(160)}`,
    locator: { type: "pdf", page: 3 },
  },
} as const;

function renderSearch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: shouldRetry, retryDelay: 0 } },
  });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <KnowledgeSearch
          organizationId={ORGANIZATION_ID}
          projectId={PROJECT_ID}
          csrfToken="csrf-context-test"
          sessionSignal={new AbortController().signal}
          onAccessUnavailable={vi.fn()}
        />
      </QueryClientProvider>,
    ),
  };
}

async function submitSearch(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("搜索项目知识"), "引用上下文");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  await screen.findByText("搜索摘录");
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("loads ordered plain-text context only while expanded and exposes the API download entry", async () => {
  const requests: Request[] = [];
  let resolveReauthorization!: (response: Response) => void;
  const reauthorization = new Promise<Response>((resolve) => {
    resolveReauthorization = resolve;
  });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "POST") {
      return Response.json({ retrievalMode: "hybrid", results: [citation] });
    }
    return requests.filter((candidate) => candidate.method === "GET").length === 1
      ? Response.json(context)
      : reauthorization;
  }));
  const user = userEvent.setup();
  const { container } = renderSearch();
  await submitSearch(user);

  const toggle = screen.getByRole("button", { name: "查看引用上下文" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveAttribute("aria-controls");
  expect(requests.filter((request) => request.method === "GET")).toHaveLength(0);
  expect(screen.queryByRole("link", { name: "下载原文件（新标签页）" })).toBeNull();

  await user.click(toggle);
  const panel = await screen.findByRole("region", { name: "引用上下文" });
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(panel).toHaveAttribute("id", toggle.getAttribute("aria-controls"));
  const labels = within(panel).getAllByText(/^(前文|命中片段|后文)$/);
  expect(labels.map((node) => node.textContent)).toEqual(["前文", "命中片段", "后文"]);
  expect(within(panel).getByText("第 1 页")).toBeInTheDocument();
  expect(within(panel).getByText("第 2 页")).toBeInTheDocument();
  expect(within(panel).getByText("第 3 页")).toBeInTheDocument();
  expect(within(panel).getByText(/命中第一行\s+命中第二行/)).toBeInTheDocument();
  expect(container.querySelector("script, img, iframe, object, embed")).toBeNull();
  const download = within(panel).getByRole("link", { name: "下载原文件（新标签页）" });
  const identityOrigin = new URL(
    import.meta.env.VITE_IDENTITY_API_URL ?? "http://localhost:8080",
  ).origin;
  expect(download).toHaveAttribute(
    "href",
    `${identityOrigin}/api/v1/projects/${PROJECT_ID}/knowledge/resources/${RESOURCE_ID}/download`,
  );
  expect(download).toHaveAttribute("target", "_blank");
  expect(download).toHaveAttribute("rel", "noopener noreferrer");

  await user.click(screen.getByRole("button", { name: "收起引用上下文" }));
  expect(screen.queryByRole("region", { name: "引用上下文" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  await waitFor(() => {
    expect(requests.filter((request) => request.method === "GET")).toHaveLength(2);
  });
  const reauthorizingPanel = screen.getByRole("region", { name: "引用上下文" });
  const refreshedContext = {
    ...context,
    hit: { ...context.hit, text: "重新授权后的命中片段" },
  } as const;
  try {
    expect(reauthorizingPanel).toHaveAttribute("aria-busy", "true");
    expect(within(reauthorizingPanel).getByRole("status")).toHaveTextContent(
      "正在加载引用上下文",
    );
    expect(within(reauthorizingPanel).queryByText(/命中第一行\s+命中第二行/))
      .toBeNull();
    expect(within(reauthorizingPanel).queryByRole(
      "link",
      { name: "下载原文件（新标签页）" },
    )).toBeNull();

    resolveReauthorization(Response.json(refreshedContext));
    expect(await within(reauthorizingPanel).findByText("重新授权后的命中片段"))
      .toBeInTheDocument();
    expect(reauthorizingPanel).not.toHaveAttribute("aria-busy");
    expect(within(reauthorizingPanel).getByRole(
      "link",
      { name: "下载原文件（新标签页）" },
    )).toBeInTheDocument();
  } finally {
    resolveReauthorization(Response.json(refreshedContext));
  }
});

test("a persistent 503 retries once, shows trace ID, and supports manual reload", async () => {
  let contextAttempts = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "POST") {
      return Response.json({ retrievalMode: "hybrid", results: [citation] });
    }
    contextAttempts += 1;
    if (contextAttempts <= 2) {
      return new Response(JSON.stringify({
        code: "database_unavailable",
        message: "引用服务暂时不可用",
        traceId: "trace-context-503",
      }), { status: 503, headers: { "Content-Type": "application/json" } });
    }
    return Response.json(context);
  }));
  const user = userEvent.setup();
  renderSearch();
  await submitSearch(user);
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("引用服务暂时不可用");
  expect(screen.getByText("请求编号：trace-context-503")).toBeInTheDocument();
  expect(contextAttempts).toBe(2);
  await user.click(screen.getByRole("button", { name: "重新加载引用上下文" }));
  expect(await screen.findByText(/命中第一行\s+命中第二行/)).toBeInTheDocument();
  expect(contextAttempts).toBe(3);
});

test("a contract mismatch never renders foreign text or offers retry", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    return request.method === "POST"
      ? Response.json({ retrievalMode: "hybrid", results: [citation] })
      : Response.json({
          ...context,
          resourceVersionId: "00000000-0000-4000-8000-000000006099",
          hit: { ...context.hit, text: "foreign-resource-secret" },
        });
  }));
  const user = userEvent.setup();
  renderSearch();
  await submitSearch(user);
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "服务器返回的数据格式不正确，请联系管理员",
  );
  expect(screen.queryByText("foreign-resource-secret")).toBeNull();
  expect(screen.queryByRole("button", { name: "重新加载引用上下文" })).toBeNull();
  expect(screen.queryByRole("link", { name: "下载原文件（新标签页）" })).toBeNull();
});

test("a citation 404 refetches resources once and only marks searches stale", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    return request.method === "POST"
      ? Response.json({ retrievalMode: "hybrid", results: [citation] })
      : new Response(JSON.stringify({
          code: "not_found",
          message: "不可见资源",
          traceId: "trace-context-404",
        }), { status: 404, headers: { "Content-Type": "application/json" } });
  }));
  const user = userEvent.setup();
  const { client } = renderSearch();
  const refetch = vi.spyOn(client, "refetchQueries");
  const invalidate = vi.spyOn(client, "invalidateQueries");
  await submitSearch(user);
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "该引用已不可用，请重新搜索",
  );
  await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1));
  expect(refetch).toHaveBeenCalledWith({
    queryKey: ["project-knowledge", ORGANIZATION_ID, PROJECT_ID, "resources"],
    exact: true,
    type: "active",
  });
  expect(invalidate).toHaveBeenCalledTimes(1);
  expect(invalidate).toHaveBeenCalledWith({
    queryKey: ["project-knowledge", ORGANIZATION_ID, PROJECT_ID, "search"],
    refetchType: "none",
  });
  await user.click(screen.getByRole("button", { name: "收起引用上下文" }));
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  await screen.findByRole("alert");
  await waitFor(() => expect(refetch).toHaveBeenCalledTimes(2));
  expect(invalidate).toHaveBeenCalledTimes(2);
});

test("delivers each 404 object once across StrictMode effect replay", async () => {
  const firstError = new ApiError("http", "首次不可见资源", {
    status: 404,
    code: "not_found",
    traceId: "trace-context-404-first",
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const citationKey = [
    "project-knowledge",
    ORGANIZATION_ID,
    PROJECT_ID,
    "citation-context",
    RESOURCE_ID,
    VERSION_ID,
    CHUNK_ID,
  ] as const;
  client.setQueryData(citationKey, context);
  const cachedQuery = client.getQueryCache().find({
    queryKey: citationKey,
    exact: true,
  });
  if (cachedQuery === undefined) throw new Error("citation cache setup failed");
  cachedQuery.setState({
    error: firstError,
    errorUpdatedAt: Date.now(),
    fetchStatus: "idle",
    status: "error",
  });

  const pendingRequests: Array<{
    request: Request;
    resolve(response: Response): void;
  }> = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    return await new Promise<Response>((resolve, reject) => {
      pendingRequests.push({ request, resolve });
      request.signal.addEventListener("abort", () => {
        reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
  }));
  const refetch = vi.spyOn(client, "refetchQueries");
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const rendered = render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <KnowledgeCitationContext
          id="strict-context"
          organizationId={ORGANIZATION_ID}
          projectId={PROJECT_ID}
          citation={citation}
          sessionSignal={new AbortController().signal}
        />
      </QueryClientProvider>
    </StrictMode>,
  );

  try {
    await waitFor(() => expect(refetch).toHaveBeenCalledTimes(1));
    expect(refetch).toHaveBeenNthCalledWith(1, {
      queryKey: ["project-knowledge", ORGANIZATION_ID, PROJECT_ID, "resources"],
      exact: true,
      type: "active",
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenNthCalledWith(1, {
      queryKey: ["project-knowledge", ORGANIZATION_ID, PROJECT_ID, "search"],
      refetchType: "none",
    });
    await waitFor(() => {
      expect(pendingRequests.filter(({ request }) => !request.signal.aborted))
        .toHaveLength(1);
    });

    const activeRequest = pendingRequests.find(({ request }) => !request.signal.aborted);
    if (activeRequest === undefined) throw new Error("active citation request missing");
    activeRequest.resolve(new Response(JSON.stringify({
      code: "not_found",
      message: "再次不可见资源",
      traceId: "trace-context-404-second",
    }), { status: 404, headers: { "Content-Type": "application/json" } }));

    await waitFor(() => expect(refetch).toHaveBeenCalledTimes(2));
    expect(refetch).toHaveBeenNthCalledWith(2, {
      queryKey: ["project-knowledge", ORGANIZATION_ID, PROJECT_ID, "resources"],
      exact: true,
      type: "active",
    });
    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(invalidate).toHaveBeenNthCalledWith(2, {
      queryKey: ["project-knowledge", ORGANIZATION_ID, PROJECT_ID, "search"],
      refetchType: "none",
    });
    expect(await screen.findByText("请求编号：trace-context-404-second"))
      .toBeInTheDocument();
  } finally {
    for (const pending of pendingRequests) {
      if (!pending.request.signal.aborted) {
        pending.resolve(Response.json(context));
      }
    }
    rendered.unmount();
    await vi.waitFor(() => expect(client.isFetching()).toBe(0));
  }
});

test("collapsing aborts a pending context without rendering an abort error", async () => {
  let contextRequest: Request | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "POST") {
      return Response.json({ retrievalMode: "hybrid", results: [citation] });
    }
    contextRequest = request;
    return await new Promise<Response>((_resolve, reject) => {
      request.signal.addEventListener("abort", () => {
        reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
  }));
  const user = userEvent.setup();
  renderSearch();
  await submitSearch(user);
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  expect(await screen.findByRole("status")).toHaveTextContent("正在加载引用上下文");
  await user.click(screen.getByRole("button", { name: "收起引用上下文" }));
  await waitFor(() => expect(contextRequest?.signal.aborted).toBe(true));
  expect(screen.queryByRole("region", { name: "引用上下文" })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("omits null neighboring chunks without inventing empty sections", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    return request.method === "POST"
      ? Response.json({ retrievalMode: "hybrid", results: [citation] })
      : Response.json({ ...context, before: null, after: null });
  }));
  const user = userEvent.setup();
  renderSearch();
  await submitSearch(user);
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  const panel = await screen.findByRole("region", { name: "引用上下文" });
  expect(within(panel).getByText("命中片段")).toBeInTheDocument();
  expect(within(panel).queryByText("前文")).toBeNull();
  expect(within(panel).queryByText("后文")).toBeNull();
});

test("replacing search results aborts their pending context request", async () => {
  let contextRequest: Request | undefined;
  let searches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "POST") {
      searches += 1;
      return searches === 1
        ? Response.json({ retrievalMode: "hybrid", results: [citation] })
        : Response.json({ retrievalMode: "hybrid", results: [] });
    }
    contextRequest = request;
    return await new Promise<Response>((_resolve, reject) => {
      request.signal.addEventListener("abort", () => {
        reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
  }));
  const user = userEvent.setup();
  renderSearch();
  await submitSearch(user);
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  await screen.findByText("正在加载引用上下文…");
  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "替换搜索结果");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("没有匹配片段")).toBeInTheDocument();
  await waitFor(() => expect(contextRequest?.signal.aborted).toBe(true));
  expect(screen.queryByRole("region", { name: "引用上下文" })).toBeNull();
});

test("an unexpected thrown value becomes a safe retryable context error", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "POST") {
      return Response.json({ retrievalMode: "hybrid", results: [citation] });
    }
    throw { secret: "never-render-context-secret" };
  }));
  const user = userEvent.setup();
  renderSearch();
  await submitSearch(user);
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "无法连接服务器，请检查网络",
  );
  expect(screen.queryByText("never-render-context-secret")).toBeNull();
  expect(screen.getByRole("button", { name: "重新加载引用上下文" }))
    .toBeInTheDocument();
});

test("keeps two expanded citations independent when one context fails", async () => {
  const secondCitation = {
    ...citation,
    resourceId: "00000000-0000-4000-8000-000000005002",
    resourceVersionId: "00000000-0000-4000-8000-000000006002",
    chunkId: "00000000-0000-4000-8000-000000007102",
    title: "第二份资料.pdf",
    excerpt: "第二条摘录",
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "POST") {
      return Response.json({ retrievalMode: "hybrid", results: [citation, secondCitation] });
    }
    if (request.url.includes(secondCitation.chunkId)) {
      return new Response(JSON.stringify({
        code: "database_unavailable",
        message: "第二条暂时不可用",
        traceId: "trace-second-503",
      }), { status: 503, headers: { "Content-Type": "application/json" } });
    }
    return Response.json(context);
  }));
  const user = userEvent.setup();
  renderSearch();
  await submitSearch(user);
  const toggles = screen.getAllByRole("button", { name: "查看引用上下文" });
  await user.click(toggles[0]!);
  await user.click(toggles[1]!);
  expect(await screen.findByText(/命中第一行\s+命中第二行/)).toBeInTheDocument();
  expect(await screen.findByText("第二条暂时不可用")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "收起引用上下文" }))
    .toHaveLength(2);
  expect(screen.getByRole("link", { name: "下载原文件（新标签页）" }))
    .toBeInTheDocument();
});
