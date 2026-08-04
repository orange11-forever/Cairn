import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
  expect(within(navigation).getAllByRole("link")).toHaveLength(2);
  expect(within(navigation).getByRole("link", { name: "知识文档" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(within(navigation).queryByRole("link", { name: /项目|Agent|治理/ })).toBeNull();
  expect(screen.getByRole("heading", { level: 1, name: "知识文档" })).toBeInTheDocument();
  expect(screen.getByText("管理用于企业问答的内部资料。")).toBeInTheDocument();

  const assistantTrigger = screen.getByRole("button", { name: "打开看板娘助手" });
  expect(assistantTrigger).toHaveAttribute("aria-expanded", "false");
  await user.click(assistantTrigger);
  expect(screen.getByRole("dialog", { name: "看板娘助手" })).toHaveTextContent("知识文档");
  expect(assistantTrigger).toHaveAttribute("aria-expanded", "true");
});

test("account menu exposes identity and logout without duplicating session state", async () => {
  const user = userEvent.setup();
  renderTestRoutes("/documents", { restoredIdentity: IDENTITY });

  await user.click(await screen.findByText("演示用户"));
  expect(screen.getByText("demo@cairn.dev")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "退出" }));
  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
});
