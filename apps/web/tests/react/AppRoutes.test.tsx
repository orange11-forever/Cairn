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

  return render(
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
  ["contract", () => jsonResponse({ items: [], nextCursor: null })],
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
