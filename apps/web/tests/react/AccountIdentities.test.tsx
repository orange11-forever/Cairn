import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { AccountIdentitiesPage } from "../../src/pages/AccountIdentitiesPage.tsx";
import { SessionProvider } from "../../src/session/SessionContext.tsx";

const identity = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" as const }, csrfToken: "csrf-test",
};
const linkedId = "00000000-0000-4000-8000-000000004001";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
function mount(restoredIdentity: import("../../src/api/auth.ts").IdentityContext = identity) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={queries}>
    <SessionProvider restoredIdentity={restoredIdentity}><AccountIdentitiesPage /></SessionProvider>
  </QueryClientProvider></MemoryRouter>);
  return queries;
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("显示当前账号绑定状态并在明确确认后携带 CSRF 解绑", async () => {
  const deletes: Request[] = [];
  let removed = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "DELETE") {
      deletes.push(request); removed = true;
      return new Response(null, { status: 204 });
    }
    if (path.endsWith("providers")) return response([{ provider: "github", enabled: true }, { provider: "feishu", enabled: false }]);
    return response({ passwordAvailable: true, identities: removed ? [] : [{ id: linkedId, provider: "github", displayName: "My Github", createdAt: "2026-10-02T00:00:00Z" }] });
  }));
  const queries = mount();
  expect(await screen.findByText("My Github")).toBeInTheDocument();
  expect(screen.getByText("当前账号：演示用户 · demo@cairn.dev")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "绑定 飞书" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "解绑 GitHub" }));
  expect(deletes).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "确认解绑" }));
  await waitFor(() => expect(deletes).toHaveLength(1));
  expect(deletes[0]!.headers.get("X-CSRF-Token")).toBe("csrf-test");
  expect(deletes[0]!.credentials).toBe("include");
  expect(new URL(deletes[0]!.url).pathname).toBe("/api/v1/auth/identities/" + linkedId);
  expect(await screen.findByRole("button", { name: "绑定 GitHub" })).toBeInTheDocument();
  queries.clear();
});

test("近期认证不足时显示重新登录入口并保留账号状态", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "POST") return response({ code: "reauthentication_required", message: "请重新登录后管理登录方式", traceId: "test" }, 403);
    if (new URL(request.url).pathname.endsWith("providers")) return response([{ provider: "github", enabled: true }, { provider: "feishu", enabled: true }]);
    return response({ passwordAvailable: true, identities: [] });
  }));
  const queries = mount();
  await userEvent.click(await screen.findByRole("button", { name: "绑定 GitHub" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("重新登录");
  expect(screen.getByRole("button", { name: "重新登录" })).toBeInTheDocument();
  expect(screen.getByText("当前账号：演示用户 · demo@cairn.dev")).toBeInTheDocument();
  queries.clear();
});


test("OAuth account without email shows its name and missing-email status", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (new URL((input as Request).url).pathname.endsWith("providers")) return response([{ provider: "github", enabled: true }, { provider: "feishu", enabled: true }]);
    return response({ passwordAvailable: false, identities: [] });
  }));
  const queries = mount({ ...identity, user: { ...identity.user, email: null } });
  expect(await screen.findByText("尚未设置")).toBeInTheDocument();
  expect(screen.getByText(/当前账号：演示用户/)).toBeInTheDocument();
  expect(screen.getByText(/未提供邮箱/)).toBeInTheDocument();
  queries.clear();
});
