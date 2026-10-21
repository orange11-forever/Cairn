import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { AppRoutes } from "../../src/app/AppRoutes.tsx";
import { SessionProvider, useSession } from "../../src/session/SessionContext.tsx";

function StateProbe() {
  const { status, session } = useSession();
  return <output data-testid="session-state" data-status={status} data-has-session={session !== null} />;
}
function mount(route: string) {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[route]}>
    <SessionProvider><StateProbe /><AppRoutes /></SessionProvider>
  </MemoryRouter></QueryClientProvider>);
}
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });
const unavailable = () => Response.json({ code: "database_unavailable", message: "temporarily unavailable", traceId: "synthetic-trace" }, { status: 503 });
const invalidSession = () => Response.json({ code: "session_invalid", message: "anonymous", traceId: "synthetic-trace" }, { status: 401 });

test.each(["slow-restore", "error-restore", "slow-bootstrap", "error-bootstrap"] as const)("public registration mounts while %s without changing session", async state => {
  vi.stubGlobal("navigator", { locks: { request: (_name: string, _options: unknown, run: () => Promise<void>) => run() } });
  const requests: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname; requests.push(path);
    if (path === "/api/v1/auth/registration") return Response.json({ enabled: false });
    if (path === "/api/v1/session") {
      if (state.endsWith("bootstrap")) return invalidSession();
      if (state === "error-restore") return unavailable();
    } else if (path === "/api/v1/auth/login-context" && state === "error-bootstrap") return unavailable();
    return new Promise<Response>((_resolve, reject) => request.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
  }));
  const mounted = mount("/register");
  expect(screen.queryByRole("heading", { name: "创建 Cairn 账号" }) !== null).toBe(true);
  await waitFor(() => expect(requests.includes("/api/v1/auth/registration")).toBe(true));
  await waitFor(() => expect(screen.getByTestId("session-state").getAttribute("data-status")).toBe(state.startsWith("error") ? "restore-error" : "restoring"));
  expect(screen.getByTestId("session-state").getAttribute("data-has-session")).toBe("false");
  expect(requests.includes("/api/v1/auth/register")).toBe(false);
  expect(requests.includes("/api/v1/logout")).toBe(false);
  mounted.unmount();
  await act(async () => { await Promise.resolve(); });
});

test.each(["/register/verify#token=retired-proof", "/password/forgot", "/password/reset#token=retired-proof"])("retired route %s cannot submit email operations", async route => {
  const requests: string[] = [];
  vi.stubGlobal("navigator", { locks: { request: (_name: string, _options: unknown, run: () => Promise<void>) => run() } });
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname; requests.push(path);
    if (path === "/api/v1/session") return invalidSession();
    if (path === "/api/v1/auth/login-context") return new Response(null, { status: 204 });
    if (path === "/api/v1/auth/providers") return Response.json({ providers: [] });
    throw new Error(`Unexpected request: ${path}`);
  }));
  mount(route);
  await screen.findByRole("button", { name: "登录" });
  expect(screen.queryByRole("button", { name: /发送.*邮件|验证邮箱|重置密码/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /找回|忘记密码/ })).not.toBeInTheDocument();
  expect(requests.some(path => path.includes("/password/") || path.includes("/register/"))).toBe(false);
});
