import { QueryClientProvider } from "@tanstack/react-query";
import type { UserDto } from "@cairn/contracts";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLayoutEffect } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../src/app/AppRoutes.tsx";
import { createAppQueryClient } from "../../src/app/queryClient.ts";
import { SessionProvider, useSession } from "../../src/session/SessionContext.tsx";

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
  const { session, establishSession } = useSession();

  useLayoutEffect(() => {
    if (user !== undefined && session === null) establishSession(user);
  }, [establishSession, session, user]);

  return user !== undefined && session === null ? null : children;
}

function renderTestRoutes(path: string, options: { initialUser?: UserDto } = {}) {
  const queryClient = createAppQueryClient();

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <SessionProvider>
          <InitialSession user={options.initialUser}>
            <AppRoutes />
          </InitialSession>
        </SessionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ user: USER })));
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
