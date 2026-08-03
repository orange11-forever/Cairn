import { QueryClientProvider } from "@tanstack/react-query";
import type { UserDto } from "@cairn/contracts";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLayoutEffect, useRef } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../src/app/AppRoutes.tsx";
import { createAppQueryClient } from "../../src/app/queryClient.ts";
import { SessionProvider, useSession } from "../../src/session/SessionContext.tsx";
import { ThemeProvider } from "../../src/theme/ThemeContext.tsx";

const USER: UserDto = {
  id: "00000000-0000-4000-8000-000000001001",
  email: "demo@cairn.dev",
  displayName: "演示用户",
  role: "member",
};

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function InitialSession({ user, children }: { user?: UserDto; children: React.ReactNode }) {
  const { establishSession } = useSession();
  const initialized = useRef(user === undefined);

  useLayoutEffect(() => {
    if (user !== undefined && !initialized.current) {
      initialized.current = true;
      establishSession(user);
    }
  }, [establishSession, user]);

  return initialized.current ? children : null;
}

function renderTestRoutes(path: string, options: { initialUser?: UserDto } = {}) {
  const queryClient = createAppQueryClient();

  return render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <SessionProvider>
            <InitialSession user={options.initialUser}>
              <AppRoutes />
            </InitialSession>
          </SessionProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ user: USER })));
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
});

test("login reaches documents and NavLink reaches ask without a reload", async () => {
  const user = userEvent.setup();
  renderTestRoutes("/login");

  await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
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

test("authenticated login and unknown routes resolve to documents", async () => {
  const first = renderTestRoutes("/login", { initialUser: USER });
  expect(await screen.findByRole("heading", { name: "知识文档" })).toBeInTheDocument();
  first.unmount();

  renderTestRoutes("/not-a-route", { initialUser: USER });
  expect(await screen.findByRole("heading", { name: "知识文档" })).toBeInTheDocument();
});

test("authenticated routes use one extensible application shell", async () => {
  const user = userEvent.setup();
  renderTestRoutes("/documents", { initialUser: USER });

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
  renderTestRoutes("/documents", { initialUser: USER });

  await user.click(await screen.findByText("演示用户"));
  expect(screen.getByText("demo@cairn.dev")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "退出" }));
  expect(await screen.findByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
});
