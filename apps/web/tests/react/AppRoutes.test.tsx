import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../src/app/AppRoutes.tsx";
import type { IdentityContext } from "../../src/api/auth.ts";
import { ApiError } from "../../src/api/errors.ts";
import { createAppQueryClient } from "../../src/app/queryClient.ts";
import { SessionProvider, type SessionApi } from "../../src/session/SessionContext.tsx";
import { ThemeProvider } from "../../src/theme/ThemeContext.tsx";

const IDENTITY: IdentityContext = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
  csrfToken: "csrf-test-token",
};

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

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

function fakeSessionApi(overrides: Partial<SessionApi> = {}): SessionApi {
  return {
    restore: async () => { throw new ApiError("http", "无会话", { status: 401, code: "session_invalid" }); },
    logout: async () => undefined,
    ...overrides,
  };
}

function renderTestRoutes(path: string, options: { restoredIdentity?: IdentityContext; sessionApi?: SessionApi } = {}) {
  const queryClient = createAppQueryClient();

  const result = render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <SessionProvider sessionApi={options.sessionApi ?? fakeSessionApi()} restoredIdentity={options.restoredIdentity}>
            <AppRoutes />
          </SessionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { ...result, queryClient };
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
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("unauthenticated document route redirects to login", async () => {
  renderTestRoutes("/documents");

  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Cairn 看板娘" })).toBeInTheDocument();
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

  const assistantTrigger = screen.getByRole("button", { name: "打开看板娘助手" });
  expect(assistantTrigger).toHaveAttribute("aria-expanded", "false");
  await user.click(assistantTrigger);
  expect(screen.getByRole("dialog", { name: "看板娘助手" })).toHaveTextContent("知识文档");
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
  await user.click(screen.getByRole("button", { name: "打开看板娘助手" }));
  expect(screen.getByRole("dialog", { name: "看板娘助手" })).toHaveTextContent("项目任务助手");
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

  await user.click(screen.getByRole("button", { name: "打开看板娘助手" }));
  expect(screen.getByRole("dialog", { name: "看板娘助手" })).toHaveTextContent("项目知识助手");
});

test("a read-only project reader can search real project knowledge", async () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "POST") {
      return jsonResponse({
        retrievalMode: "hybrid",
        results: [{
          resourceId: "00000000-0000-4000-8000-000000005001",
          resourceVersionId: "00000000-0000-4000-8000-000000006001",
          chunkId: "00000000-0000-4000-8000-000000007001",
          title: "只读资料",
          mediaType: "application/pdf",
          excerpt: "只读权限仍可检索",
          locator: { type: "pdf", page: 2 },
          score: 0.8,
        }],
      });
    }
    return jsonResponse({
      capabilities: { canWrite: false },
      items: [knowledgeResource({
        id: "00000000-0000-4000-8000-000000005001",
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
  await user.type(screen.getByLabelText("搜索项目知识"), "只读检索");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("只读权限仍可检索")).toBeInTheDocument();
  const searchRequest = requests.find((request) => request.method === "POST");
  expect(searchRequest).toBeDefined();
  expect(searchRequest!.headers.get("X-CSRF-Token")).toBe("csrf-test-token");
  await expect(searchRequest!.clone().json()).resolves.toEqual({ query: "只读检索", limit: 10 });
});

test("a concealed search 404 clears all previously authorized project knowledge", async () => {
  let searches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "GET") {
      return jsonResponse({
        capabilities: { canWrite: true },
        items: [knowledgeResource({
          id: "00000000-0000-4000-8000-000000005001",
          title: "撤权前资料.pdf",
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
  const { queryClient } = renderTestRoutes(
    "/projects/00000000-0000-4000-8000-000000004001/knowledge",
    { restoredIdentity: IDENTITY },
  );
  expect(await screen.findByText("撤权前资料.pdf")).toBeInTheDocument();
  await user.type(screen.getByLabelText("搜索项目知识"), "第一轮查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));
  expect(await screen.findByText("撤权前结果")).toBeInTheDocument();
  await user.clear(screen.getByLabelText("搜索项目知识"));
  await user.type(screen.getByLabelText("搜索项目知识"), "第二轮查询");
  await user.click(screen.getByRole("button", { name: "搜索项目知识" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("项目或知识资料不存在");
  for (const staleText of ["撤权前资料.pdf", "撤权前结果", "可维护资料"]) {
    expect(screen.queryByText(staleText)).toBeNull();
  }
  expect(screen.queryByRole("list", { name: "知识资料" })).toBeNull();
  expect(screen.queryByLabelText("搜索项目知识")).toBeNull();
  expect(queryClient.getQueriesData({
    queryKey: ["project-knowledge", IDENTITY.organization.id, "00000000-0000-4000-8000-000000004001"],
  }).every(([, data]) => data === undefined)).toBe(true);
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
  await user.click(screen.getByRole("button", { name: "打开看板娘助手" }));
  expect(screen.getByRole("dialog", { name: "看板娘助手" })).toHaveTextContent("项目知识助手");
});

test("account menu exposes identity and logout without duplicating session state", async () => {
  const user = userEvent.setup();
  renderTestRoutes("/documents", { restoredIdentity: IDENTITY });

  await user.click(await screen.findByText("演示用户"));
  expect(screen.getByText("demo@cairn.dev")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "退出" }));
  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
});
