import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useState, type ComponentProps } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ApiError } from "../../src/api/errors.ts";
import type { KnowledgeLocator } from "../../src/api/knowledge.ts";
import {
  KnowledgeSearch,
  presentKnowledgeSearchError,
} from "../../src/components/knowledge/KnowledgeSearch.tsx";
import {
  formatKnowledgeLocator,
  formatKnowledgeMediaType,
  validateKnowledgeQuery,
} from "../../src/lib/knowledgeSearch.ts";
import { knowledgeKeys } from "../../src/queries/knowledge.ts";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const ORGANIZATION_ID = "00000000-0000-4000-8000-000000002001";
const RESOURCE_ID = "00000000-0000-4000-8000-000000005001";
const RESOURCE_VERSION_ID = "00000000-0000-4000-8000-000000006001";
const CHUNK_ID = "00000000-0000-4000-8000-000000007001";
const HOSTILE_TITLE = "<script data-hostile-title>title-marker</script>";
const HOSTILE_EXCERPT = "<img src=x data-hostile-excerpt>excerpt-marker";
const HOSTILE_MEDIA_TYPE = "application/x-<svg data-hostile-media>media-marker</svg>";
const HOSTILE_LOCATOR = "<iframe data-hostile-locator>locator-marker</iframe>";
const HOSTILE_ERROR_MESSAGE = "<script data-hostile-error>error-marker</script>";
const HOSTILE_REQUEST_ID = "<img data-hostile-request-id>request-id-marker</img>";

const lifecycleCitation = {
  resourceId: RESOURCE_ID,
  resourceVersionId: RESOURCE_VERSION_ID,
  chunkId: CHUNK_ID,
  title: "引用生命周期.pdf",
  mediaType: "application/pdf",
  excerpt: "引用生命周期摘录",
  locator: { type: "pdf", page: 2 },
  score: 0.9,
} as const;

const lifecycleContext = {
  resourceId: RESOURCE_ID,
  resourceVersionId: RESOURCE_VERSION_ID,
  before: null,
  hit: {
    id: CHUNK_ID,
    ordinal: 2,
    text: "旧搜索已授权的引用原文",
    locator: { type: "pdf", page: 2 },
  },
  after: null,
} as const;

function renderKnowledgeSearch(
  overrides: Partial<ComponentProps<typeof KnowledgeSearch>> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const props: ComponentProps<typeof KnowledgeSearch> = {
    organizationId: ORGANIZATION_ID,
    projectId: PROJECT_ID,
    csrfToken: "csrf-search-test",
    sessionSignal: new AbortController().signal,
    onAccessUnavailable: vi.fn(),
    ...overrides,
  };
  const result = render(
    <QueryClientProvider client={queryClient}>
      <KnowledgeSearch {...props} />
    </QueryClientProvider>,
  );
  return { ...result, props, queryClient };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("submits normalized real search and renders ordered text-only results", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json({
      retrievalMode: "hybrid",
      results: [
        {
          resourceId: "00000000-0000-4000-8000-000000005001",
          resourceVersionId: "00000000-0000-4000-8000-000000006001",
          chunkId: "00000000-0000-4000-8000-000000007001",
          title: HOSTILE_TITLE,
          mediaType: HOSTILE_MEDIA_TYPE,
          excerpt: HOSTILE_EXCERPT,
          locator: { type: "xlsx", sheet: HOSTILE_LOCATOR, cellRange: "A1" },
          score: 0.920123,
        },
        {
          resourceId: "00000000-0000-4000-8000-000000005002",
          resourceVersionId: "00000000-0000-4000-8000-000000006002",
          chunkId: "00000000-0000-4000-8000-000000007002",
          title: "第二条",
          mediaType: "text/markdown",
          excerpt: "租约恢复边界",
          locator: {
            type: "markdown",
            headingPath: ["租约"],
            lineStart: 6,
            lineEnd: 12,
          },
          score: 0.710456,
        },
      ],
    });
  }));
  const user = userEvent.setup();
  const { container } = renderKnowledgeSearch();

  await user.type(screen.getByLabelText("搜索项目知识"), "  ＡＢＣ  ");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  const results = await screen.findByRole("list", { name: "知识搜索结果" });
  expect(within(results).getAllByRole("listitem")).toHaveLength(2);
  expect(within(results).getAllByRole("heading").map((node) => node.textContent)).toEqual([
    HOSTILE_TITLE,
    "第二条",
  ]);
  expect(within(results).getByText(HOSTILE_EXCERPT)).toBeInTheDocument();
  expect(within(results).getByText(HOSTILE_MEDIA_TYPE)).toBeInTheDocument();
  expect(within(results).getByText(`工作表「${HOSTILE_LOCATOR}」 · A1`))
    .toBeInTheDocument();
  expect(within(results).getByText("租约 · 第 6–12 行")).toBeInTheDocument();
  expect(screen.getByText("混合检索")).toBeInTheDocument();
  expect(results.querySelector("script, img, svg, iframe, object, embed, link, style"))
    .toBeNull();
  for (const privateValue of [
    "00000000-0000-4000-8000-000000005001",
    "00000000-0000-4000-8000-000000006001",
    "00000000-0000-4000-8000-000000007001",
    "00000000-0000-4000-8000-000000005002",
    "00000000-0000-4000-8000-000000006002",
    "00000000-0000-4000-8000-000000007002",
    "0.920123",
    "0.710456",
  ]) {
    expect(container).not.toHaveTextContent(privateValue);
  }
  expect(requests).toHaveLength(1);
  expect((await requests[0]!.clone().json())).toEqual({ query: "ABC", limit: 10 });
  expect(requests[0]!.headers.get("X-CSRF-Token")).toBe("csrf-search-test");
});

test.each(["索引", "😀😀", "知".repeat(501)])(
  "does not request invalid query %j",
  async (query) => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    renderKnowledgeSearch();
    await user.type(screen.getByLabelText("搜索项目知识"), query);
    await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
    expect(screen.getByRole("alert")).toHaveAttribute("id", "knowledge-search-error");
    expect(screen.getByLabelText("搜索项目知识")).toHaveAttribute(
      "aria-describedby",
      expect.stringContaining("knowledge-search-error"),
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  },
);

test("distinguishes initial, pending, empty, and keyword fallback states", async () => {
  const responses = [
    { retrievalMode: "hybrid", results: [] },
    {
      retrievalMode: "keyword_fallback",
      results: [{
        resourceId: "00000000-0000-4000-8000-000000005001",
        resourceVersionId: "00000000-0000-4000-8000-000000006001",
        chunkId: "00000000-0000-4000-8000-000000007001",
        title: "降级结果",
        mediaType: "text/plain",
        excerpt: "关键词仍可检索",
        locator: { type: "text", headingPath: [], lineStart: 1, lineEnd: 1 },
        score: 0.5,
      }],
    },
  ];
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(responses.shift())));
  const user = userEvent.setup();
  renderKnowledgeSearch();
  expect(screen.getByText("搜索只返回当前项目已索引的原文片段，不生成 AI 答案。"))
    .toBeInTheDocument();
  expect(screen.queryByText("没有匹配片段")).toBeNull();

  await user.type(screen.getByLabelText("搜索项目知识"), "第一轮查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("没有匹配片段")).toBeInTheDocument();

  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "第二轮查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("语义检索暂时不可用，本次使用关键词结果。"))
    .toBeInTheDocument();
  expect(screen.getByText("降级结果")).toBeInTheDocument();
  expect(screen.queryByText(/回答|生成答案/)).toBeNull();
});

test.each([
  [429, "17", "搜索请求过于频繁", "请在 17 秒后再次搜索", false],
  [503, null, "知识搜索暂时不可用", "知识搜索暂时不可用", true],
] as const)(
  "renders safe HTTP status %s behavior",
  async (status, retryAfter, message, expected, retryable) => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (retryAfter !== null) headers["Retry-After"] = retryAfter;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      code: status === 429 ? "rate_limited" : "embedding_unavailable",
      message,
      traceId: `trace-search-${status}`,
    }), { status, headers })));
    const user = userEvent.setup();
    renderKnowledgeSearch();
    await user.type(screen.getByLabelText("搜索项目知识"), "错误边界");
    await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(screen.getByText(`请求编号：trace-search-${status}`)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新搜索" }) !== null).toBe(retryable);
  },
);

test("renders hostile error text and falls back to the X-Request-ID as text", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    code: "gateway_failure",
    message: HOSTILE_ERROR_MESSAGE,
  }), {
    status: 502,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": HOSTILE_REQUEST_ID,
    },
  })));
  const user = userEvent.setup();
  const { container } = renderKnowledgeSearch();

  await user.type(screen.getByLabelText("搜索项目知识"), "网关错误边界");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(HOSTILE_ERROR_MESSAGE);
  expect(screen.getByText(`请求编号：${HOSTILE_REQUEST_ID}`)).toBeInTheDocument();
  expect(container.querySelector(
    ".knowledge-search-error script, .knowledge-search-error img, " +
    ".knowledge-search-error svg, .knowledge-search-error iframe, " +
    ".knowledge-search-error object, .knowledge-search-error embed",
  )).toBeNull();
});

test("never renders an unexpected thrown value", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw { secret: "do-not-render" }; }));
  const user = userEvent.setup();
  renderKnowledgeSearch();
  await user.type(screen.getByLabelText("搜索项目知识"), "异常边界");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("无法连接服务器，请检查网络");
  expect(screen.queryByText("do-not-render")).toBeNull();
});

test("explicit retry refetches the same normalized query", async () => {
  let attempts = 0;
  vi.stubGlobal("fetch", vi.fn(async () => {
    attempts += 1;
    return attempts === 1
      ? new Response(JSON.stringify({
          code: "embedding_unavailable",
          message: "知识搜索暂时不可用",
          traceId: "trace-retry-search",
        }), { status: 503, headers: { "Content-Type": "application/json" } })
      : Response.json({ retrievalMode: "hybrid", results: [] });
  }));
  const user = userEvent.setup();
  renderKnowledgeSearch();
  await user.type(screen.getByLabelText("搜索项目知识"), "重试边界");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("知识搜索暂时不可用");
  await user.click(screen.getByRole("button", { name: "重新搜索" }));
  expect(await screen.findByText("没有匹配片段")).toBeInTheDocument();
  expect(attempts).toBe(2);
});

test("normalization-equivalent resubmission reuses one exact search key and request body", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json({ retrievalMode: "hybrid", results: [] });
  }));
  const user = userEvent.setup();
  const { queryClient } = renderKnowledgeSearch();

  await user.type(screen.getByLabelText("搜索项目知识"), "  ＡＢＣ  ");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("没有匹配片段")).toBeInTheDocument();

  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "ABC");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  await waitFor(() => expect(requests).toHaveLength(2));

  await expect(Promise.all(requests.map((request) => request.clone().json())))
    .resolves.toEqual([
      { query: "ABC", limit: 10 },
      { query: "ABC", limit: 10 },
    ]);
  const searchKey = knowledgeKeys.search(ORGANIZATION_ID, PROJECT_ID, "ABC", 10);
  expect(queryClient.getQueryData(searchKey)).toEqual({
    retrievalMode: "hybrid",
    results: [],
  });
  expect(queryClient.getQueryCache().findAll({
    predicate: ({ queryKey }) =>
      queryKey.length === 6 &&
      queryKey[0] === "project-knowledge" &&
      queryKey[1] === ORGANIZATION_ID &&
      queryKey[2] === PROJECT_ID &&
      queryKey[3] === "search",
  }).map(({ queryKey }) => queryKey)).toEqual([searchKey]);
});

test("normalization-equivalent resubmission removes authorized detail and refreshes the same citation collapsed", async () => {
  const requests: Request[] = [];
  let searchAttempts = 0;
  let contextAttempts = 0;
  let resolveRefresh!: (response: Response) => void;
  const refresh = new Promise<Response>((resolve) => {
    resolveRefresh = resolve;
  });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "POST") {
      searchAttempts += 1;
      return searchAttempts === 1
        ? Response.json({ retrievalMode: "hybrid", results: [lifecycleCitation] })
        : refresh;
    }
    contextAttempts += 1;
    return Response.json(contextAttempts === 1
      ? lifecycleContext
      : {
          ...lifecycleContext,
          hit: { ...lifecycleContext.hit, text: "重新展开后新授权的引用原文" },
        });
  }));
  const user = userEvent.setup();
  renderKnowledgeSearch();

  await user.type(screen.getByLabelText("搜索项目知识"), "  ＡＢＣ  ");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  await screen.findByText("引用生命周期摘录");
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  expect(await screen.findByText("旧搜索已授权的引用原文")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "下载原文件（新标签页）" }))
    .toBeInTheDocument();

  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "ABC");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  expect(screen.queryByText("旧搜索已授权的引用原文")).toBeNull();
  expect(screen.queryByRole("link", { name: "下载原文件（新标签页）" })).toBeNull();
  expect(screen.queryByRole("region", { name: "引用上下文" })).toBeNull();
  expect(requests.filter((request) => request.method === "GET")).toHaveLength(1);

  resolveRefresh(Response.json({ retrievalMode: "hybrid", results: [lifecycleCitation] }));
  await waitFor(() => expect(screen.queryByText("正在搜索项目知识…")).toBeNull());
  const refreshedToggle = screen.getByRole("button", { name: "查看引用上下文" });
  expect(refreshedToggle).toHaveAttribute("aria-expanded", "false");
  expect(requests.filter((request) => request.method === "GET")).toHaveLength(1);

  await user.click(refreshedToggle);
  expect(await screen.findByText("重新展开后新授权的引用原文")).toBeInTheDocument();
  expect(requests.filter((request) => request.method === "GET")).toHaveLength(2);
});

test("normalization-equivalent resubmission aborts a pending citation context request", async () => {
  let contextRequest: Request | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "POST") {
      return Response.json({ retrievalMode: "hybrid", results: [lifecycleCitation] });
    }
    contextRequest = request;
    return await new Promise<Response>((_resolve, reject) => {
      request.signal.addEventListener("abort", () => {
        reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
  }));
  const user = userEvent.setup();
  renderKnowledgeSearch();

  await user.type(screen.getByLabelText("搜索项目知识"), "  ＡＢＣ  ");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  await screen.findByText("引用生命周期摘录");
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  expect(await screen.findByText("正在加载引用上下文…")).toBeInTheDocument();

  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "ABC");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  await waitFor(() => expect(contextRequest?.signal.aborted).toBe(true));
  expect(screen.queryByRole("region", { name: "引用上下文" })).toBeNull();
});

test("reports a concealed 404 ApiError through the access-unavailable callback", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    code: "not_found",
    message: "资源不存在",
    traceId: "trace-knowledge-search-404",
  }), {
    status: 404,
    headers: { "Content-Type": "application/json" },
  })));
  const onAccessUnavailable = vi.fn();
  const user = userEvent.setup();
  renderKnowledgeSearch({ onAccessUnavailable });

  await user.type(screen.getByLabelText("搜索项目知识"), "权限边界");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  await waitFor(() => expect(onAccessUnavailable).toHaveBeenCalledTimes(1));
  const [error] = onAccessUnavailable.mock.calls[0] as [ApiError];
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({
    kind: "http",
    status: 404,
    code: "not_found",
    message: "资源不存在",
    traceId: "trace-knowledge-search-404",
    context: "POST /api/v1/projects/{project_id}/knowledge/search",
  });
});

test("delivers each persistent 404 once and uses the latest parent callback", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    code: "not_found",
    message: "资源不存在",
    traceId: "trace-callback-identity-404",
  }), {
    status: 404,
    headers: { "Content-Type": "application/json" },
  })));
  const deliveries: Array<{ error: ApiError; revision: number }> = [];
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const sessionSignal = new AbortController().signal;

  function StatefulParent() {
    const [revision, setRevision] = useState(0);
    return (
      <KnowledgeSearch
        organizationId={ORGANIZATION_ID}
        projectId={PROJECT_ID}
        csrfToken="csrf-search-test"
        sessionSignal={sessionSignal}
        onAccessUnavailable={(error) => {
          deliveries.push({ error, revision });
          if (revision === 0) setRevision(1);
        }}
      />
    );
  }

  render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <StatefulParent />
      </QueryClientProvider>
    </StrictMode>,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("搜索项目知识"), "回调身份边界");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  await waitFor(() => expect(deliveries).toHaveLength(1));
  expect(deliveries[0]?.revision).toBe(0);

  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  await waitFor(() => expect(deliveries).toHaveLength(2));
  expect(deliveries.map(({ revision }) => revision)).toEqual([0, 1]);
  expect(deliveries[1]?.error).not.toBe(deliveries[0]?.error);
});

test("does not offer retry when the generated response contract rejects the body", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    retrievalMode: "semantic",
    results: [],
  })));
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const user = userEvent.setup();
  renderKnowledgeSearch();
  await user.type(screen.getByLabelText("搜索项目知识"), "契约边界");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "服务器返回的数据格式不正确，请联系管理员",
  );
  expect(screen.queryByRole("button", { name: "重新搜索" })).toBeNull();
});

test("presents timeout as retryable without exposing its cause", () => {
  expect(presentKnowledgeSearchError(new ApiError("timeout", "知识搜索请求超时", {
    cause: { secret: "timeout-secret" },
  }))).toEqual({
    message: "知识搜索请求超时",
    traceId: null,
    retryable: true,
  });
});

test("cancel aborts the active request, preserves the draft, and allows resubmission", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (requests.length === 1) {
      return await new Promise<Response>((_resolve, reject) => {
        request.signal.addEventListener(
          "abort",
          () => reject(request.signal.reason ?? new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    }
    return Response.json({ retrievalMode: "hybrid", results: [] });
  }));
  const user = userEvent.setup();
  renderKnowledgeSearch();
  await user.type(screen.getByLabelText("搜索项目知识"), "可取消查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("正在搜索项目知识…")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "取消搜索" }));
  expect(requests[0]!.signal.aborted).toBe(true);
  expect(screen.getByRole("status")).toHaveTextContent("搜索已取消");
  expect(screen.getByLabelText("搜索项目知识")).toHaveValue("可取消查询");
  expect(screen.queryByRole("alert")).toBeNull();
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("没有匹配片段")).toBeInTheDocument();
  expect(requests).toHaveLength(2);
});

describe("knowledge search query validation", () => {
  test.each([
    ["  ＡＢＣ  ", { ok: true, query: "ABC" }],
    ["索引边界", { ok: true, query: "索引边界" }],
    ["😀😀😀", { ok: true, query: "😀😀😀" }],
  ])("normalizes %j before validating code points", (input, expected) => {
    expect(validateKnowledgeQuery(input)).toEqual(expected);
  });

  test.each([
    ["", "请输入至少 3 个字符"],
    ["索引", "请输入至少 3 个字符"],
    ["😀😀", "请输入至少 3 个字符"],
    ["知".repeat(501), "搜索内容不能超过 500 个字符"],
  ])("rejects invalid normalized input %j", (input, message) => {
    expect(validateKnowledgeQuery(input)).toEqual({
      ok: false,
      query: input.normalize("NFKC").trim(),
      message,
    });
  });

  test("accepts exactly 500 Unicode code points", () => {
    const query = "😀".repeat(500);
    expect(validateKnowledgeQuery(query)).toEqual({ ok: true, query });
  });

  test.each([
    [500, { ok: true, query: "é".repeat(500) }],
    [
      501,
      {
        ok: false,
        query: "é".repeat(501),
        message: "搜索内容不能超过 500 个字符",
      },
    ],
  ])("validates %i code points after NFKC composition", (length, expected) => {
    expect(validateKnowledgeQuery("e\u0301".repeat(length))).toEqual(expected);
  });

  test.each([
    [
      "\u0085ab\u0085",
      { ok: false, query: "ab", message: "请输入至少 3 个字符" },
    ],
    [
      "\u001cab\u001f",
      { ok: false, query: "ab", message: "请输入至少 3 个字符" },
    ],
    ["\ufeffab\ufeff", { ok: true, query: "\ufeffab\ufeff" }],
  ])("matches API edge-whitespace normalization for %j", (input, expected) => {
    expect(validateKnowledgeQuery(input)).toEqual(expected);
  });

  test("accepts 500 code points surrounded by API whitespace", () => {
    const query = "a".repeat(500);
    expect(validateKnowledgeQuery(`\u0085${query}\u0085`)).toEqual({
      ok: true,
      query,
    });
  });

  test("strips edge whitespace without changing interior whitespace", () => {
    expect(validateKnowledgeQuery("  部署 回滚  ")).toEqual({
      ok: true,
      query: "部署 回滚",
    });
  });
});

describe("knowledge locator formatting", () => {
  const locatorCases: Array<[KnowledgeLocator, string]> = [
    [{ type: "pdf", page: 3 }, "第 3 页"],
    [
      { type: "docx", headingPath: ["运行手册", "升级"], paragraph: 4, table: null },
      "运行手册 › 升级 · 第 4 段",
    ],
    [
      { type: "docx", headingPath: [], paragraph: null, table: 2 },
      "第 2 个表格",
    ],
    [
      { type: "docx", headingPath: [], paragraph: null, table: null },
      "Word 文档",
    ],
    [{ type: "pptx", slide: 8, area: "body" }, "第 8 张幻灯片（正文）"],
    [
      { type: "pptx", slide: 8, area: "notes" },
      "第 8 张幻灯片（演讲者备注）",
    ],
    [
      { type: "xlsx", sheet: "故障清单", cellRange: "A1:C8" },
      "工作表「故障清单」 · A1:C8",
    ],
    [{ type: "csv", rowStart: 9, rowEnd: 9 }, "第 9 行"],
    [{ type: "csv", rowStart: 9, rowEnd: 14 }, "第 9–14 行"],
    [
      { type: "html", headingPath: ["部署", "回滚"], block: 2 },
      "部署 › 回滚 · 第 2 个正文块",
    ],
    [{ type: "text", headingPath: [], lineStart: 6, lineEnd: 6 }, "第 6 行"],
    [
      { type: "markdown", headingPath: ["租约"], lineStart: 6, lineEnd: 12 },
      "租约 · 第 6–12 行",
    ],
  ];

  test.each(locatorCases)("formats %o as %s", (locator, expected) => {
    expect(formatKnowledgeLocator(locator)).toBe(expected);
  });

  test.each([
    ["application/pdf", "PDF"],
    [
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "DOCX",
    ],
    [
      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      "PPTX",
    ],
    [
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "XLSX",
    ],
    ["application/zip", "ZIP"],
    ["text/csv", "CSV"],
    ["text/html", "HTML"],
    ["text/markdown", "Markdown"],
    ["text/plain", "纯文本"],
    ["application/x-cairn-unknown", "application/x-cairn-unknown"],
    ["__proto__", "__proto__"],
    ["constructor", "constructor"],
  ])("formats media type %s", (mediaType, expected) => {
    expect(formatKnowledgeMediaType(mediaType)).toBe(expected);
  });
});
