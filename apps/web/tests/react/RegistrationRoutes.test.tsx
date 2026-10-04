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

test.each(["slow-restore", "error-restore", "slow-bootstrap", "error-bootstrap"] as const)("public verification scrubs while %s without authenticating or resetting session", async state => {
  window.history.replaceState(null, "", "/register/verify#token=synthetic-proof");
  const requests: { method: string; path: string }[] = [];
  vi.stubGlobal("navigator", { locks: { request: (_name: string, _options: unknown, run: () => Promise<void>) => run() } });
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname;
    requests.push({ method: request.method, path });
    if (path === "/api/v1/session") {
      if (state.endsWith("bootstrap")) return invalidSession();
      if (state === "error-restore") return unavailable();
    } else if (path === "/api/v1/auth/login-context" && state === "error-bootstrap") return unavailable();
    return new Promise<Response>((_resolve, reject) => request.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true }));
  }));
  const mounted = mount("/register/verify#token=synthetic-proof");
  expect(window.location.hash === "").toBe(true);
  expect(screen.queryByRole("heading", { name: "验证邮箱" }) !== null).toBe(true);
  await waitFor(() => expect(screen.getByTestId("session-state").getAttribute("data-status")).toBe(state.startsWith("error") ? "restore-error" : "restoring"));
  if (state.endsWith("bootstrap")) await waitFor(() => expect(requests.some(request => request.path === "/api/v1/auth/login-context")).toBe(true));
  expect(screen.getByTestId("session-state").getAttribute("data-has-session")).toBe("false");
  expect(requests.some(request => request.path === "/api/v1/auth/register/verify")).toBe(false);
  expect(requests.some(request => request.path === "/api/v1/logout")).toBe(false);
  expect(requests.filter(request => request.path === "/api/v1/session")).toHaveLength(1);
  mounted.unmount();
  await act(async () => { await Promise.resolve(); });
});

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

test("a delayed existing session restores normally without replacing the public verification page", async () => {
  window.history.replaceState(null, "", "/register/verify#token=synthetic-proof");
  let finish!: (response: Response) => void;
  const requests: { method: string; path: string }[] = [];
  vi.stubGlobal("fetch", vi.fn((request: Request) => {
    requests.push({ method: request.method, path: new URL(request.url).pathname });
    return new Promise<Response>(resolve => { finish = resolve; });
  }));
  mount("/register/verify#token=synthetic-proof");
  expect(window.location.hash === "").toBe(true);
  expect(screen.getByTestId("session-state").getAttribute("data-status")).toBe("restoring");
  const existing = {
    user: { id: "00000000-0000-4000-8000-000000001001", email: null, displayName: null },
    organization: { id: "00000000-0000-4000-8000-000000002001", name: "synthetic", slug: "synthetic" },
    membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" }, csrfToken: "synthetic-material",
  };
  await waitFor(() => expect(typeof finish).toBe("function"));
  await act(async () => finish(Response.json(existing)));
  await waitFor(() => expect(screen.getByTestId("session-state").getAttribute("data-status")).toBe("authenticated"));
  expect(screen.getByTestId("session-state").getAttribute("data-has-session")).toBe("true");
  expect(screen.queryByRole("heading", { name: "验证邮箱" }) !== null).toBe(true);
  expect(requests).toEqual([{ method: "GET", path: "/api/v1/session" }]);
});
