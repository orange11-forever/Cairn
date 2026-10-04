import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { OAuthFinalize } from "../../src/components/OAuthFinalize.tsx";
import { SessionProvider } from "../../src/session/SessionContext.tsx";
import { ApiError } from "../../src/api/errors.ts";

const identity = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: null, displayName: "演示用户" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" as const }, csrfToken: "csrf-test",
};
function mount() {
  const onSuccess = vi.fn();
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <SessionProvider sessionApi={{ restore: async () => { throw new ApiError("http", "expired", { status: 401, code: "session_invalid" }); }, prepareLogin: async () => undefined, logout: async () => undefined }}>
      <OAuthFinalize onSuccess={onSuccess} />
    </SessionProvider>
  </MemoryRouter></QueryClientProvider>);
  return onSuccess;
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("verified callback requires a single explicit confirmation before establishing the account", async () => {
  const fetch = vi.fn(async (_input: RequestInfo | URL) => new Response(JSON.stringify(identity), { headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  const onSuccess = mount();
  expect(fetch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "完成登录" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(identity));
  expect(fetch).toHaveBeenCalledTimes(1);
  const request = fetch.mock.calls[0]?.[0] as unknown as Request;
  expect(new URL(request.url).pathname).toBe("/api/v1/auth/oauth/finalize");
  expect(request.method).toBe("POST");
  expect(request.credentials).toBe("include");
});

test("expired pending authorization shows a safe restart without changing the account", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "session_changed", message: "授权已失效，请重新登录", traceId: "test" }), { status: 409, headers: { "Content-Type": "application/json" } })));
  const onSuccess = mount();
  await userEvent.click(screen.getByRole("button", { name: "完成登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("授权已失效");
  expect(onSuccess).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "重新开始登录" })).toBeEnabled();
});
