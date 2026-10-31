import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectRepository } from "../../src/components/projects/ProjectRepository.tsx";
import { SessionProvider } from "../../src/session/SessionContext.tsx";

const identity = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" as const }, csrfToken: "csrf-test",
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
function mount() {
  vi.stubGlobal("chrome", { webview: { postMessage: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<MemoryRouter><QueryClientProvider client={client}><SessionProvider restoredIdentity={identity}>
    <ProjectRepository projectId="00000000-0000-4000-8000-000000004001" canWrite />
  </SessionProvider></QueryClientProvider></MemoryRouter>);
  return { client, view };
}

test("binds an existing local repository and only removes its association after confirmation", async () => {
  let binding: object | null = null;
  const mutations: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.url.endsWith("connection")) return json({ configured: false, status: "disconnected", account: null, message: null });
    if (request.method === "PUT") {
      mutations.push(request); const body = await request.clone().json();
      binding = { localPath: body.localPath, branch: "main", repository: null, account: null };
      return json(binding);
    }
    if (request.method === "DELETE") { mutations.push(request); binding = null; return new Response(null, { status: 204 }); }
    return json({ binding, gitAvailable: true, message: null });
  }));
  const { client } = mount();
  await userEvent.click(screen.getByText("代码仓库"));
  await userEvent.type(await screen.findByLabelText("本地仓库目录"), "D:\\code\\project");
  await userEvent.click(screen.getByRole("button", { name: "关联本地仓库" }));
  expect(await screen.findByText("main")).toBeVisible();
  expect(mutations[0]?.headers.get("X-CSRF-Token")).toBe("csrf-test");
  await userEvent.click(screen.getByRole("button", { name: "解除关联" }));
  expect(mutations).toHaveLength(1);
  expect(screen.getByText(/确认解除此项目的本机关联/)).toHaveTextContent("代码文件会保留");
  await userEvent.click(screen.getByRole("button", { name: "确认解除关联" }));
  await waitFor(() => expect(mutations).toHaveLength(2));
  expect(await screen.findByText("尚未关联代码仓库")).toBeVisible();
  client.clear();
});

test("clone failure is visible and never displays a new saved association", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.url.endsWith("connection")) return json({ configured: true, status: "connected", account: { id: 123, login: "octo" }, message: null });
    if (request.url.includes("/github/repositories")) return json({ items: [{ id: 42, fullName: "octo/private", private: true, defaultBranch: "main", canPush: false, url: "https://github.com/octo/private" }], nextPage: null });
    if (request.method === "PUT") return json({ code: "git_failed", message: "Git 克隆失败；目标目录已保留", traceId: "clone-test" }, 409);
    return json({ binding: null, gitAvailable: true, message: null });
  }));
  const { client } = mount();
  await userEvent.click(screen.getByText("代码仓库"));
  await userEvent.click(await screen.findByLabelText("克隆 GitHub 仓库"));
  await userEvent.selectOptions(await screen.findByLabelText("GitHub 仓库"), "42");
  await userEvent.type(screen.getByLabelText("新目录完整路径"), "D:\\code\\private");
  await userEvent.click(screen.getByRole("button", { name: "克隆并关联" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("目标目录已保留");
  expect(screen.getByText("尚未关联代码仓库")).toBeVisible();
  client.clear();
});
