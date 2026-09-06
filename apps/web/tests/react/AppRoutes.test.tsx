import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Profiler, StrictMode, useState } from "react";
import { MemoryRouter, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../src/app/AppRoutes.tsx";
import type { IdentityContext } from "../../src/api/auth.ts";
import { ApiError } from "../../src/api/errors.ts";
import { createAppQueryClient } from "../../src/app/queryClient.ts";
import {
  SessionProvider,
  type SessionApi,
  useSession,
} from "../../src/session/SessionContext.tsx";
import { ThemeProvider } from "../../src/theme/ThemeContext.tsx";

const IDENTITY: IdentityContext = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
  csrfToken: "csrf-test-token",
};

const KNOWLEDGE_PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const OTHER_KNOWLEDGE_PROJECT_ID = "00000000-0000-4000-8000-000000004002";
const UPLOAD_BATCH_ID = "00000000-0000-4000-8000-000000008001";
const UPLOAD_ID_1 = "00000000-0000-4000-8000-000000009001";
const UPLOAD_ID_2 = "00000000-0000-4000-8000-000000009002";
const UPLOAD_ITEM_ID_1 = "00000000-0000-4000-8000-000000010001";
const UPLOAD_ITEM_ID_2 = "00000000-0000-4000-8000-000000010002";

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const writableResourcePage = (nextCursor: string | null = null) => ({
  capabilities: { canWrite: true },
  items: [],
  nextCursor,
});

const uploadInstruction = (
  uploadId: string,
  itemId: string,
  suffix: string,
) => ({
  uploadId,
  itemId,
  method: "PUT" as const,
  url: `https://objects.invalid/${suffix}?signature=route-private`,
  headers: {
    "Content-Type": "application/pdf",
    "x-upload-token": `route-token-${suffix}`,
  },
  expiresAt: "2026-09-04T10:00:00Z",
});

const uploadCreateResponse = (count = 1) => ({
  batchId: UPLOAD_BATCH_ID,
  uploads: [
    uploadInstruction(UPLOAD_ID_1, UPLOAD_ITEM_ID_1, "upload-one"),
    ...(count === 2
      ? [uploadInstruction(UPLOAD_ID_2, UPLOAD_ITEM_ID_2, "upload-two")]
      : []),
  ],
});

const uploadCompleteResponse = (
  uploadId = UPLOAD_ID_1,
  itemId = UPLOAD_ITEM_ID_1,
) => ({
  uploadId,
  batchId: UPLOAD_BATCH_ID,
  itemId,
  resourceId: null,
  resourceVersionId: null,
  status: "queued" as const,
});

const uploadBatchResponse = () => ({
  id: UPLOAD_BATCH_ID,
  status: "processing" as const,
  itemCount: 2,
  readyCount: 0,
  failedCount: 0,
  createdAt: "2026-09-04T09:00:00Z",
  completedAt: null,
  items: [
    {
      id: UPLOAD_ITEM_ID_1,
      parentItemId: null,
      normalizedPath: "first.pdf",
      mediaType: "application/pdf",
      sizeBytes: 5,
      status: "processing" as const,
      resourceId: null,
      resourceVersionId: null,
      errorCode: null,
      errorDetail: null,
      createdAt: "2026-09-04T09:00:00Z",
      completedAt: null,
    },
    {
      id: UPLOAD_ITEM_ID_2,
      parentItemId: null,
      normalizedPath: "second.pdf",
      mediaType: "application/pdf",
      sizeBytes: 6,
      status: "awaiting_upload" as const,
      resourceId: null,
      resourceVersionId: null,
      errorCode: null,
      errorDetail: null,
      createdAt: "2026-09-04T09:00:00Z",
      completedAt: null,
    },
  ],
});

type RouteXhrHandler = ((event: ProgressEvent) => void) | null;

interface RouteXhr {
  status: number;
  responseText: string;
  withCredentials: boolean;
  upload: { onprogress: RouteXhrHandler };
  onload: RouteXhrHandler;
  onerror: RouteXhrHandler;
  onabort: RouteXhrHandler;
  open: ReturnType<typeof vi.fn>;
  setRequestHeader: ReturnType<typeof vi.fn>;
  send: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
}

function installRouteXhr(): RouteXhr[] {
  const instances: RouteXhr[] = [];
  vi.stubGlobal("XMLHttpRequest", vi.fn(function () {
    const xhr: RouteXhr = {
      status: 0,
      responseText: "",
      withCredentials: true,
      upload: { onprogress: null },
      onload: null,
      onerror: null,
      onabort: null,
      open: vi.fn(),
      setRequestHeader: vi.fn(),
      send: vi.fn(),
      abort: vi.fn(),
    };
    instances.push(xhr);
    return xhr;
  }));
  return instances;
}

function finishRouteXhr(xhr: RouteXhr, status = 200): void {
  xhr.status = status;
  xhr.onload?.(new ProgressEvent("load"));
}

function knowledgeResource({
  id,
  mediaType,
  sizeBytes,
  status,
  title,
}: {
  id: string;
  mediaType: string;
  sizeBytes: number;
  status: "queued" | "processing" | "ready" | "failed";
  title: string;
}) {
  return {
    id,
    title,
    sourceType: "upload",
    createdAt: "2026-08-21T02:00:00Z",
    updatedAt: "2026-08-22T02:00:00Z",
    latestVersion: {
      id: id.replace(/.$/, "9"),
      sourceType: "upload",
      mediaType,
      sizeBytes,
      sha256: "a".repeat(64),
      status,
      errorCode: status === "failed" ? "parser_failed" : null,
      retryable: status === "failed",
      createdAt: "2026-08-21T02:00:00Z",
      processingStartedAt: status === "queued" ? null : "2026-08-21T02:01:00Z",
      readyAt: status === "ready" ? "2026-08-21T02:03:00Z" : null,
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

const pendingResponseCleanups = new Set<() => void>();

function trackedResponse(fallback: () => Response) {
  const response = deferred<Response>();
  const settle = response.resolve;
  const cleanup = () => settle(fallback());
  const resolve = (value: Response) => {
    pendingResponseCleanups.delete(cleanup);
    settle(value);
  };
  pendingResponseCleanups.add(cleanup);
  return { promise: response.promise, resolve };
}

const trackedBatchResponse = () => trackedResponse(
  () => jsonResponse(uploadBatchResponse()),
);

const trackedResourceResponse = () => trackedResponse(
  () => jsonResponse(writableResourcePage()),
);

async function settleLateBatchResponse(
  response: ReturnType<typeof trackedBatchResponse>,
  forceRerender?: () => void,
): Promise<void> {
  await act(async () => {
    response.resolve(jsonResponse(uploadBatchResponse()));
    await Promise.resolve();
    await Promise.resolve();
  });
  forceRerender?.();
}

function expectQueriesNotToContain(
  queryClient: ReturnType<typeof createAppQueryClient>,
  staleTexts: readonly string[],
): void {
  expect(queryClient.getQueryCache().getAll().every((query) => {
    const data = JSON.stringify(query.state.data) ?? "";
    return staleTexts.every((text) => !data.includes(text));
  })).toBe(true);
}

function fakeSessionApi(overrides: Partial<SessionApi> = {}): SessionApi {
  return {
    restore: async () => { throw new ApiError("http", "无会话", { status: 401, code: "session_invalid" }); },
    logout: async () => undefined,
    ...overrides,
  };
}

interface TestRouteControls {
  establishSession(identity: IdentityContext): void;
  forceRerender(): void;
  navigate: NavigateFunction;
}

function TestAppHarness({
  capture,
  onCommit,
}: {
  capture(controls: TestRouteControls): void;
  onCommit(): void;
}) {
  const navigate = useNavigate();
  const { establishSession } = useSession();
  const [renderCount, setRenderCount] = useState(0);
  void renderCount;
  capture({
    establishSession,
    forceRerender: () => setRenderCount((value) => value + 1),
    navigate,
  });
  return (
    <Profiler id="test-app-routes" onRender={onCommit}>
      <AppRoutes />
    </Profiler>
  );
}

function renderTestRoutes(path: string, options: {
  restoredIdentity?: IdentityContext;
  sessionApi?: SessionApi;
  strictMode?: boolean;
} = {}) {
  const queryClient = createAppQueryClient();
  const commitSnapshots: string[] = [];
  let controls: TestRouteControls | null = null;

  const content = (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <SessionProvider sessionApi={options.sessionApi ?? fakeSessionApi()} restoredIdentity={options.restoredIdentity}>
            <TestAppHarness
              capture={(value) => { controls = value; }}
              onCommit={() => {
                queueMicrotask(() => { commitSnapshots.push(document.body.textContent ?? ""); });
              }}
            />
          </SessionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
  const result = render(options.strictMode ? <StrictMode>{content}</StrictMode> : content);
  function requireControls(): TestRouteControls {
    if (controls === null) throw new Error("测试路由控制器尚未挂载");
    return controls;
  }
  return {
    ...result,
    commitSnapshots,
    queryClient,
    establishSession(identity: IdentityContext) {
      act(() => requireControls().establishSession(identity));
    },
    forceRerender() {
      act(() => requireControls().forceRerender());
    },
    navigate(pathname: string) {
      act(() => requireControls().navigate(pathname));
    },
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(IDENTITY)));
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

afterEach(() => {
  for (const settle of pendingResponseCleanups) settle();
  pendingResponseCleanups.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("unauthenticated document route redirects to login", async () => {
  renderTestRoutes("/documents");

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "岑宁，Cairn 知识向导" })).toBeInTheDocument();
});

test("unauthenticated project route redirects to login", async () => {
  renderTestRoutes("/projects");

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
});

test("unauthenticated project knowledge route redirects without loading resources", async () => {
  const fetchSpy = vi.mocked(fetch);

  renderTestRoutes("/projects/00000000-0000-4000-8000-000000004001/knowledge");

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("login reaches documents and NavLink reaches ask without a reload", async () => {
  const user = userEvent.setup();
  renderTestRoutes("/login");

  await user.type(await screen.findByLabelText("邮箱"), "demo@cairn.dev");
  await user.type(screen.getByLabelText("密码"), "cairn-demo-2026");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(await screen.findByRole("heading", { name: "知识文档" })).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "知识问答" }));
  expect(await screen.findByRole("heading", { name: "AI 问答" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "知识问答" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("protected routes wait for restoration instead of flashing login", async () => {
  const restore = deferred<IdentityContext>();
  renderTestRoutes("/documents", { sessionApi: fakeSessionApi({ restore: () => restore.promise }) });

  expect(screen.getByText("正在恢复会话…")).toHaveAttribute("aria-busy", "true");
  expect(screen.queryByRole("heading", { name: "登录 Cairn" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "知识文档" })).toBeNull();

  restore.resolve(IDENTITY);
  expect(await screen.findByRole("heading", { name: "知识文档" })).toBeInTheDocument();
});

test("restore outages show a retry action and recover without a blank route", async () => {
  let attempts = 0;
  const user = userEvent.setup();
  renderTestRoutes("/documents", {
    sessionApi: fakeSessionApi({
      restore: async () => {
        attempts += 1;
        if (attempts === 1) {
          throw new ApiError("http", "身份服务暂时不可用", {
            status: 503,
            code: "database_unavailable",
          });
        }
        return IDENTITY;
      },
    }),
  });

  expect(await screen.findByRole("alert")).toHaveTextContent("身份服务暂时不可用");
  await user.click(screen.getByRole("button", { name: "重试" }));

  expect(await screen.findByRole("heading", { name: "知识文档" })).toBeInTheDocument();
  expect(attempts).toBe(2);
});

test("logout failure keeps the authenticated session and cached identity", async () => {
  const api = fakeSessionApi({ logout: async () => { throw new ApiError("network", "断网"); } });
  const user = userEvent.setup();
  renderTestRoutes("/documents", { sessionApi: api, restoredIdentity: IDENTITY });

  await user.click(await screen.findByText("演示用户"));
  await user.click(screen.getByRole("button", { name: "退出" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("断网");
  expect(screen.getByRole("heading", { name: "知识文档" })).toBeInTheDocument();
});

test("authenticated login and unknown routes resolve to documents", async () => {
  const first = renderTestRoutes("/login", { restoredIdentity: IDENTITY });
  expect(await screen.findByRole("heading", { name: "知识文档" })).toBeInTheDocument();
  first.unmount();

  renderTestRoutes("/not-a-route", { restoredIdentity: IDENTITY });
  expect(await screen.findByRole("heading", { name: "知识文档" })).toBeInTheDocument();
});

test("authenticated routes use one extensible application shell", async () => {
  const user = userEvent.setup();
  renderTestRoutes("/documents", { restoredIdentity: IDENTITY });

  expect(await screen.findByRole("banner")).toBeInTheDocument();
  const navigation = screen.getByRole("navigation", { name: "主导航" });
  expect(within(navigation).getAllByRole("link")).toHaveLength(3);
  expect(within(navigation).getByRole("link", { name: "知识文档" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(within(navigation).getByRole("link", { name: "项目任务" })).toBeInTheDocument();
  expect(within(navigation).queryByRole("link", { name: /Agent|治理/ })).toBeNull();
  expect(screen.getByRole("heading", { level: 1, name: "知识文档" })).toBeInTheDocument();
  expect(screen.getByText("管理用于企业问答的内部资料。")).toBeInTheDocument();

  const assistantTrigger = screen.getByRole("button", { name: "打开岑宁助手" });
  expect(assistantTrigger).toHaveAttribute("aria-expanded", "false");
  await user.click(assistantTrigger);
  expect(screen.getByRole("dialog", { name: "岑宁助手" })).toHaveTextContent("知识文档");
  expect(assistantTrigger).toHaveAttribute("aria-expanded", "true");
});

test("authenticated shell presents the dedicated Cairn wordmark once", async () => {
  renderTestRoutes("/documents", { restoredIdentity: IDENTITY });

  const brandLink = await screen.findByRole("link", { name: "Cairn" });
  expect(within(brandLink).getByRole("img", { name: "Cairn" })).toHaveAttribute(
    "src",
    "/assets/brand/cairn-wordmark.png",
  );
  expect(within(brandLink).queryByText("Cairn")).toBeNull();
});

test("authenticated shell keeps a text brand when the wordmark fails", async () => {
  renderTestRoutes("/documents", { restoredIdentity: IDENTITY });

  const brandLink = await screen.findByRole("link", { name: "Cairn" });
  fireEvent.error(within(brandLink).getByRole("img", { name: "Cairn" }));

  expect(within(brandLink).queryByRole("img")).toBeNull();
  expect(within(brandLink).getByText("Cairn")).toBeInTheDocument();
});

test("the project route stays in the shared shell with project navigation and assistant copy", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({ items: [], nextCursor: null })),
  );
  const user = userEvent.setup();

  renderTestRoutes("/projects", { restoredIdentity: IDENTITY });

  expect(await screen.findByRole("heading", { level: 1, name: "项目任务" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "项目任务" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await user.click(screen.getByRole("button", { name: "打开岑宁助手" }));
  expect(screen.getByRole("dialog", { name: "岑宁助手" })).toHaveTextContent("项目任务助手");
});

test.each([
  ["contract", () => jsonResponse({
    capabilities: { canWrite: true },
    items: [{
      id: "00000000-0000-4000-8000-000000005099",
      title: "损坏日期.pdf",
      sourceType: "upload",
      createdAt: "2026-08-21T02:00:00Z",
      updatedAt: "not-a-date",
      latestVersion: null,
    }],
    nextCursor: null,
  })],
  ["HTTP 404", () => jsonResponse({
    code: "not_found",
    message: "项目不存在或不可访问",
    traceId: "trace-knowledge-404",
  }, 404)],
])("project knowledge %s errors do not offer an ineffective retry", async (_kind, response) => {
  vi.stubGlobal("fetch", vi.fn(async () => response()));
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  renderTestRoutes(
    "/projects/00000000-0000-4000-8000-000000004001/knowledge",
    { restoredIdentity: IDENTITY },
  );

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重新加载知识资料" })).toBeNull();
});

test("an initial session-invalid knowledge response clears the session without retrying", async () => {
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      requests.push(input as Request);
      return jsonResponse({
        code: "session_invalid",
        message: "会话已过期",
        traceId: "trace-knowledge-session-401",
      }, 401);
    }),
  );

  const { queryClient } = renderTestRoutes(
    "/projects/00000000-0000-4000-8000-000000004001/knowledge",
    { restoredIdentity: IDENTITY },
  );

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(requests).toHaveLength(1);
  expect(requests[0]?.signal.aborted).toBe(true);
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
});

test.each(["503", "network"])(
  "project knowledge %s errors offer retry and recover",
  async (failureKind) => {
    let attempts = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      attempts += 1;
      if (attempts > 2) {
        return jsonResponse({
          capabilities: { canWrite: true },
          items: [],
          nextCursor: null,
        });
      }
      if (failureKind === "network") throw new TypeError("socket closed");
      return jsonResponse({
        code: "database_unavailable",
        message: "知识服务暂时不可用",
        traceId: "trace-knowledge-503",
      }, 503);
    }));
    const user = userEvent.setup();

    renderTestRoutes(
      "/projects/00000000-0000-4000-8000-000000004001/knowledge",
      { restoredIdentity: IDENTITY },
    );

    expect(await screen.findByRole("alert", undefined, { timeout: 3_000 })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新加载知识资料" }));
    expect(await screen.findByRole("heading", { name: "还没有知识资料" })).toBeInTheDocument();
    expect(attempts).toBe(3);
  },
);

test("the project knowledge route exposes its initial loading state until resources arrive", async () => {
  const resourcePage = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn(async () => resourcePage.promise));

  renderTestRoutes(
    "/projects/00000000-0000-4000-8000-000000004001/knowledge",
    { restoredIdentity: IDENTITY },
  );

  const workspace = screen.getByRole("region", { name: "项目知识工作区" });
  expect(workspace).toHaveAttribute("aria-busy", "true");
  expect(screen.getByText("正在连接项目知识")).toBeInTheDocument();

  resourcePage.resolve(jsonResponse({
    capabilities: { canWrite: true },
    items: [],
    nextCursor: null,
  }));

  expect(await screen.findByRole("heading", { name: "还没有知识资料" })).toBeInTheDocument();
  expect(workspace).not.toHaveAttribute("aria-busy");
  expect(screen.queryByText("正在连接项目知识")).toBeNull();
});

test("the project knowledge route loads the selected project inside the shared knowledge shell", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      requests.push(input as Request);
      return jsonResponse({
        capabilities: { canWrite: true },
        items: [],
        nextCursor: null,
      });
    }),
  );
  const user = userEvent.setup();

  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  expect(await screen.findByRole("heading", { level: 1, name: "项目知识" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "还没有知识资料" })).toBeInTheDocument();
  expect(screen.getByLabelText("上传知识资料")).toBeVisible();
  expect(screen.queryByText("上传入口将在后续任务接入")).toBeNull();
  expect(screen.getByText("可维护资料")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "项目任务" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(new URL(requests[0]?.url ?? "").pathname).toBe(
    `/api/v1/projects/${projectId}/knowledge/resources`,
  );
  expect(requests[0]?.credentials).toBe("include");

  await user.click(screen.getByRole("button", { name: "打开岑宁助手" }));
  expect(screen.getByRole("dialog", { name: "岑宁助手" })).toHaveTextContent("项目知识助手");
});

test("a read-only project reader can search real project knowledge", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const resourceId = "00000000-0000-4000-8000-000000005001";
  const resourceVersionId = "00000000-0000-4000-8000-000000006001";
  const chunkId = "00000000-0000-4000-8000-000000007001";
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST") {
      return jsonResponse({
        retrievalMode: "hybrid",
        results: [{
          resourceId,
          resourceVersionId,
          chunkId,
          title: "只读资料",
          mediaType: "application/pdf",
          excerpt: "只读权限仍可检索",
          locator: { type: "pdf", page: 2 },
          score: 0.8,
        }],
      });
    }
    if (pathname ===
      `/api/v1/projects/${projectId}/knowledge/resources/${resourceId}/chunks/${chunkId}`
    ) {
      return jsonResponse({
        resourceId,
        resourceVersionId,
        before: null,
        hit: {
          id: chunkId,
          ordinal: 1,
          text: "只读权限仍可阅读引用原文",
          locator: { type: "pdf", page: 2 },
        },
        after: null,
      });
    }
    return jsonResponse({
      capabilities: { canWrite: false },
      items: [knowledgeResource({
        id: resourceId,
        title: "只读资料.pdf",
        mediaType: "application/pdf",
        sizeBytes: 1024,
        status: "ready",
      })],
      nextCursor: null,
    });
  }));
  const user = userEvent.setup();
  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  expect(await screen.findByText("只读访问")).toBeInTheDocument();
  expect(screen.queryByLabelText("上传知识资料")).toBeNull();
  await user.type(screen.getByLabelText("搜索项目知识"), "只读检索");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("只读权限仍可检索")).toBeInTheDocument();
  const searchRequest = requests.find((request) => request.method === "POST");
  expect(searchRequest).toBeDefined();
  expect(searchRequest!.headers.get("X-CSRF-Token")).toBe("csrf-test-token");
  await expect(searchRequest!.clone().json()).resolves.toEqual({ query: "只读检索", limit: 10 });

  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));
  expect(await screen.findByText("只读权限仍可阅读引用原文")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "下载原文件（新标签页）" })).toHaveAttribute(
    "href",
    `http://localhost:8080/api/v1/projects/${projectId}/knowledge/resources/${resourceId}/download`,
  );
  expect(screen.getByText("只读访问")).toBeInTheDocument();
  expect(requests.some((request) => new URL(request.url).pathname.endsWith("/download")))
    .toBe(false);
});

test("a writable project creates an upload with the exact session and file contract", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
      return jsonResponse(writableResourcePage());
    }
    if (request.method === "POST" && pathname.endsWith("/knowledge/uploads")) {
      return jsonResponse(uploadCreateResponse(), 201);
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const xhrs = installRouteXhr();
  const user = userEvent.setup();
  renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, {
    restoredIdentity: IDENTITY,
  });

  const input = await screen.findByLabelText("上传知识资料");
  await user.upload(
    input,
    new File(["route-upload"], "route-upload.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "开始上传" }));

  const createRequest = await waitFor(() => {
    const request = requests.find((candidate) =>
      candidate.method === "POST" &&
      new URL(candidate.url).pathname.endsWith("/knowledge/uploads")
    );
    expect(request).toBeDefined();
    return request!;
  });
  expect(createRequest.credentials).toBe("include");
  expect(createRequest.headers.get("X-CSRF-Token")).toBe("csrf-test-token");
  expect(createRequest.headers.get("Content-Type")).toContain("application/json");
  expect(new URL(createRequest.url).pathname).toBe(
    `/api/v1/projects/${KNOWLEDGE_PROJECT_ID}/knowledge/uploads`,
  );
  await expect(createRequest.clone().json()).resolves.toEqual({
    files: [{
      fileName: "route-upload.pdf",
      mediaType: "application/pdf",
      sizeBytes: 12,
      sha256: "79b61a7c915771540d733b359e806cceff41fcad0734aa75454f272a45f24ebe",
    }],
  });
  await waitFor(() => expect(xhrs).toHaveLength(1));
  expect(xhrs[0]?.open).toHaveBeenCalledWith(
    "PUT",
    "https://objects.invalid/upload-one?signature=route-private",
    true,
  );
  expect(xhrs[0]?.withCredentials).toBe(false);
});

test("an upload-create 404 conceals the whole project knowledge workspace", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "GET") return jsonResponse(writableResourcePage());
    return jsonResponse({
      code: "not_found",
      message: "项目或知识资料不存在",
      traceId: "trace-route-upload-create-404",
    }, 404);
  }));
  const user = userEvent.setup();
  const { queryClient } = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  await user.upload(
    await screen.findByLabelText("上传知识资料"),
    new File(["create"], "create.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "开始上传" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("项目或知识资料不存在");
  expect(screen.queryByLabelText("上传知识资料")).toBeNull();
  expect(screen.queryByLabelText("搜索项目知识")).toBeNull();
  expect(screen.queryByText("route-private")).toBeNull();
  expect(queryClient.getQueryData([
    "project-knowledge",
    IDENTITY.organization.id,
    KNOWLEDGE_PROJECT_ID,
    "resources",
  ])).toBeUndefined();
  expect(requests).toHaveLength(2);
});

test("an upload-complete 404 stays local when a fresh resource check still succeeds", async () => {
  const requests: Request[] = [];
  let resourceRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
      resourceRequests += 1;
      return jsonResponse(writableResourcePage());
    }
    if (pathname.endsWith("/knowledge/uploads")) {
      return jsonResponse(uploadCreateResponse(), 201);
    }
    if (pathname.endsWith(`/knowledge/uploads/${UPLOAD_ID_1}/complete`)) {
      return jsonResponse({
        code: "not_found",
        message: "项目或知识资料不存在",
        traceId: "trace-route-upload-complete-local",
      }, 404);
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const xhrs = installRouteXhr();
  const user = userEvent.setup();
  renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, {
    restoredIdentity: IDENTITY,
  });

  await user.upload(
    await screen.findByLabelText("上传知识资料"),
    new File(["complete"], "complete.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "开始上传" }));
  const xhr = await waitFor(() => {
    expect(xhrs).toHaveLength(1);
    return xhrs[0]!;
  });
  act(() => finishRouteXhr(xhr));

  expect((await screen.findByText("项目或知识资料不存在")).closest("[role=alert]"))
    .not.toBeNull();
  expect(screen.getByText("请求编号：trace-route-upload-complete-local")).toBeInTheDocument();
  expect(screen.getByLabelText("上传知识资料")).toBeInTheDocument();
  expect(screen.getByLabelText("搜索项目知识")).toBeInTheDocument();
  expect(screen.getByText("可维护资料")).toBeInTheDocument();
  expect(resourceRequests).toBe(2);
  const completeRequest = requests.find((request) =>
    new URL(request.url).pathname.endsWith(`/${UPLOAD_ID_1}/complete`)
  );
  expect(completeRequest?.credentials).toBe("include");
  expect(completeRequest?.headers.get("X-CSRF-Token")).toBe("csrf-test-token");
  await expect(completeRequest?.clone().text()).resolves.toBe("");
});

test("an upload-complete 404 conceals when the fresh resource boundary is also gone", async () => {
  let resourceRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
      resourceRequests += 1;
      return resourceRequests === 1
        ? jsonResponse(writableResourcePage())
        : jsonResponse({
            code: "not_found",
            message: "项目或知识资料不存在",
            traceId: "trace-route-resource-recheck-404",
          }, 404);
    }
    if (pathname.endsWith("/knowledge/uploads")) {
      return jsonResponse(uploadCreateResponse(), 201);
    }
    if (pathname.endsWith(`/${UPLOAD_ID_1}/complete`)) {
      return jsonResponse({
        code: "not_found",
        message: "项目或知识资料不存在",
        traceId: "trace-route-upload-complete-conceal",
      }, 404);
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const xhrs = installRouteXhr();
  const user = userEvent.setup();
  const { queryClient } = renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, {
    restoredIdentity: IDENTITY,
  });

  await screen.findByLabelText("上传知识资料");
  const projectKey = [
    "project-knowledge",
    IDENTITY.organization.id,
    KNOWLEDGE_PROJECT_ID,
  ] as const;
  queryClient.setQueryData([...projectKey, "search", "seeded", 10], {
    retrievalMode: "hybrid",
    results: [],
  });
  queryClient.setQueryData(
    [...projectKey, "batch", "00000000-0000-4000-8000-000000008099"],
    uploadBatchResponse(),
  );
  await user.upload(
    screen.getByLabelText("上传知识资料"),
    new File(["conceal"], "conceal.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "开始上传" }));
  await waitFor(() => expect(xhrs).toHaveLength(1));
  act(() => finishRouteXhr(xhrs[0]!));

  expect(await screen.findByRole("alert")).toHaveTextContent("项目或知识资料不存在");
  expect(screen.queryByLabelText("上传知识资料")).toBeNull();
  expect(screen.queryByLabelText("搜索项目知识")).toBeNull();
  expect(screen.queryByText("请求编号：trace-route-upload-complete-conceal")).toBeNull();
  expect(screen.queryByText("trace-route-resource-recheck-404")).toBeNull();
  expect(screen.queryByText("route-private")).toBeNull();
  expect(resourceRequests).toBe(2);
  expect(queryClient.getQueryCache().findAll({ queryKey: projectKey })).toHaveLength(0);
});

test("a batch 404 conceals after a fresh resource 404 and removes the project cache prefix", async () => {
  const batchNotFound = trackedResponse(() => jsonResponse({
    code: "not_found",
    message: "项目或知识资料不存在",
    traceId: "trace-route-batch-cleanup",
  }, 404));
  let resourceRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
      resourceRequests += 1;
      return resourceRequests < 3
        ? jsonResponse({
            capabilities: { canWrite: true },
            items: [knowledgeResource({
              id: "00000000-0000-4000-8000-000000005095",
              title: "批次撤权前资料.pdf",
              mediaType: "application/pdf",
              sizeBytes: 1024,
              status: "ready",
            })],
            nextCursor: null,
          })
        : jsonResponse({
            code: "not_found",
            message: "项目或知识资料不存在",
            traceId: "trace-route-batch-resource-404",
          }, 404);
    }
    if (request.method === "GET" && pathname.includes(`/knowledge/batches/${UPLOAD_BATCH_ID}`)) {
      return batchNotFound.promise;
    }
    if (pathname.endsWith("/knowledge/uploads")) {
      return jsonResponse(uploadCreateResponse(), 201);
    }
    if (pathname.endsWith(`/${UPLOAD_ID_1}/complete`)) {
      return jsonResponse(uploadCompleteResponse());
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const xhrs = installRouteXhr();
  const user = userEvent.setup();
  const { queryClient } = renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, {
    restoredIdentity: IDENTITY,
  });
  const projectKey = [
    "project-knowledge",
    IDENTITY.organization.id,
    KNOWLEDGE_PROJECT_ID,
  ] as const;

  expect(await screen.findByText("批次撤权前资料.pdf")).toBeInTheDocument();
  queryClient.setQueryData([...projectKey, "search", "batch-seed", 10], {
    retrievalMode: "hybrid",
    results: [],
  });
  queryClient.setQueryData(
    [...projectKey, "batch", "00000000-0000-4000-8000-000000008098"],
    uploadBatchResponse(),
  );
  await user.upload(
    screen.getByLabelText("上传知识资料"),
    new File(["batch"], "batch-404.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "开始上传" }));
  await waitFor(() => expect(xhrs).toHaveLength(1));
  act(() => finishRouteXhr(xhrs[0]!));
  await waitFor(() => expect(resourceRequests).toBe(2));

  await act(async () => {
    batchNotFound.resolve(jsonResponse({
      code: "not_found",
      message: "项目或知识资料不存在",
      traceId: "trace-route-batch-404",
    }, 404));
    await Promise.resolve();
  });

  expect(await screen.findByRole("alert")).toHaveTextContent("项目或知识资料不存在");
  expect(resourceRequests).toBe(3);
  expect(screen.queryByLabelText("上传知识资料")).toBeNull();
  expect(screen.queryByLabelText("搜索项目知识")).toBeNull();
  expect(screen.queryByText("批次撤权前资料.pdf")).toBeNull();
  expect(screen.queryByText("batch-404.pdf")).toBeNull();
  expect(screen.queryByText("trace-route-batch-404")).toBeNull();
  expect(screen.queryByText("trace-route-batch-resource-404")).toBeNull();
  expect(screen.queryByText("route-private")).toBeNull();
  expect(queryClient.getQueryCache().findAll({ queryKey: projectKey })).toHaveLength(0);
});

test.each(["create", "complete"] as const)(
  "a session-invalid upload %s clears private data and navigates to login",
  async (stage) => {
    const requests: Request[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      requests.push(request);
      const pathname = new URL(request.url).pathname;
      if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
        return jsonResponse(writableResourcePage());
      }
      if (pathname.endsWith("/knowledge/uploads")) {
        return stage === "create"
          ? jsonResponse({
              code: "session_invalid",
              message: "会话已过期",
              traceId: "trace-route-upload-create-401",
            }, 401)
          : jsonResponse(uploadCreateResponse(), 201);
      }
      if (pathname.endsWith(`/${UPLOAD_ID_1}/complete`)) {
        return jsonResponse({
          code: "session_invalid",
          message: "会话已过期",
          traceId: "trace-route-upload-complete-401",
        }, 401);
      }
      throw new Error(`Unexpected request: ${request.method} ${pathname}`);
    }));
    const xhrs = installRouteXhr();
    const user = userEvent.setup();
    const { queryClient } = renderTestRoutes(
      `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
      { restoredIdentity: IDENTITY },
    );

    await user.upload(
      await screen.findByLabelText("上传知识资料"),
      new File([stage], `${stage}.pdf`, { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("button", { name: "开始上传" }));
    if (stage === "complete") {
      await waitFor(() => expect(xhrs).toHaveLength(1));
      act(() => finishRouteXhr(xhrs[0]!));
    }

    expect(await screen.findByRole("heading", { name: "登录 Cairn" }))
      .toBeInTheDocument();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
    expect(screen.queryByLabelText("上传知识资料")).toBeNull();
    expect(screen.queryByText(`${stage}.pdf`)).toBeNull();
    expect(requests.every((request) => request.signal.aborted)).toBe(true);
  },
);

test("a citation-only 404 keeps the project workspace and refreshes only resources", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const resourceId = "00000000-0000-4000-8000-000000005001";
  const resourceVersionId = "00000000-0000-4000-8000-000000006001";
  const chunkId = "00000000-0000-4000-8000-000000007001";
  let searchRequests = 0;
  let resourceListRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST") {
      searchRequests += 1;
      return jsonResponse({
        retrievalMode: "hybrid",
        results: [{
          resourceId,
          resourceVersionId,
          chunkId,
          title: "撤销前结果",
          mediaType: "application/pdf",
          excerpt: "撤销前搜索摘录",
          locator: { type: "pdf", page: 1 },
          score: 0.9,
        }],
      });
    }
    if (pathname ===
      `/api/v1/projects/${projectId}/knowledge/resources/${resourceId}/chunks/${chunkId}`
    ) {
      return jsonResponse({
        code: "not_found",
        message: "不可见资源",
        traceId: "trace-context-resource-404",
      }, 404);
    }
    resourceListRequests += 1;
    return jsonResponse({
      capabilities: { canWrite: false },
      items: resourceListRequests === 1
        ? [knowledgeResource({
            id: resourceId,
            title: "撤销前资料.pdf",
            mediaType: "application/pdf",
            sizeBytes: 1024,
            status: "ready",
          })]
        : [],
      nextCursor: null,
    });
  }));
  const user = userEvent.setup();

  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  expect(await screen.findByText("撤销前资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "资源撤销");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("撤销前搜索摘录")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "该引用已不可用，请重新搜索",
  );
  expect(await screen.findByRole("heading", { name: "还没有知识资料" }))
    .toBeInTheDocument();
  expect(screen.getByLabelText("搜索项目知识")).toBeInTheDocument();
  expect(screen.getByText("撤销前搜索摘录")).toBeInTheDocument();
  expect(searchRequests).toBe(1);
  expect(resourceListRequests).toBe(2);
  expect(screen.queryByRole("link", { name: "下载原文件（新标签页）" })).toBeNull();
});

test("a citation 404 followed by a resource-list 404 removes revoked project knowledge", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const resourceId = "00000000-0000-4000-8000-000000005001";
  const resourceVersionId = "00000000-0000-4000-8000-000000006001";
  const chunkId = "00000000-0000-4000-8000-000000007001";
  let resourceListRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST") {
      return jsonResponse({
        retrievalMode: "hybrid",
        results: [{
          resourceId,
          resourceVersionId,
          chunkId,
          title: "撤权前结果",
          mediaType: "application/pdf",
          excerpt: "撤权前搜索摘录",
          locator: { type: "pdf", page: 1 },
          score: 0.9,
        }],
      });
    }
    if (pathname ===
      `/api/v1/projects/${projectId}/knowledge/resources/${resourceId}/chunks/${chunkId}`
    ) {
      return jsonResponse({
        code: "not_found",
        message: "不可见资源",
        traceId: "trace-context-project-404",
      }, 404);
    }
    resourceListRequests += 1;
    if (resourceListRequests > 1) {
      return jsonResponse({
        code: "not_found",
        message: "项目或知识资料不存在",
        traceId: "trace-resources-project-404",
      }, 404);
    }
    return jsonResponse({
      capabilities: { canWrite: true },
      items: [knowledgeResource({
        id: resourceId,
        title: "撤权前资料.pdf",
        mediaType: "application/pdf",
        sizeBytes: 1024,
        status: "ready",
      })],
      nextCursor: null,
    });
  }));
  const user = userEvent.setup();

  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  expect(await screen.findByText("撤权前资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "项目撤权");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("撤权前搜索摘录")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));

  expect(await screen.findByText("项目或知识资料不存在")).toHaveAttribute(
    "role",
    "alert",
  );
  for (const staleText of [
    "撤权前资料.pdf",
    "撤权前搜索摘录",
    "可维护资料",
    "该引用已不可用，请重新搜索",
  ]) {
    expect(screen.queryByText(staleText)).toBeNull();
  }
  expect(screen.queryByLabelText("搜索项目知识")).toBeNull();
  expect(screen.queryByRole("region", { name: "引用上下文" })).toBeNull();
  expect(resourceListRequests).toBe(2);
});

test("a session-invalid citation context clears the authenticated page boundary", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const resourceId = "00000000-0000-4000-8000-000000005001";
  const resourceVersionId = "00000000-0000-4000-8000-000000006001";
  const chunkId = "00000000-0000-4000-8000-000000007001";
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST") {
      return jsonResponse({
        retrievalMode: "hybrid",
        results: [{
          resourceId,
          resourceVersionId,
          chunkId,
          title: "会话失效前结果",
          mediaType: "application/pdf",
          excerpt: "会话失效前搜索摘录",
          locator: { type: "pdf", page: 1 },
          score: 0.9,
        }],
      });
    }
    if (pathname ===
      `/api/v1/projects/${projectId}/knowledge/resources/${resourceId}/chunks/${chunkId}`
    ) {
      return jsonResponse({
        code: "session_invalid",
        message: "会话已过期",
        traceId: "trace-context-session-401",
      }, 401);
    }
    return jsonResponse({
      capabilities: { canWrite: true },
      items: [knowledgeResource({
        id: resourceId,
        title: "会话失效前资料.pdf",
        mediaType: "application/pdf",
        sizeBytes: 1024,
        status: "ready",
      })],
      nextCursor: null,
    });
  }));
  const user = userEvent.setup();
  const { queryClient } = renderTestRoutes(
    `/projects/${projectId}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  expect(await screen.findByText("会话失效前资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "会话失效");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("会话失效前搜索摘录")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看引用上下文" }));

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(requests).toHaveLength(3);
  expect(requests.every((request) => request.signal.aborted)).toBe(true);
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  expect(screen.queryByText("会话失效前资料.pdf")).toBeNull();
  expect(screen.queryByText("会话失效前搜索摘录")).toBeNull();
  expect(screen.queryByRole("region", { name: "引用上下文" })).toBeNull();
});

test("a concealed search 404 clears all previously authorized project knowledge", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const projectKey = ["project-knowledge", IDENTITY.organization.id, projectId] as const;
  const latePage = deferred<Response>();
  const requests: Request[] = [];
  let searches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "GET") {
      const cursor = new URL(request.url).searchParams.get("cursor");
      if (cursor !== null) return latePage.promise;
      return jsonResponse({
        capabilities: { canWrite: true },
        items: [knowledgeResource({
          id: "00000000-0000-4000-8000-000000005001",
          title: "撤权前资料.pdf",
          mediaType: "application/pdf",
          sizeBytes: 1024,
          status: "ready",
        })],
        nextCursor: "cursor-revoked-sibling",
      });
    }
    searches += 1;
    if (searches === 1) {
      return jsonResponse({
        retrievalMode: "hybrid",
        results: [{
          resourceId: "00000000-0000-4000-8000-000000005001",
          resourceVersionId: "00000000-0000-4000-8000-000000006001",
          chunkId: "00000000-0000-4000-8000-000000007001",
          title: "撤权前结果",
          mediaType: "application/pdf",
          excerpt: "随后 ACL 被撤销",
          locator: { type: "pdf", page: 1 },
          score: 0.9,
        }],
      });
    }
    return jsonResponse({
      code: "not_found",
      message: "项目或知识资料不存在",
      traceId: "trace-search-revoked",
    }, 404);
  }));
  const user = userEvent.setup();
  const { commitSnapshots, forceRerender, queryClient } = renderTestRoutes(
    `/projects/${projectId}/knowledge`,
    { restoredIdentity: IDENTITY },
  );
  expect(await screen.findByText("撤权前资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "第一轮查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("撤权前结果")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "加载更多知识资料" }));
  const paginationRequest = await waitFor(() => {
    const request = requests.find((candidate) =>
      candidate.method === "GET" &&
      new URL(candidate.url).searchParams.get("cursor") === "cursor-revoked-sibling"
    );
    expect(request).toBeDefined();
    return request!;
  });
  expect(paginationRequest.signal.aborted).toBe(false);
  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "第二轮查询");
  const revocationCommitStart = commitSnapshots.length;
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("项目或知识资料不存在");
  const accessErrorCommits = commitSnapshots
    .slice(revocationCommitStart)
    .filter((snapshot) => snapshot.includes("项目或知识资料不存在"));
  expect(accessErrorCommits.length).toBeGreaterThan(0);
  expect(accessErrorCommits.every((snapshot) =>
    !snapshot.includes("撤权前资料.pdf") &&
    !snapshot.includes("撤权前结果") &&
    !snapshot.includes("可维护资料")
  )).toBe(true);
  for (const staleText of ["撤权前资料.pdf", "撤权前结果", "可维护资料"]) {
    expect(screen.queryByText(staleText)).toBeNull();
  }
  expect(screen.queryByRole("list", { name: "知识资料" })).toBeNull();
  expect(screen.queryByLabelText("搜索项目知识")).toBeNull();
  expect(paginationRequest.signal.aborted).toBe(true);
  await waitFor(() => {
    expect(queryClient.getQueryCache().findAll({ queryKey: projectKey })).toHaveLength(0);
  });

  latePage.resolve(jsonResponse({
    capabilities: { canWrite: true },
    items: [knowledgeResource({
      id: "00000000-0000-4000-8000-000000005002",
      title: "撤权后迟到资料.pdf",
      mediaType: "application/pdf",
      sizeBytes: 2048,
      status: "ready",
    })],
    nextCursor: null,
  }));
  await act(async () => Promise.resolve());
  forceRerender();

  expect(screen.getByRole("alert")).toHaveTextContent("项目或知识资料不存在");
  expect(screen.queryByText("撤权后迟到资料.pdf")).toBeNull();
  expect(screen.queryByText("撤权前资料.pdf")).toBeNull();
  expect(queryClient.getQueryCache().findAll({ queryKey: projectKey })).toHaveLength(0);
});

test("project navigation aborts the old search and starts the new scope without replay", async () => {
  const projectA = "00000000-0000-4000-8000-000000004001";
  const projectB = "00000000-0000-4000-8000-000000004002";
  const lateSearch = deferred<Response>();
  const requests: Request[] = [];
  let projectASearches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET") {
      const isProjectA = pathname.includes(projectA);
      return jsonResponse({
        capabilities: { canWrite: true },
        items: [knowledgeResource({
          id: isProjectA
            ? "00000000-0000-4000-8000-000000005011"
            : "00000000-0000-4000-8000-000000005012",
          title: isProjectA ? "项目甲资料.pdf" : "项目乙资料.pdf",
          mediaType: "application/pdf",
          sizeBytes: 1024,
          status: "ready",
        })],
        nextCursor: null,
      });
    }
    if (pathname.includes(projectA)) {
      projectASearches += 1;
      if (projectASearches > 1) return lateSearch.promise;
      return jsonResponse({
        retrievalMode: "hybrid",
        results: [{
          resourceId: "00000000-0000-4000-8000-000000005011",
          resourceVersionId: "00000000-0000-4000-8000-000000006011",
          chunkId: "00000000-0000-4000-8000-000000007011",
          title: "项目甲结果",
          mediaType: "application/pdf",
          excerpt: "只属于项目甲",
          locator: { type: "pdf", page: 1 },
          score: 0.9,
        }],
      });
    }
    return jsonResponse({
      retrievalMode: "hybrid",
      results: [{
        resourceId: "00000000-0000-4000-8000-000000005012",
        resourceVersionId: "00000000-0000-4000-8000-000000006012",
        chunkId: "00000000-0000-4000-8000-000000007012",
        title: "项目乙结果",
        mediaType: "application/pdf",
        excerpt: "只属于项目乙",
        locator: { type: "pdf", page: 1 },
        score: 0.8,
      }],
    });
  }));
  const user = userEvent.setup();
  const { forceRerender, navigate, queryClient } = renderTestRoutes(
    `/projects/${projectA}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  expect(await screen.findByText("项目甲资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "项目甲查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("项目甲结果")).toBeInTheDocument();
  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "项目甲未完成查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  const pendingRequest = await waitFor(() => {
    const projectAPosts = requests.filter((request) =>
      request.method === "POST" && new URL(request.url).pathname.includes(projectA)
    );
    expect(projectAPosts).toHaveLength(2);
    return projectAPosts[1]!;
  });
  queryClient.setQueryData(
    ["project-knowledge", IDENTITY.organization.id, projectB, "resources"],
    {
      pages: [{
        capabilities: { canWrite: true },
        items: [knowledgeResource({
          id: "00000000-0000-4000-8000-000000005012",
          title: "项目乙资料.pdf",
          mediaType: "application/pdf",
          sizeBytes: 1024,
          status: "ready",
        })],
        nextCursor: null,
      }],
      pageParams: [null],
    },
  );

  navigate(`/projects/${projectB}/knowledge`);

  expect(await screen.findByText("项目乙资料.pdf")).toBeInTheDocument();
  expect(pendingRequest.signal.aborted).toBe(true);
  expect(screen.getByLabelText("搜索项目知识")).toHaveValue("");
  for (const projectAText of ["项目甲资料.pdf", "项目甲结果", "项目甲未完成查询"]) {
    expect(screen.queryByText(projectAText)).toBeNull();
  }
  expect(requests.filter((request) =>
    request.method === "POST" && new URL(request.url).pathname.includes(projectB)
  )).toHaveLength(0);

  lateSearch.resolve(jsonResponse({
    retrievalMode: "hybrid",
    results: [{
      resourceId: "00000000-0000-4000-8000-000000005011",
      resourceVersionId: "00000000-0000-4000-8000-000000006011",
      chunkId: "00000000-0000-4000-8000-000000007013",
      title: "项目甲迟到结果",
      mediaType: "application/pdf",
      excerpt: "不应进入项目乙",
      locator: { type: "pdf", page: 2 },
      score: 0.7,
    }],
  }));
  await act(async () => Promise.resolve());
  forceRerender();

  expect(screen.queryByText("项目甲迟到结果")).toBeNull();
  expect(requests.filter((request) =>
    request.method === "POST" && new URL(request.url).pathname.includes(projectB)
  )).toHaveLength(0);
  const projectBCache = queryClient.getQueryCache().findAll({
    queryKey: ["project-knowledge", IDENTITY.organization.id, projectB],
  });
  expect(projectBCache.length).toBeGreaterThan(0);
  expect(projectBCache.every((query) =>
    !(JSON.stringify(query.state.data) ?? "").includes("项目甲")
  )).toBe(true);
});

test("project navigation aborts an active upload and its batch query without reusing files", async () => {
  const batchResponse = trackedBatchResponse();
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
      return jsonResponse(writableResourcePage());
    }
    if (request.method === "GET" && pathname.includes("/knowledge/batches/")) {
      return batchResponse.promise;
    }
    if (pathname.endsWith("/knowledge/uploads")) {
      return jsonResponse(uploadCreateResponse(2), 201);
    }
    if (pathname.endsWith(`/${UPLOAD_ID_1}/complete`)) {
      return jsonResponse(uploadCompleteResponse());
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const xhrs = installRouteXhr();
  const user = userEvent.setup();
  const { forceRerender, navigate, queryClient } = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  const input = await screen.findByLabelText("上传知识资料");
  await user.upload(input, [
    new File(["first"], "first.pdf", { type: "application/pdf" }),
    new File(["second"], "second.pdf", { type: "application/pdf" }),
  ]);
  await user.click(screen.getByRole("button", { name: "开始上传" }));
  await waitFor(() => expect(xhrs).toHaveLength(2));
  act(() => finishRouteXhr(xhrs[0]!));
  const batchRequest = await waitFor(() => {
    const request = requests.find((candidate) =>
      new URL(candidate.url).pathname.includes(`/knowledge/batches/${UPLOAD_BATCH_ID}`)
    );
    expect(request).toBeDefined();
    return request!;
  });

  navigate(`/projects/${OTHER_KNOWLEDGE_PROJECT_ID}/knowledge`);

  await waitFor(() => expect(batchRequest.signal.aborted).toBe(true));
  expect(xhrs[1]?.abort).toHaveBeenCalledTimes(1);
  expect(await screen.findByLabelText("上传知识资料")).toBeInTheDocument();
  expect(screen.queryByText("first.pdf")).toBeNull();
  expect(screen.queryByText("second.pdf")).toBeNull();
  expect(requests.some((request) =>
    new URL(request.url).pathname.includes(OTHER_KNOWLEDGE_PROJECT_ID)
  )).toBe(true);

  await settleLateBatchResponse(batchResponse, forceRerender);
  expect(screen.queryByText("first.pdf")).toBeNull();
  expect(screen.queryByText("second.pdf")).toBeNull();
  expectQueriesNotToContain(queryClient, ["first.pdf", "second.pdf"]);
});

test("logout aborts an active upload and its batch query and clears private state", async () => {
  const batchResponse = trackedBatchResponse();
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
      return jsonResponse(writableResourcePage());
    }
    if (request.method === "GET" && pathname.includes("/knowledge/batches/")) {
      return batchResponse.promise;
    }
    if (pathname.endsWith("/knowledge/uploads")) {
      return jsonResponse(uploadCreateResponse(2), 201);
    }
    if (pathname.endsWith(`/${UPLOAD_ID_1}/complete`)) {
      return jsonResponse(uploadCompleteResponse());
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const xhrs = installRouteXhr();
  const user = userEvent.setup();
  const { forceRerender, queryClient } = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  await user.upload(await screen.findByLabelText("上传知识资料"), [
    new File(["first"], "logout-first.pdf", { type: "application/pdf" }),
    new File(["second"], "logout-second.pdf", { type: "application/pdf" }),
  ]);
  await user.click(screen.getByRole("button", { name: "开始上传" }));
  await waitFor(() => expect(xhrs).toHaveLength(2));
  act(() => finishRouteXhr(xhrs[0]!));
  const batchRequest = await waitFor(() => {
    const request = requests.find((candidate) =>
      new URL(candidate.url).pathname.includes(`/knowledge/batches/${UPLOAD_BATCH_ID}`)
    );
    expect(request).toBeDefined();
    return request!;
  });

  await user.click(screen.getByText("演示用户"));
  await user.click(screen.getByRole("button", { name: "退出" }));

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(batchRequest.signal.aborted).toBe(true);
  expect(xhrs[1]?.abort).toHaveBeenCalledTimes(1);
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
  expect(screen.queryByText("logout-first.pdf")).toBeNull();
  expect(screen.queryByText("logout-second.pdf")).toBeNull();

  await settleLateBatchResponse(batchResponse, forceRerender);
  expect(screen.queryByText("logout-first.pdf")).toBeNull();
  expect(screen.queryByText("logout-second.pdf")).toBeNull();
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
});

test.each([
  {
    boundary: "authenticated session",
    nextIdentity: {
      ...IDENTITY,
      user: {
        id: "00000000-0000-4000-8000-000000001002",
        email: "next-session@cairn.dev",
        displayName: "新会话用户",
      },
      membership: {
        id: "00000000-0000-4000-8000-000000003002",
        role: "member" as const,
      },
      csrfToken: "csrf-next-session",
    },
  },
  {
    boundary: "organization session",
    nextIdentity: {
      ...IDENTITY,
      user: {
        id: "00000000-0000-4000-8000-000000001003",
        email: "next-org@cairn.dev",
        displayName: "新组织用户",
      },
      organization: {
        id: "00000000-0000-4000-8000-000000002002",
        slug: "cairn-next-upload",
        name: "Cairn Next Upload",
      },
      membership: {
        id: "00000000-0000-4000-8000-000000003003",
        role: "member" as const,
      },
      csrfToken: "csrf-next-organization",
    },
  },
] satisfies Array<{ boundary: string; nextIdentity: IdentityContext }>)(
  "$boundary transition aborts active upload work and exposes no prior session state",
  async ({ nextIdentity }) => {
    const batchResponse = trackedBatchResponse();
    const requests: Request[] = [];
    let transitioned = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      requests.push(request);
      const pathname = new URL(request.url).pathname;
      if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
        return jsonResponse({
          capabilities: { canWrite: true },
          items: [knowledgeResource({
            id: transitioned
              ? "00000000-0000-4000-8000-000000005094"
              : "00000000-0000-4000-8000-000000005093",
            title: transitioned ? "新会话资料.pdf" : "旧会话资料.pdf",
            mediaType: "application/pdf",
            sizeBytes: 1024,
            status: "ready",
          })],
          nextCursor: null,
        });
      }
      if (request.method === "GET" && pathname.includes("/knowledge/batches/")) {
        return batchResponse.promise;
      }
      if (pathname.endsWith("/knowledge/uploads")) {
        return jsonResponse(uploadCreateResponse(2), 201);
      }
      if (pathname.endsWith(`/${UPLOAD_ID_1}/complete`)) {
        return jsonResponse(uploadCompleteResponse());
      }
      throw new Error(`Unexpected request: ${request.method} ${pathname}`);
    }));
    const xhrs = installRouteXhr();
    const user = userEvent.setup();
    const { establishSession, forceRerender, queryClient } = renderTestRoutes(
      `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
      { restoredIdentity: IDENTITY },
    );

    expect(await screen.findByText("旧会话资料.pdf")).toBeInTheDocument();
    await user.upload(screen.getByLabelText("上传知识资料"), [
      new File(["first"], "old-session-first.pdf", { type: "application/pdf" }),
      new File(["second"], "old-session-second.pdf", { type: "application/pdf" }),
    ]);
    await user.click(screen.getByRole("button", { name: "开始上传" }));
    await waitFor(() => expect(xhrs).toHaveLength(2));
    act(() => finishRouteXhr(xhrs[0]!));
    const batchRequest = await waitFor(() => {
      const request = requests.find((candidate) =>
        new URL(candidate.url).pathname.includes(`/knowledge/batches/${UPLOAD_BATCH_ID}`)
      );
      expect(request).toBeDefined();
      return request!;
    });

    transitioned = true;
    establishSession(nextIdentity);

    expect(await screen.findByText("新会话资料.pdf")).toBeInTheDocument();
    expect(batchRequest.signal.aborted).toBe(true);
    expect(xhrs[1]?.abort).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("上传知识资料")).toBeInTheDocument();
    expect(screen.queryByText("old-session-first.pdf")).toBeNull();
    expect(screen.queryByText("old-session-second.pdf")).toBeNull();
    expect(screen.queryByText("旧会话资料.pdf")).toBeNull();
    expect(queryClient.getQueryCache().getAll().every((query) =>
      !(JSON.stringify(query.state.data) ?? "").includes("旧会话")
    )).toBe(true);
    expect(queryClient.getQueryCache().findAll({
      queryKey: [
        "project-knowledge",
        nextIdentity.organization.id,
        KNOWLEDGE_PROJECT_ID,
      ],
    }).length).toBeGreaterThan(0);

    await settleLateBatchResponse(batchResponse, forceRerender);
    expect(screen.queryByText("old-session-first.pdf")).toBeNull();
    expect(screen.queryByText("old-session-second.pdf")).toBeNull();
    expectQueriesNotToContain(queryClient, [
      "old-session-first.pdf",
      "old-session-second.pdf",
      "first.pdf",
      "second.pdf",
    ]);
  },
);

test("organization transition clears an old search 404 without replaying its scope", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const nextIdentity: IdentityContext = {
    ...IDENTITY,
    organization: {
      id: "00000000-0000-4000-8000-000000002002",
      slug: "cairn-next",
      name: "Cairn Next",
    },
    membership: {
      id: "00000000-0000-4000-8000-000000003002",
      role: "member",
    },
    csrfToken: "csrf-next-token",
  };
  const requests: Request[] = [];
  let resourceLoads = 0;
  let searches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "GET") {
      resourceLoads += 1;
      const nextOrganization = resourceLoads > 1;
      return jsonResponse({
        capabilities: { canWrite: !nextOrganization },
        items: [knowledgeResource({
          id: nextOrganization
            ? "00000000-0000-4000-8000-000000005022"
            : "00000000-0000-4000-8000-000000005021",
          title: nextOrganization ? "新组织资料.pdf" : "旧组织资料.pdf",
          mediaType: "application/pdf",
          sizeBytes: 1024,
          status: "ready",
        })],
        nextCursor: null,
      });
    }
    searches += 1;
    if (searches === 1) {
      return jsonResponse({
        code: "not_found",
        message: "旧组织项目不可用",
        traceId: "trace-old-organization-404",
      }, 404);
    }
    return jsonResponse({
      retrievalMode: "hybrid",
      results: [{
        resourceId: "00000000-0000-4000-8000-000000005022",
        resourceVersionId: "00000000-0000-4000-8000-000000006022",
        chunkId: "00000000-0000-4000-8000-000000007022",
        title: "新组织结果",
        mediaType: "application/pdf",
        excerpt: "只属于新组织",
        locator: { type: "pdf", page: 3 },
        score: 0.8,
      }],
    });
  }));
  const user = userEvent.setup();
  const { establishSession, queryClient } = renderTestRoutes(
    `/projects/${projectId}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  expect(await screen.findByText("旧组织资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "触发旧组织撤权");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("旧组织项目不可用");
  const oldSearchRequest = requests.find((request) => request.method === "POST")!;
  expect(queryClient.getQueryCache().findAll({
    queryKey: ["project-knowledge", IDENTITY.organization.id, projectId],
  })).toHaveLength(0);

  establishSession(nextIdentity);

  expect(await screen.findByText("新组织资料.pdf")).toBeInTheDocument();
  expect(oldSearchRequest.signal.aborted).toBe(true);
  expect(screen.queryByText("旧组织项目不可用")).toBeNull();
  expect(screen.queryByText("旧组织资料.pdf")).toBeNull();
  expect(screen.getByLabelText("搜索项目知识")).toHaveValue("");
  expect(requests.filter((request) => request.method === "POST")).toHaveLength(1);
  expect(queryClient.getQueryCache().findAll({
    queryKey: ["project-knowledge", IDENTITY.organization.id, projectId],
  })).toHaveLength(0);
  const nextOrganizationCache = queryClient.getQueryCache().findAll({
    queryKey: ["project-knowledge", nextIdentity.organization.id, projectId],
  });
  expect(nextOrganizationCache.length).toBeGreaterThan(0);
  expect(nextOrganizationCache.every((query) =>
    !(JSON.stringify(query.state.data) ?? "").includes("旧组织")
  )).toBe(true);

  await user.type(screen.getByLabelText("搜索项目知识"), "新组织显式查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("新组织结果")).toBeInTheDocument();
  const searchRequests = requests.filter((request) => request.method === "POST");
  expect(searchRequests).toHaveLength(2);
  expect(searchRequests[1]!.headers.get("X-CSRF-Token")).toBe("csrf-next-token");
});

test("same-project subject transition hard-isolates resources, search state, and in-flight work", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const nextIdentity: IdentityContext = {
    ...IDENTITY,
    user: {
      id: "00000000-0000-4000-8000-000000001002",
      email: "next@cairn.dev",
      displayName: "用户乙",
    },
    membership: {
      id: "00000000-0000-4000-8000-000000003002",
      role: "member",
    },
    csrfToken: "csrf-next-subject",
  };
  const lateSearch = deferred<Response>();
  const requests: Request[] = [];
  let resourceLoads = 0;
  let searches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "GET") {
      resourceLoads += 1;
      const nextSubject = resourceLoads > 1;
      return jsonResponse({
        capabilities: { canWrite: !nextSubject },
        items: [knowledgeResource({
          id: nextSubject
            ? "00000000-0000-4000-8000-000000005032"
            : "00000000-0000-4000-8000-000000005031",
          title: nextSubject ? "用户乙资料.pdf" : "用户甲私有资料.pdf",
          mediaType: "application/pdf",
          sizeBytes: 1024,
          status: "ready",
        })],
        nextCursor: null,
      });
    }
    searches += 1;
    if (searches === 1) {
      return jsonResponse({
        retrievalMode: "hybrid",
        results: [{
          resourceId: "00000000-0000-4000-8000-000000005031",
          resourceVersionId: "00000000-0000-4000-8000-000000006031",
          chunkId: "00000000-0000-4000-8000-000000007031",
          title: "用户甲私有结果",
          mediaType: "application/pdf",
          excerpt: "仅用户甲可以看到的片段",
          locator: { type: "pdf", page: 1 },
          score: 0.9,
        }],
      });
    }
    if (searches === 2) return lateSearch.promise;
    return jsonResponse({
      retrievalMode: "hybrid",
      results: [{
        resourceId: "00000000-0000-4000-8000-000000005032",
        resourceVersionId: "00000000-0000-4000-8000-000000006032",
        chunkId: "00000000-0000-4000-8000-000000007032",
        title: "用户乙结果",
        mediaType: "application/pdf",
        excerpt: "只属于用户乙",
        locator: { type: "pdf", page: 2 },
        score: 0.8,
      }],
    });
  }));
  const user = userEvent.setup();
  const {
    commitSnapshots,
    establishSession,
    forceRerender,
    queryClient,
  } = renderTestRoutes(
    `/projects/${projectId}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  expect(await screen.findByText("用户甲私有资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "用户甲显式查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("用户甲私有结果")).toBeInTheDocument();
  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "用户甲未完成查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  const oldPendingRequest = await waitFor(() => {
    const posts = requests.filter((request) => request.method === "POST");
    expect(posts).toHaveLength(2);
    return posts[1]!;
  });
  queryClient.getMutationCache().build(queryClient, {
    mutationKey: ["user-a-private-mutation"],
    mutationFn: async () => "用户甲私有变更",
  });
  await act(async () => Promise.resolve());
  const transitionCommitStart = commitSnapshots.length;

  establishSession(nextIdentity);

  expect(await screen.findByText("用户乙资料.pdf")).toBeInTheDocument();
  expect(oldPendingRequest.signal.aborted).toBe(true);
  expect(screen.getByLabelText("搜索项目知识")).toHaveValue("");
  expect(requests.filter((request) => request.method === "POST")).toHaveLength(2);
  expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
  const postTransitionCommits = commitSnapshots.slice(transitionCommitStart);
  expect(postTransitionCommits.length).toBeGreaterThan(0);
  expect(postTransitionCommits.every((snapshot) =>
    !snapshot.includes("用户甲私有资料.pdf") &&
    !snapshot.includes("用户甲私有结果") &&
    !snapshot.includes("仅用户甲可以看到的片段")
  )).toBe(true);
  for (const staleText of [
    "用户甲私有资料.pdf",
    "用户甲私有结果",
    "仅用户甲可以看到的片段",
  ]) {
    expect(screen.queryByText(staleText)).toBeNull();
  }
  expect(queryClient.getQueryCache().getAll().every((query) =>
    !(JSON.stringify(query.state.data) ?? "").includes("用户甲")
  )).toBe(true);

  await user.type(screen.getByLabelText("搜索项目知识"), "用户乙显式查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("用户乙结果")).toBeInTheDocument();
  const nextSearchRequest = requests.filter((request) => request.method === "POST")[2]!;
  expect(nextSearchRequest.headers.get("X-CSRF-Token")).toBe("csrf-next-subject");
  await expect(nextSearchRequest.clone().json()).resolves.toEqual({
    query: "用户乙显式查询",
    limit: 10,
  });

  lateSearch.resolve(jsonResponse({
    retrievalMode: "hybrid",
    results: [{
      resourceId: "00000000-0000-4000-8000-000000005031",
      resourceVersionId: "00000000-0000-4000-8000-000000006031",
      chunkId: "00000000-0000-4000-8000-000000007033",
      title: "用户甲迟到结果",
      mediaType: "application/pdf",
      excerpt: "迟到的用户甲私有片段",
      locator: { type: "pdf", page: 3 },
      score: 0.7,
    }],
  }));
  await act(async () => Promise.resolve());
  forceRerender();

  expect(screen.queryByText("用户甲迟到结果")).toBeNull();
  expect(screen.queryByText("迟到的用户甲私有片段")).toBeNull();
  expect(queryClient.getQueryCache().getAll().every((query) =>
    !(JSON.stringify(query.state.data) ?? "").includes("用户甲")
  )).toBe(true);
});

test("same-project subject transition remounts a concealed 404 boundary", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const nextIdentity: IdentityContext = {
    ...IDENTITY,
    user: {
      id: "00000000-0000-4000-8000-000000001002",
      email: "next@cairn.dev",
      displayName: "用户乙",
    },
    membership: {
      id: "00000000-0000-4000-8000-000000003002",
      role: "member",
    },
    csrfToken: "csrf-next-subject",
  };
  let resourceLoads = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "POST") {
      return jsonResponse({
        code: "not_found",
        message: "用户甲项目不可用",
        traceId: "trace-user-a-concealed",
      }, 404);
    }
    resourceLoads += 1;
    const nextSubject = resourceLoads > 1;
    return jsonResponse({
      capabilities: { canWrite: !nextSubject },
      items: [knowledgeResource({
        id: nextSubject
          ? "00000000-0000-4000-8000-000000005042"
          : "00000000-0000-4000-8000-000000005041",
        title: nextSubject ? "用户乙恢复资料.pdf" : "用户甲撤权前资料.pdf",
        mediaType: "application/pdf",
        sizeBytes: 1024,
        status: "ready",
      })],
      nextCursor: null,
    });
  }));
  const user = userEvent.setup();
  const { commitSnapshots, establishSession } = renderTestRoutes(
    `/projects/${projectId}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  expect(await screen.findByText("用户甲撤权前资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "触发用户甲撤权");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("用户甲项目不可用");
  await act(async () => Promise.resolve());
  const transitionCommitStart = commitSnapshots.length;

  establishSession(nextIdentity);

  expect(await screen.findByText("用户乙恢复资料.pdf")).toBeInTheDocument();
  expect(screen.queryByText("用户甲项目不可用")).toBeNull();
  expect(screen.queryByText("用户甲撤权前资料.pdf")).toBeNull();
  expect(screen.getByLabelText("搜索项目知识")).toHaveValue("");
  expect(commitSnapshots.slice(transitionCommitStart).every((snapshot) =>
    !snapshot.includes("用户甲项目不可用") &&
    !snapshot.includes("用户甲撤权前资料.pdf")
  )).toBe(true);
});

test("a session-invalid knowledge search clears resources and ends the session", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "POST") {
      return jsonResponse({
        code: "session_invalid",
        message: "会话已过期",
        traceId: "trace-search-session-401",
      }, 401);
    }
    return jsonResponse({
      capabilities: { canWrite: true },
      items: [knowledgeResource({
        id: "00000000-0000-4000-8000-000000005001",
        title: "会话过期前资料.pdf",
        mediaType: "application/pdf",
        sizeBytes: 1024,
        status: "ready",
      })],
      nextCursor: null,
    });
  }));
  const user = userEvent.setup();
  const { queryClient } = renderTestRoutes(
    `/projects/${projectId}/knowledge`,
    { restoredIdentity: IDENTITY },
  );
  expect(await screen.findByText("会话过期前资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "会话失效边界");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(requests).toHaveLength(2);
  expect(requests.every((request) => request.signal.aborted)).toBe(true);
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  expect(screen.queryByText("会话过期前资料.pdf")).toBeNull();
});

test("the project knowledge route renders resource metadata and every processing state", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({
      capabilities: { canWrite: false },
      items: [
        knowledgeResource({
          id: "00000000-0000-4000-8000-000000005001",
          title: "架构决策.pdf",
          mediaType: "application/pdf",
          sizeBytes: 1536,
          status: "queued",
        }),
        knowledgeResource({
          id: "00000000-0000-4000-8000-000000005002",
          title: "交付清单.docx",
          mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          sizeBytes: 2 * 1024 * 1024,
          status: "processing",
        }),
        knowledgeResource({
          id: "00000000-0000-4000-8000-000000005003",
          title: "值班说明.txt",
          mediaType: "text/plain",
          sizeBytes: 512,
          status: "ready",
        }),
        knowledgeResource({
          id: "00000000-0000-4000-8000-000000005004",
          title: "损坏报告.pdf",
          mediaType: "application/pdf",
          sizeBytes: 10 * 1024 * 1024,
          status: "failed",
        }),
        {
          id: "00000000-0000-4000-8000-000000005005",
          title: "等待版本.md",
          sourceType: "zip_entry",
          createdAt: "2026-08-21T02:00:00Z",
          updatedAt: "2026-08-22T02:00:00Z",
          latestVersion: null,
        },
        {
          id: "00000000-0000-4000-8000-000000005015",
          title: "等待上传版本.txt",
          sourceType: "upload",
          createdAt: "2026-08-21T02:00:00Z",
          updatedAt: "2026-08-22T02:00:00Z",
          latestVersion: null,
        },
      ],
      nextCursor: null,
    })),
  );

  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  expect(await screen.findByText("只读访问")).toBeInTheDocument();
  const list = screen.getByRole("list", { name: "知识资料" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(6);
  expect(within(list).getByText("架构决策.pdf").closest("li")).toHaveTextContent(
    "等待处理PDF1.5 KB2026年8月22日",
  );
  expect(within(list).getByText("交付清单.docx").closest("li")).toHaveTextContent(
    "处理中DOCX2.0 MB",
  );
  expect(within(list).getByText("值班说明.txt").closest("li")).toHaveTextContent(
    "可检索纯文本512 B",
  );
  expect(within(list).getByText("损坏报告.pdf").closest("li")).toHaveTextContent(
    "处理失败PDF10.0 MB",
  );
  expect(within(list).getByText("等待版本.md").closest("li")).toHaveTextContent(
    "等待版本文件类型待生成文件大小待生成ZIP 内文件",
  );
  const uploadWithoutVersion = within(list).getByText("等待上传版本.txt").closest("li");
  expect(uploadWithoutVersion).toHaveTextContent(
    "等待版本文件类型待生成文件大小待生成",
  );
  expect(within(uploadWithoutVersion as HTMLElement).queryByText("ZIP 内文件")).toBeNull();
});

test("resource details abort on collapse and reauthorize on every reopen", async () => {
  const resourceId = "00000000-0000-4000-8000-000000005021";
  const detail = knowledgeResource({
    id: resourceId,
    title: "重开授权手册.pdf",
    mediaType: "application/pdf",
    sizeBytes: 2048,
    status: "ready",
  });
  const firstDetail = trackedResponse(() => jsonResponse(detail));
  const detailRequests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (pathname.endsWith("/knowledge/resources")) {
      return jsonResponse({ capabilities: { canWrite: false }, items: [detail], nextCursor: null });
    }
    if (pathname.endsWith(`/knowledge/resources/${resourceId}`)) {
      detailRequests.push(request);
      return detailRequests.length === 1 ? firstDetail.promise : jsonResponse(detail);
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const user = userEvent.setup();

  renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, { restoredIdentity: IDENTITY });

  const row = (await screen.findByText(detail.title)).closest("li");
  const toggle = within(row as HTMLElement).getByRole("button", { name: "查看资料详情" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(toggle.getAttribute("aria-controls")).toMatch(/^knowledge-resource-detail-/);
  expect(screen.getByText("正在读取资料详情…")).toBeVisible();

  await user.click(toggle);

  await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
  expect(screen.queryByText("正在读取资料详情…")).toBeNull();
  expect(detailRequests[0]?.signal.aborted).toBe(true);
  expect(document.activeElement).toBe(toggle);
  await user.click(toggle);
  expect(await screen.findByRole("region", { name: `${detail.title} 资料详情` })).toBeVisible();
  expect(detailRequests).toHaveLength(2);
});

test("a session-invalid resource detail expires the real session boundary", async () => {
  const resourceId = "00000000-0000-4000-8000-000000005022";
  const detail = knowledgeResource({
    id: resourceId,
    title: "会话失效详情.pdf",
    mediaType: "application/pdf",
    sizeBytes: 1024,
    status: "ready",
  });
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (pathname.endsWith("/knowledge/resources")) {
      return jsonResponse({ capabilities: { canWrite: false }, items: [detail], nextCursor: null });
    }
    return jsonResponse({
      code: "session_invalid",
      message: "会话已过期",
      traceId: "trace-detail-session-401",
    }, 401);
  }));
  const user = userEvent.setup();
  const { queryClient } = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  const row = (await screen.findByText(detail.title)).closest("li");
  await user.click(within(row as HTMLElement).getByRole("button", { name: "查看资料详情" }));

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(requests).toHaveLength(2);
  expect(requests.every((request) => request.signal.aborted)).toBe(true);
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  expect(screen.queryByText(detail.title)).toBeNull();
});

test("a writer retry refreshes the exact list and only marks existing search results stale", async () => {
  const resourceId = "00000000-0000-4000-8000-000000005031";
  const failed = knowledgeResource({
    id: resourceId,
    title: "等待人工重试.pdf",
    mediaType: "application/pdf",
    sizeBytes: 1024,
    status: "failed",
  });
  const queued = { ...failed, updatedAt: "2026-09-06T05:00:00Z", latestVersion: {
    ...failed.latestVersion!, status: "queued" as const, processingStartedAt: null,
    errorCode: null, retryable: false,
  } };
  let listRequests = 0;
  let searchRequests = 0;
  const retryRequests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && pathname.endsWith("/knowledge/search")) {
      searchRequests += 1;
      return jsonResponse({ retrievalMode: "hybrid", results: [{
        resourceId,
        resourceVersionId: failed.latestVersion!.id,
        chunkId: "00000000-0000-4000-8000-000000007031",
        title: failed.title,
        mediaType: "application/pdf",
        excerpt: "重试前仍可见的搜索结果",
        locator: { type: "pdf", page: 1 },
        score: 0.8,
      }] });
    }
    if (request.method === "POST" && pathname.endsWith("/retry")) {
      retryRequests.push(request);
      return jsonResponse(queued);
    }
    if (pathname.endsWith(`/knowledge/resources/${resourceId}`)) return jsonResponse(failed);
    if (pathname.endsWith("/knowledge/resources")) {
      listRequests += 1;
      return jsonResponse({ capabilities: { canWrite: true }, items: [
        listRequests === 1 ? failed : queued,
      ], nextCursor: null });
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const user = userEvent.setup();
  const { queryClient } = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  const row = (await screen.findByText(failed.title)).closest("li")!;
  await user.type(screen.getByLabelText("搜索项目知识"), "人工重试");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("重试前仍可见的搜索结果")).toBeVisible();
  await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
  await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));

  await waitFor(() => expect(listRequests).toBe(2));
  expect(retryRequests).toHaveLength(1);
  expect(retryRequests[0]!.headers.get("X-CSRF-Token")).toBe(IDENTITY.csrfToken);
  expect(searchRequests).toBe(1);
  expect(screen.getByText("等待处理", { selector: "dd" })).toBeVisible();
  expect(queryClient.getQueryState([
    "project-knowledge", IDENTITY.organization.id, KNOWLEDGE_PROJECT_ID,
    "search", "人工重试", 10,
  ])).toMatchObject({ isInvalidated: true, fetchStatus: "idle" });
});

test("confirmed delete cancels reads before purging facts, resets visible search, and focuses its notice", async () => {
  const resourceId = "00000000-0000-4000-8000-000000005032";
  const survivorId = "00000000-0000-4000-8000-000000005033";
  const target = knowledgeResource({
    id: resourceId, title: "需要删除的资料.pdf", mediaType: "application/pdf",
    sizeBytes: 1024, status: "failed",
  });
  const survivor = knowledgeResource({
    id: survivorId, title: "继续保留的资料.pdf", mediaType: "application/pdf",
    sizeBytes: 2048, status: "ready",
  });
  let listRequests = 0;
  let searchRequests = 0;
  let deleteRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && pathname.endsWith("/knowledge/search")) {
      searchRequests += 1;
      return jsonResponse({ retrievalMode: "hybrid", results: [{
        resourceId,
        resourceVersionId: target.latestVersion!.id,
        chunkId: "00000000-0000-4000-8000-000000007032",
        title: target.title,
        mediaType: "application/pdf",
        excerpt: "删除前可见搜索摘录",
        locator: { type: "pdf", page: 2 },
        score: 0.9,
      }] });
    }
    if (request.method === "DELETE") {
      deleteRequests += 1;
      return new Response(null, { status: 204 });
    }
    if (pathname.endsWith(`/knowledge/resources/${resourceId}`)) return jsonResponse(target);
    if (pathname.endsWith("/knowledge/resources")) {
      listRequests += 1;
      return jsonResponse({ capabilities: { canWrite: true }, items: [target, survivor], nextCursor: null });
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const user = userEvent.setup();
  const { queryClient } = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { restoredIdentity: IDENTITY },
  );
  const row = (await screen.findByText(target.title)).closest("li")!;
  await user.type(screen.getByLabelText("搜索项目知识"), "删除前查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("删除前可见搜索摘录")).toBeVisible();
  queryClient.setQueryData([
    "project-knowledge", IDENTITY.organization.id, KNOWLEDGE_PROJECT_ID,
    "citation-context", resourceId, target.latestVersion!.id,
    "00000000-0000-4000-8000-000000007032",
  ], { private: "target citation" });
  queryClient.setQueryData([
    "project-knowledge", IDENTITY.organization.id, OTHER_KNOWLEDGE_PROJECT_ID,
    "resource", resourceId,
  ], { private: "unrelated project" });
  await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
  await user.click(await screen.findByRole("button", { name: "删除资料" }));
  await user.click(screen.getByRole("button", { name: "确认删除资料" }));

  const notice = await screen.findByRole("status", { name: "资料删除结果" });
  expect(notice).toHaveTextContent(`已删除资料：${target.title}`);
  await waitFor(() => expect(notice).toHaveFocus());
  expect(screen.queryByText(target.title)).toBeNull();
  expect(screen.getByText(survivor.title)).toBeVisible();
  expect(screen.queryByText("删除前可见搜索摘录")).toBeNull();
  expect(screen.getByLabelText("搜索项目知识")).toHaveValue("");
  expect(deleteRequests).toBe(1);
  expect(listRequests).toBe(1);
  expect(searchRequests).toBe(1);
  expect(queryClient.getQueryData([
    "project-knowledge", IDENTITY.organization.id, KNOWLEDGE_PROJECT_ID,
    "resource", resourceId,
  ])).toBeUndefined();
  expect(queryClient.getQueryData([
    "project-knowledge", IDENTITY.organization.id, KNOWLEDGE_PROJECT_ID,
    "citation-context", resourceId, target.latestVersion!.id,
    "00000000-0000-4000-8000-000000007032",
  ])).toBeUndefined();
  expect(queryClient.getQueryData([
    "project-knowledge", IDENTITY.organization.id, OTHER_KNOWLEDGE_PROJECT_ID,
    "resource", resourceId,
  ])).toEqual({ private: "unrelated project" });
});

test.each([
  [200, true],
  [404, false],
] as const)("a mutation 404 rechecks the list and keeps only a still-readable workspace: list %s",
  async (listStatus, workspaceRemains) => {
    const resourceId = "00000000-0000-4000-8000-000000005034";
    const target = knowledgeResource({
      id: resourceId, title: "删除时权限变化.pdf", mediaType: "application/pdf",
      sizeBytes: 1024, status: "failed",
    });
    let listRequests = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      const pathname = new URL(request.url).pathname;
      if (request.method === "DELETE") return jsonResponse({
        code: "not_found", message: "资料不存在", traceId: "trace-delete-404",
      }, 404);
      if (pathname.endsWith(`/knowledge/resources/${resourceId}`)) return jsonResponse(target);
      if (pathname.endsWith("/knowledge/resources")) {
        listRequests += 1;
        if (listRequests > 1 && listStatus === 404) return jsonResponse({
          code: "not_found", message: "项目不存在", traceId: "trace-list-404",
        }, 404);
        return jsonResponse({ capabilities: { canWrite: listRequests === 1 }, items: [target], nextCursor: null });
      }
      throw new Error(`Unexpected request: ${request.method} ${pathname}`);
    }));
    const user = userEvent.setup();
    renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, { restoredIdentity: IDENTITY });
    const row = (await screen.findByText(target.title)).closest("li")!;
    await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
    await user.click(await screen.findByRole("button", { name: "删除资料" }));
    await user.click(screen.getByRole("button", { name: "确认删除资料" }));

    await waitFor(() => expect(listRequests).toBe(2));
    if (workspaceRemains) {
      expect(screen.getByRole("region", { name: "项目知识工作区" })).toBeVisible();
      expect(screen.getByText("只读访问")).toBeVisible();
      expect(screen.getByText("该资料已不可用，正在重新检查项目知识访问权限。")).toBeVisible();
      expect(screen.queryByRole("button", { name: "删除资料" })).toBeNull();
    } else {
      expect(await screen.findByRole("alert")).toHaveTextContent("项目不存在");
      expect(screen.queryByText(target.title)).toBeNull();
    }
  });

test("a 409 retry conflict refreshes the resource before another action is possible", async () => {
  const resourceId = "00000000-0000-4000-8000-000000005035";
  const failed = knowledgeResource({
    id: resourceId, title: "冲突后刷新.pdf", mediaType: "application/pdf",
    sizeBytes: 1024, status: "failed",
  });
  const refreshed = { ...failed, latestVersion: { ...failed.latestVersion!, retryable: false } };
  let detailReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && pathname.endsWith("/retry")) return jsonResponse({
      code: "version_not_retryable", message: "该版本当前不能重试", traceId: "trace-retry-409",
    }, 409);
    if (pathname.endsWith(`/knowledge/resources/${resourceId}`)) {
      detailReads += 1;
      return jsonResponse(detailReads === 1 ? failed : refreshed);
    }
    if (pathname.endsWith("/knowledge/resources")) return jsonResponse({
      capabilities: { canWrite: true }, items: [failed], nextCursor: null,
    });
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const user = userEvent.setup();
  renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, { restoredIdentity: IDENTITY });
  const row = (await screen.findByText(failed.title)).closest("li")!;
  await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
  await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));

  await waitFor(() => expect(detailReads).toBe(2));
  expect(screen.getByText("该版本当前不能重试")).toBeVisible();
  expect(screen.getByText("请求编号：trace-retry-409")).toBeVisible();
  expect(screen.queryByRole("button", { name: "重新处理失败版本" })).toBeNull();
  expect(screen.getByRole("button", { name: "删除资料" })).toBeEnabled();
});

test.each(["retry", "delete"] as const)(
  "a session-invalid %s mutation expires the real SessionProvider boundary",
  async (operation) => {
    const resourceId = operation === "retry"
      ? "00000000-0000-4000-8000-000000005036"
      : "00000000-0000-4000-8000-000000005037";
    const target = knowledgeResource({
      id: resourceId, title: `${operation}-会话失效.pdf`, mediaType: "application/pdf",
      sizeBytes: 1024, status: "failed",
    });
    const mutationRequests: Request[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      const pathname = new URL(request.url).pathname;
      if (request.method === "POST" || request.method === "DELETE") {
        mutationRequests.push(request);
        return jsonResponse({
          code: "session_invalid", message: "会话已过期", traceId: `trace-${operation}-401`,
        }, 401);
      }
      if (pathname.endsWith(`/knowledge/resources/${resourceId}`)) return jsonResponse(target);
      return jsonResponse({ capabilities: { canWrite: true }, items: [target], nextCursor: null });
    }));
    const user = userEvent.setup();
    const { queryClient } = renderTestRoutes(
      `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, { restoredIdentity: IDENTITY },
    );
    const row = (await screen.findByText(target.title)).closest("li")!;
    await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
    if (operation === "retry") {
      await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));
    } else {
      await user.click(await screen.findByRole("button", { name: "删除资料" }));
      await user.click(screen.getByRole("button", { name: "确认删除资料" }));
    }

    expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeVisible();
    expect(mutationRequests).toHaveLength(1);
    expect(mutationRequests[0]!.signal.aborted).toBe(true);
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
  },
);

test("a project change aborts a pending delete and its late response cannot purge the new workspace", async () => {
  const oldTarget = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005038", title: "旧项目待删除.pdf",
    mediaType: "application/pdf", sizeBytes: 1024, status: "failed",
  });
  const newTarget = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005039", title: "新项目保留.pdf",
    mediaType: "application/pdf", sizeBytes: 1024, status: "ready",
  });
  const lateDelete = trackedResponse(() => new Response(null, { status: 204 }));
  let deleteRequest: Request | null = null;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "DELETE") {
      deleteRequest = request;
      return lateDelete.promise;
    }
    if (pathname.endsWith(`/knowledge/resources/${oldTarget.id}`)) return jsonResponse(oldTarget);
    const selected = pathname.includes(OTHER_KNOWLEDGE_PROJECT_ID) ? newTarget : oldTarget;
    return jsonResponse({ capabilities: { canWrite: true }, items: [selected], nextCursor: null });
  }));
  const user = userEvent.setup();
  const rendered = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, { restoredIdentity: IDENTITY },
  );
  const row = (await screen.findByText(oldTarget.title)).closest("li")!;
  await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
  await user.click(await screen.findByRole("button", { name: "删除资料" }));
  await user.click(screen.getByRole("button", { name: "确认删除资料" }));
  await waitFor(() => expect(deleteRequest).not.toBeNull());

  rendered.navigate(`/projects/${OTHER_KNOWLEDGE_PROJECT_ID}/knowledge`);
  expect(await screen.findByText(newTarget.title)).toBeVisible();
  expect((deleteRequest as Request | null)?.signal.aborted).toBe(true);
  await act(async () => lateDelete.resolve(new Response(null, { status: 204 })));
  expect(screen.getByText(newTarget.title)).toBeVisible();
  expect(screen.queryByRole("status", { name: "资料删除结果" })).toBeNull();
});

test("a same-project session generation change aborts retry and ignores its late success", async () => {
  const oldTarget = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005040", title: "旧会话待重试.pdf",
    mediaType: "application/pdf", sizeBytes: 1024, status: "failed",
  });
  const newTarget = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005041", title: "新会话同项目资料.pdf",
    mediaType: "application/pdf", sizeBytes: 1024, status: "ready",
  });
  const queuedOld = { ...oldTarget, latestVersion: {
    ...oldTarget.latestVersion!, status: "queued" as const, errorCode: null, retryable: false,
  } };
  const lateRetry = trackedResponse(() => jsonResponse(queuedOld));
  let retryRequest: Request | null = null;
  let listRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && pathname.endsWith("/retry")) {
      retryRequest = request;
      return lateRetry.promise;
    }
    if (pathname.endsWith(`/knowledge/resources/${oldTarget.id}`)) return jsonResponse(oldTarget);
    listRequests += 1;
    return jsonResponse({
      capabilities: { canWrite: true },
      items: [listRequests === 1 ? oldTarget : newTarget],
      nextCursor: null,
    });
  }));
  const user = userEvent.setup();
  const rendered = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, { restoredIdentity: IDENTITY },
  );
  const row = (await screen.findByText(oldTarget.title)).closest("li")!;
  await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
  await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));
  await waitFor(() => expect(retryRequest).not.toBeNull());

  rendered.establishSession({
    ...IDENTITY,
    user: { ...IDENTITY.user, id: "00000000-0000-4000-8000-000000001098" },
  });

  expect(await screen.findByText(newTarget.title)).toBeVisible();
  expect((retryRequest as Request | null)?.signal.aborted).toBe(true);
  await act(async () => lateRetry.resolve(jsonResponse(queuedOld)));
  expect(screen.getByText(newTarget.title)).toBeVisible();
  expect(screen.queryByText(oldTarget.title)).toBeNull();
  expect(screen.queryByRole("status", { name: "资料删除结果" })).toBeNull();
});

test("closing and reopening the same resource aborts a mutation and never reveals its late result", async () => {
  const target = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005042", title: "重开后重新授权.pdf",
    mediaType: "application/pdf", sizeBytes: 1024, status: "failed",
  });
  const queued = { ...target, latestVersion: {
    ...target.latestVersion!, status: "queued" as const, errorCode: null, retryable: false,
  } };
  const lateRetry = trackedResponse(() => jsonResponse(queued));
  let retryRequest: Request | null = null;
  let detailReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (request.method === "POST" && pathname.endsWith("/retry")) {
      retryRequest = request;
      return lateRetry.promise;
    }
    if (pathname.endsWith(`/knowledge/resources/${target.id}`)) {
      detailReads += 1;
      return jsonResponse(target);
    }
    return jsonResponse({ capabilities: { canWrite: true }, items: [target], nextCursor: null });
  }));
  const user = userEvent.setup();
  renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, { restoredIdentity: IDENTITY });
  const row = (await screen.findByText(target.title)).closest("li")!;
  const toggle = within(row).getByRole("button", { name: "查看资料详情" });
  await user.click(toggle);
  await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));
  await waitFor(() => expect(retryRequest).not.toBeNull());

  await user.click(within(row).getByRole("button", { name: "收起资料详情" }));
  expect((retryRequest as Request | null)?.signal.aborted).toBe(true);
  await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
  expect(await screen.findByText("文件解析失败，请刷新状态或联系管理员。")).toBeVisible();
  expect(detailReads).toBe(2);
  await act(async () => lateRetry.resolve(jsonResponse(queued)));
  expect(screen.getByText("处理失败", { selector: "dd" })).toBeVisible();
  expect(screen.queryByText("等待处理", { selector: "dd" })).toBeNull();
  expect(screen.getByRole("button", { name: "重新处理失败版本" })).toBeEnabled();
});

test.each(["retry", "delete"] as const)(
  "StrictMode keeps a successful %s callback live after its setup probe",
  async (operation) => {
    const target = knowledgeResource({
      id: operation === "retry"
        ? "00000000-0000-4000-8000-000000005043"
        : "00000000-0000-4000-8000-000000005044",
      title: `StrictMode-${operation}.pdf`,
      mediaType: "application/pdf",
      sizeBytes: 1024,
      status: "failed",
    });
    const queued = { ...target, latestVersion: {
      ...target.latestVersion!, status: "queued" as const, processingStartedAt: null,
      errorCode: null, retryable: false,
    } };
    const mutationRequests: Request[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      const pathname = new URL(request.url).pathname;
      if (request.method === "POST" || request.method === "DELETE") {
        mutationRequests.push(request);
        return request.method === "POST"
          ? jsonResponse(queued)
          : new Response(null, { status: 204 });
      }
      if (pathname.endsWith(`/knowledge/resources/${target.id}`)) return jsonResponse(target);
      return jsonResponse({ capabilities: { canWrite: true }, items: [target], nextCursor: null });
    }));
    const user = userEvent.setup();
    renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, {
      restoredIdentity: IDENTITY,
      strictMode: true,
    });
    const row = (await screen.findByText(target.title)).closest("li")!;
    await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
    if (operation === "retry") {
      await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));
      expect(await screen.findByText("等待处理", { selector: "dd" })).toBeVisible();
    } else {
      await user.click(await screen.findByRole("button", { name: "删除资料" }));
      await user.click(screen.getByRole("button", { name: "确认删除资料" }));
      expect(await screen.findByRole("status", { name: "资料删除结果" })).toHaveTextContent(
        `已删除资料：${target.title}`,
      );
      expect(screen.queryByText(target.title)).toBeNull();
    }
    expect(mutationRequests).toHaveLength(1);
  },
);

test.each(["retry", "delete"] as const)(
  "a delayed old-session 401 from %s cannot expire the replacement session",
  async (operation) => {
    const oldTarget = knowledgeResource({
      id: operation === "retry"
        ? "00000000-0000-4000-8000-000000005045"
        : "00000000-0000-4000-8000-000000005046",
      title: `旧会话延迟401-${operation}.pdf`,
      mediaType: "application/pdf",
      sizeBytes: 1024,
      status: "failed",
    });
    const newTarget = knowledgeResource({
      id: operation === "retry"
        ? "00000000-0000-4000-8000-000000005047"
        : "00000000-0000-4000-8000-000000005048",
      title: `替换会话保留-${operation}.pdf`,
      mediaType: "application/pdf",
      sizeBytes: 1024,
      status: "ready",
    });
    const late401 = trackedResponse(() => jsonResponse({
      code: "session_invalid", message: "旧会话已失效", traceId: `trace-old-${operation}-401`,
    }, 401));
    let mutationRequest: Request | null = null;
    let listRequests = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      const pathname = new URL(request.url).pathname;
      if (request.method === "POST" || request.method === "DELETE") {
        mutationRequest = request;
        return late401.promise;
      }
      if (pathname.endsWith(`/knowledge/resources/${oldTarget.id}`)) return jsonResponse(oldTarget);
      listRequests += 1;
      return jsonResponse({
        capabilities: { canWrite: true },
        items: [listRequests === 1 ? oldTarget : newTarget],
        nextCursor: null,
      });
    }));
    const user = userEvent.setup();
    const rendered = renderTestRoutes(
      `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, { restoredIdentity: IDENTITY },
    );
    const row = (await screen.findByText(oldTarget.title)).closest("li")!;
    await user.click(within(row).getByRole("button", { name: "查看资料详情" }));
    if (operation === "retry") {
      await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));
    } else {
      await user.click(await screen.findByRole("button", { name: "删除资料" }));
      await user.click(screen.getByRole("button", { name: "确认删除资料" }));
    }
    await waitFor(() => expect(mutationRequest).not.toBeNull());
    rendered.establishSession({
      ...IDENTITY,
      user: { ...IDENTITY.user, id: "00000000-0000-4000-8000-000000001097" },
    });
    expect(await screen.findByText(newTarget.title)).toBeVisible();
    expect((mutationRequest as Request | null)?.signal.aborted).toBe(true);

    await act(async () => late401.resolve(jsonResponse({
      code: "session_invalid", message: "旧会话已失效", traceId: `trace-old-${operation}-401`,
    }, 401)));

    expect(screen.getByText(newTarget.title)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "登录 Cairn" })).toBeNull();
    expect(screen.queryByText(oldTarget.title)).toBeNull();
  },
);

test.each([
  [200, true],
  [404, false],
])("a detail 404 rechecks the exact resource list and keeps the workspace only when it returns %s",
  async (listRecheckStatus, workspaceRemains) => {
    const resourceId = "00000000-0000-4000-8000-000000005023";
    const detail = knowledgeResource({
      id: resourceId,
      title: "本地消失详情.pdf",
      mediaType: "application/pdf",
      sizeBytes: 1024,
      status: "ready",
    });
    let listRequests = 0;
    let searchRequests = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      const pathname = new URL(request.url).pathname;
      if (request.method === "POST") {
        searchRequests += 1;
        return jsonResponse({
          retrievalMode: "hybrid",
          results: [{
            resourceId,
            resourceVersionId: detail.latestVersion?.id,
            chunkId: "00000000-0000-4000-8000-000000007023",
            title: "详情撤销前结果",
            mediaType: "application/pdf",
            excerpt: "详情撤销前搜索摘录",
            locator: { type: "pdf", page: 1 },
            score: 0.9,
          }],
        });
      }
      if (pathname.endsWith(`/knowledge/resources/${resourceId}`)) {
        return jsonResponse({
          code: "not_found",
          message: "资料不存在",
          traceId: "trace-route-detail-404",
        }, 404);
      }
      listRequests += 1;
      if (listRequests > 1 && listRecheckStatus === 404) {
        return jsonResponse({
          code: "not_found",
          message: "项目或知识资料不存在",
          traceId: "trace-route-list-404",
        }, 404);
      }
      return jsonResponse({ capabilities: { canWrite: false }, items: [detail], nextCursor: null });
    }));
    const user = userEvent.setup();

    const { queryClient } = renderTestRoutes(
      `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
      { restoredIdentity: IDENTITY },
    );
    const row = (await screen.findByText(detail.title)).closest("li");
    await user.type(screen.getByLabelText("搜索项目知识"), "详情撤销前搜索");
    await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
    expect(await screen.findByText("详情撤销前搜索摘录")).toBeVisible();
    await user.click(within(row as HTMLElement).getByRole("button", { name: "查看资料详情" }));
    await waitFor(() => expect(listRequests).toBe(2));

    expect(searchRequests).toBe(1);
    const searchState = queryClient.getQueryState([
      "project-knowledge", IDENTITY.organization.id, KNOWLEDGE_PROJECT_ID,
      "search", "详情撤销前搜索", 10,
    ]);
    expect(searchState).toMatchObject({ isInvalidated: true, fetchStatus: "idle" });
    if (workspaceRemains) {
      expect(await screen.findByText("该资料已不可用，正在重新检查项目知识访问权限。"))
        .toBeVisible();
      expect(screen.getByRole("region", { name: "项目知识工作区" })).toBeVisible();
      expect(screen.getByText(detail.title)).toBeVisible();
    } else {
      expect(await screen.findByRole("alert")).toHaveTextContent("项目或知识资料不存在");
      expect(screen.queryByText(detail.title)).toBeNull();
      expect(screen.queryByLabelText("搜索项目知识")).toBeNull();
    }
  });

test("a project transition aborts a pending detail and cannot reveal its late response", async () => {
  const oldResource = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005024",
    title: "旧项目详情.pdf",
    mediaType: "application/pdf",
    sizeBytes: 1024,
    status: "ready",
  });
  const newResource = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005025",
    title: "新项目资料.pdf",
    mediaType: "application/pdf",
    sizeBytes: 2048,
    status: "queued",
  });
  const oldDetail = trackedResponse(() => jsonResponse(oldResource));
  let oldDetailRequest: Request | null = null;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (pathname.endsWith(`/knowledge/resources/${oldResource.id}`)) {
      oldDetailRequest = request;
      return oldDetail.promise;
    }
    const selected = pathname.includes(OTHER_KNOWLEDGE_PROJECT_ID) ? newResource : oldResource;
    return jsonResponse({ capabilities: { canWrite: false }, items: [selected], nextCursor: null });
  }));
  const user = userEvent.setup();
  const rendered = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { restoredIdentity: IDENTITY },
  );
  const oldRow = (await screen.findByText(oldResource.title)).closest("li");
  await user.click(within(oldRow as HTMLElement).getByRole("button", { name: "查看资料详情" }));
  expect(screen.getByText("正在读取资料详情…")).toBeVisible();

  rendered.navigate(`/projects/${OTHER_KNOWLEDGE_PROJECT_ID}/knowledge`);

  expect(await screen.findByText(newResource.title)).toBeVisible();
  expect((oldDetailRequest as Request | null)?.signal.aborted).toBe(true);
  await act(async () => oldDetail.resolve(jsonResponse(oldResource)));
  expect(screen.queryByText("旧项目详情.pdf", { selector: "strong" })).toBeNull();
  expect(screen.queryByRole("link", { name: /下载资料/ })).toBeNull();
});

test("a same-project session generation change destroys authorized detail state", async () => {
  const oldResource = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005026",
    title: "旧会话授权详情.pdf",
    mediaType: "application/pdf",
    sizeBytes: 1024,
    status: "ready",
  });
  const newResource = knowledgeResource({
    id: "00000000-0000-4000-8000-000000005027",
    title: "新会话资料.pdf",
    mediaType: "application/pdf",
    sizeBytes: 2048,
    status: "queued",
  });
  let listRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const pathname = new URL(request.url).pathname;
    if (pathname.endsWith(`/knowledge/resources/${oldResource.id}`)) {
      return jsonResponse(oldResource);
    }
    listRequests += 1;
    return jsonResponse({
      capabilities: { canWrite: false },
      items: [listRequests === 1 ? oldResource : newResource],
      nextCursor: null,
    });
  }));
  const user = userEvent.setup();
  const rendered = renderTestRoutes(
    `/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { restoredIdentity: IDENTITY },
  );
  const oldRow = (await screen.findByText(oldResource.title)).closest("li");
  await user.click(within(oldRow as HTMLElement).getByRole("button", { name: "查看资料详情" }));
  expect(await screen.findByRole("link", { name: /下载资料.*新标签页/ })).toBeVisible();

  rendered.establishSession({
    ...IDENTITY,
    user: { ...IDENTITY.user, id: "00000000-0000-4000-8000-000000001099" },
  });

  expect(await screen.findByText(newResource.title)).toBeVisible();
  expect(screen.queryByText(oldResource.title)).toBeNull();
  expect(screen.queryByRole("region", { name: `${oldResource.title} 资料详情` })).toBeNull();
  expect(screen.queryByRole("link", { name: /下载资料/ })).toBeNull();
  expect(listRequests).toBe(2);
});

test("the project knowledge route safely renders an RFC3339 leap second", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({
      capabilities: { canWrite: true },
      items: [{
        ...knowledgeResource({
          id: "00000000-0000-4000-8000-000000005006",
          title: "闰秒记录.pdf",
          mediaType: "application/pdf",
          sizeBytes: 1024,
          status: "ready",
        }),
        updatedAt: "1990-12-31T23:59:60Z",
      }],
      nextCursor: null,
    })),
  );

  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  const resource = (await screen.findByText("闰秒记录.pdf")).closest("li");
  expect(resource).not.toBeNull();
  expect(resource?.querySelector("time")).toHaveAttribute(
    "datetime",
    "1990-12-31T23:59:60Z",
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

test("the project knowledge route appends cursor pages without replacing loaded resources", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      requests.push(request);
      const cursor = new URL(request.url).searchParams.get("cursor");
      return cursor === null
        ? jsonResponse({
            capabilities: { canWrite: true },
            items: [knowledgeResource({
              id: "00000000-0000-4000-8000-000000005011",
              title: "第一页.pdf",
              mediaType: "application/pdf",
              sizeBytes: 1024,
              status: "ready",
            })],
            nextCursor: "cursor-second-page",
          })
        : jsonResponse({
            capabilities: { canWrite: true },
            items: [knowledgeResource({
              id: "00000000-0000-4000-8000-000000005012",
              title: "第二页.csv",
              mediaType: "text/csv",
              sizeBytes: 2048,
              status: "processing",
            })],
            nextCursor: null,
          });
    }),
  );
  const user = userEvent.setup();

  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  expect(await screen.findByText("第一页.pdf")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "加载更多知识资料" }));

  expect(await screen.findByText("第二页.csv")).toBeInTheDocument();
  expect(screen.getByText("第一页.pdf")).toBeInTheDocument();
  expect(screen.getByText("已加载 2 项")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "加载更多知识资料" })).toBeNull();
  expect(requests).toHaveLength(2);
  expect(new URL(requests[1]?.url ?? "").searchParams.get("cursor")).toBe(
    "cursor-second-page",
  );
});

test("a pagination capability downgrade removes upload UI and aborts active transfer state", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname.endsWith("/knowledge/resources")) {
      return url.searchParams.get("cursor") === null
        ? jsonResponse({
            capabilities: { canWrite: true },
            items: [knowledgeResource({
              id: "00000000-0000-4000-8000-000000005091",
              title: "权限切换资料.pdf",
              mediaType: "application/pdf",
              sizeBytes: 1024,
              status: "ready",
            })],
            nextCursor: "cursor-read-only",
          })
        : jsonResponse({
            capabilities: { canWrite: false },
            items: [],
            nextCursor: null,
          });
    }
    if (url.pathname.endsWith("/knowledge/uploads")) {
      return jsonResponse(uploadCreateResponse(), 201);
    }
    throw new Error(`Unexpected request: ${request.method} ${url.pathname}`);
  }));
  const xhrs = installRouteXhr();
  const user = userEvent.setup();
  renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, {
    restoredIdentity: IDENTITY,
  });

  await user.upload(
    await screen.findByLabelText("上传知识资料"),
    new File(["pending"], "pending-capability.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "开始上传" }));
  await waitFor(() => expect(xhrs).toHaveLength(1));
  await user.click(screen.getByRole("button", { name: "加载更多知识资料" }));

  expect(await screen.findByText("只读访问")).toBeInTheDocument();
  expect(screen.queryByLabelText("上传知识资料")).toBeNull();
  expect(screen.queryByText("pending-capability.pdf")).toBeNull();
  expect(screen.getByLabelText("搜索项目知识")).toBeInTheDocument();
  expect(xhrs[0]?.abort).toHaveBeenCalledTimes(1);
});

test("an upload-driven resource refetch revokes capability and stops upload and batch work", async () => {
  const resourceRefetch = trackedResourceResponse();
  const batchResponse = trackedBatchResponse();
  const requests: Request[] = [];
  let resourceRequests = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const pathname = new URL(request.url).pathname;
    if (request.method === "GET" && pathname.endsWith("/knowledge/resources")) {
      resourceRequests += 1;
      if (resourceRequests > 1) return resourceRefetch.promise;
      return jsonResponse({
        capabilities: { canWrite: true },
        items: [knowledgeResource({
          id: "00000000-0000-4000-8000-000000005092",
          title: "仍可只读检索.pdf",
          mediaType: "application/pdf",
          sizeBytes: 1024,
          status: "ready",
        })],
        nextCursor: null,
      });
    }
    if (request.method === "GET" && pathname.includes("/knowledge/batches/")) {
      return batchResponse.promise;
    }
    if (pathname.endsWith("/knowledge/uploads")) {
      return jsonResponse(uploadCreateResponse(2), 201);
    }
    if (pathname.endsWith(`/${UPLOAD_ID_1}/complete`)) {
      return jsonResponse(uploadCompleteResponse());
    }
    throw new Error(`Unexpected request: ${request.method} ${pathname}`);
  }));
  const xhrs = installRouteXhr();
  const user = userEvent.setup();
  const { forceRerender, queryClient } = renderTestRoutes(`/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`, {
    restoredIdentity: IDENTITY,
  });

  expect(await screen.findByText("仍可只读检索.pdf")).toBeInTheDocument();
  await user.upload(screen.getByLabelText("上传知识资料"), [
    new File(["first"], "refetch-first.pdf", { type: "application/pdf" }),
    new File(["second"], "refetch-second.pdf", { type: "application/pdf" }),
  ]);
  await user.click(screen.getByRole("button", { name: "开始上传" }));
  await waitFor(() => expect(xhrs).toHaveLength(2));
  act(() => finishRouteXhr(xhrs[0]!));
  const batchRequest = await waitFor(() => {
    expect(resourceRequests).toBe(2);
    const request = requests.find((candidate) =>
      new URL(candidate.url).pathname.includes(`/knowledge/batches/${UPLOAD_BATCH_ID}`)
    );
    expect(request).toBeDefined();
    return request!;
  });

  resourceRefetch.resolve(jsonResponse({
    capabilities: { canWrite: false },
    items: [knowledgeResource({
      id: "00000000-0000-4000-8000-000000005092",
      title: "仍可只读检索.pdf",
      mediaType: "application/pdf",
      sizeBytes: 1024,
      status: "ready",
    })],
    nextCursor: null,
  }));

  expect(await screen.findByText("只读访问")).toBeInTheDocument();
  expect(screen.getByText("仍可只读检索.pdf")).toBeInTheDocument();
  expect(screen.getByLabelText("搜索项目知识")).toBeInTheDocument();
  expect(screen.queryByLabelText("上传知识资料")).toBeNull();
  expect(screen.queryByText("refetch-first.pdf")).toBeNull();
  expect(screen.queryByText("refetch-second.pdf")).toBeNull();
  expect(xhrs[1]?.abort).toHaveBeenCalledTimes(1);
  expect(batchRequest.signal.aborted).toBe(true);

  await settleLateBatchResponse(batchResponse, forceRerender);
  expect(screen.queryByText("refetch-first.pdf")).toBeNull();
  expect(screen.queryByText("refetch-second.pdf")).toBeNull();
  expectQueriesNotToContain(queryClient, [
    "refetch-first.pdf",
    "refetch-second.pdf",
    "first.pdf",
    "second.pdf",
  ]);
});

test.each([
  [true, false, "可维护资料", "只读访问"],
  [false, true, "只读访问", "可维护资料"],
] as const)(
  "knowledge pagination updates access from canWrite=%s to canWrite=%s",
  async (initialCanWrite, nextCanWrite, initialLabel, nextLabel) => {
    const projectId = "00000000-0000-4000-8000-000000004001";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const cursor = new URL((input as Request).url).searchParams.get("cursor");
        return cursor === null
          ? jsonResponse({
              capabilities: { canWrite: initialCanWrite },
              items: [knowledgeResource({
                id: "00000000-0000-4000-8000-000000005013",
                title: "权限变化前.pdf",
                mediaType: "application/pdf",
                sizeBytes: 1024,
                status: "ready",
              })],
              nextCursor: "cursor-capability-change",
            })
          : jsonResponse({
              capabilities: { canWrite: nextCanWrite },
              items: [knowledgeResource({
                id: "00000000-0000-4000-8000-000000005014",
                title: "权限变化后.pdf",
                mediaType: "application/pdf",
                sizeBytes: 2048,
                status: "ready",
              })],
              nextCursor: null,
            });
      }),
    );
    const user = userEvent.setup();

    renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

    expect(await screen.findByText(initialLabel)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "加载更多知识资料" }));

    expect(await screen.findByText("权限变化后.pdf")).toBeInTheDocument();
    expect(screen.getByText(nextLabel)).toBeInTheDocument();
    expect(screen.queryByText(initialLabel)).toBeNull();
  },
);

test("a retryable knowledge pagination failure keeps loaded resources and recovers in place", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const nextPage = deferred<Response>();
  let paginationAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const cursor = new URL((input as Request).url).searchParams.get("cursor");
      if (cursor === null) {
        return jsonResponse({
          capabilities: { canWrite: true },
          items: [knowledgeResource({
            id: "00000000-0000-4000-8000-000000005021",
            title: "已加载资料.pdf",
            mediaType: "application/pdf",
            sizeBytes: 4096,
            status: "ready",
          })],
          nextCursor: "cursor-retry-page",
        });
      }
      paginationAttempts += 1;
      if (paginationAttempts === 1) return nextPage.promise;
      if (paginationAttempts === 2) {
        return jsonResponse({
          code: "database_unavailable",
          message: "更多知识资料暂时无法加载",
          traceId: "trace-knowledge-page-503-retry",
        }, 503);
      }
      return jsonResponse({
        capabilities: { canWrite: true },
        items: [knowledgeResource({
          id: "00000000-0000-4000-8000-000000005022",
          title: "恢复后的资料.csv",
          mediaType: "text/csv",
          sizeBytes: 8192,
          status: "ready",
        })],
        nextCursor: null,
      });
    }),
  );
  const user = userEvent.setup();

  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  expect(await screen.findByText("已加载资料.pdf")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "加载更多知识资料" }));
  expect(screen.getByRole("button", { name: "正在加载更多知识资料" })).toBeDisabled();
  nextPage.resolve(jsonResponse({
    code: "database_unavailable",
    message: "更多知识资料暂时无法加载",
    traceId: "trace-knowledge-page-503",
  }, 503));

  expect(
    await screen.findByRole("alert", undefined, { timeout: 3_000 }),
  ).toHaveTextContent("更多知识资料暂时无法加载");
  expect(screen.getByText("已加载资料.pdf")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重新加载更多知识资料" }));

  expect(await screen.findByText("恢复后的资料.csv")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(paginationAttempts).toBe(3);
});

test("a retryable network pagination failure keeps loaded resources and recovers in place", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  let paginationAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const cursor = new URL((input as Request).url).searchParams.get("cursor");
      if (cursor === null) {
        return jsonResponse({
          capabilities: { canWrite: true },
          items: [knowledgeResource({
            id: "00000000-0000-4000-8000-000000005023",
            title: "网络中断前.pdf",
            mediaType: "application/pdf",
            sizeBytes: 4096,
            status: "ready",
          })],
          nextCursor: "cursor-network-retry-page",
        });
      }
      paginationAttempts += 1;
      if (paginationAttempts <= 2) throw new TypeError("socket closed");
      return jsonResponse({
        capabilities: { canWrite: true },
        items: [knowledgeResource({
          id: "00000000-0000-4000-8000-000000005024",
          title: "网络恢复后的资料.csv",
          mediaType: "text/csv",
          sizeBytes: 8192,
          status: "ready",
        })],
        nextCursor: null,
      });
    }),
  );
  const user = userEvent.setup();

  renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

  expect(await screen.findByText("网络中断前.pdf")).toBeInTheDocument();
  expect(screen.getByText("可维护资料")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "加载更多知识资料" }));

  expect(
    await screen.findByRole("alert", undefined, { timeout: 3_000 }),
  ).toHaveTextContent("无法连接服务器，请检查网络");
  expect(screen.getByText("网络中断前.pdf")).toBeInTheDocument();
  expect(screen.getByText("可维护资料")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重新加载更多知识资料" }));

  expect(await screen.findByText("网络恢复后的资料.csv")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(paginationAttempts).toBe(3);
});

test.each([
  [false, "只读访问"],
  [true, "可维护资料"],
] as const)(
  "a concealed knowledge pagination 404 clears previously authorized resources with canWrite=%s",
  async (canWrite, capabilityLabel) => {
    const projectId = "00000000-0000-4000-8000-000000004001";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const cursor = new URL((input as Request).url).searchParams.get("cursor");
        if (cursor === null) {
          return jsonResponse({
            capabilities: { canWrite },
            items: [knowledgeResource({
              id: "00000000-0000-4000-8000-000000005031",
              title: "仍然可见的资料.pdf",
              mediaType: "application/pdf",
              sizeBytes: 4096,
              status: "ready",
            })],
            nextCursor: "cursor-forbidden-page",
          });
        }
        return jsonResponse({
          code: "not_found",
          message: "项目或知识资料不存在",
          traceId: "trace-knowledge-page-404",
        }, 404);
      }),
    );
    const user = userEvent.setup();

    renderTestRoutes(`/projects/${projectId}/knowledge`, { restoredIdentity: IDENTITY });

    expect(await screen.findByText("仍然可见的资料.pdf")).toBeInTheDocument();
    expect(screen.getByText(capabilityLabel)).toBeInTheDocument();
    expect(screen.getByText("已加载 1 项")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "加载更多知识资料" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("项目或知识资料不存在");
    expect(screen.queryByText("仍然可见的资料.pdf")).toBeNull();
    expect(screen.queryByText(capabilityLabel)).toBeNull();
    expect(screen.queryByText("已加载 1 项")).toBeNull();
    expect(screen.queryByRole("list", { name: "知识资料" })).toBeNull();
    expect(screen.queryByRole("button", { name: /加载更多知识资料/ })).toBeNull();
  },
);

test("a session-invalid knowledge pagination response clears loaded resources and ends the session", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      requests.push(request);
      const cursor = new URL(request.url).searchParams.get("cursor");
      if (cursor === null) {
        return jsonResponse({
          capabilities: { canWrite: true },
          items: [knowledgeResource({
            id: "00000000-0000-4000-8000-000000005041",
            title: "会话过期前的资料.pdf",
            mediaType: "application/pdf",
            sizeBytes: 4096,
            status: "ready",
          })],
          nextCursor: "cursor-expired-session",
        });
      }
      return jsonResponse({
        code: "session_invalid",
        message: "会话已过期",
        traceId: "trace-knowledge-page-session-401",
      }, 401);
    }),
  );
  const user = userEvent.setup();

  const { queryClient } = renderTestRoutes(
    `/projects/${projectId}/knowledge`,
    { restoredIdentity: IDENTITY },
  );

  expect(await screen.findByText("会话过期前的资料.pdf")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "加载更多知识资料" }));

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(requests).toHaveLength(2);
  expect(requests.every((request) => request.signal.aborted)).toBe(true);
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  expect(screen.queryByText("会话过期前的资料.pdf")).toBeNull();
});

test("the project knowledge assistant keeps its context with a trailing slash", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({
      capabilities: { canWrite: true },
      items: [],
      nextCursor: null,
    })),
  );
  const user = userEvent.setup();

  renderTestRoutes(`/projects/${projectId}/knowledge/`, { restoredIdentity: IDENTITY });

  expect(await screen.findByRole("heading", { level: 1, name: "项目知识" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "打开岑宁助手" }));
  expect(screen.getByRole("dialog", { name: "岑宁助手" })).toHaveTextContent("项目知识助手");
});

test("account menu exposes identity and logout without duplicating session state", async () => {
  const user = userEvent.setup();
  renderTestRoutes("/documents", { restoredIdentity: IDENTITY });

  await user.click(await screen.findByText("演示用户"));
  expect(screen.getByText("demo@cairn.dev")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "退出" }));
  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
});
