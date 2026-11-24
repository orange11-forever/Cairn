import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../src/app/AppRoutes.tsx";
import { SessionProvider } from "../../src/session/SessionContext.tsx";
import { ThemeProvider } from "../../src/theme/ThemeContext.tsx";

const projectId = "00000000-0000-4000-8000-000000000010";
const firstId = "00000000-0000-4000-8000-000000000011";
const secondId = "00000000-0000-4000-8000-000000000012";
const identity = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "test@example.com", displayName: "测试账号" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "test", name: "测试组织" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" as const }, csrfToken: "csrf-test",
};

function mount(module: "knowledge" | "agents" = "agents", denied = false) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("prefers-reduced-motion"), addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  const project = { id: projectId, name: "智能体验收项目", description: null, createdAt: "2026-11-07T00:00:00Z", updatedAt: "2026-11-07T00:00:00Z" };
  const profiles = [{ id: firstId, name: "岑宁", instructions: "先核对资料", modelId: "fast" as string | null, enabledSkillIds: [] as string[], avatarDataUrl: null, revision: 1 }];
  let active = profiles[0]!;
  let revision = 1;
  const writes: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method !== "GET") writes.push(request.clone());
    if (denied) return Response.json({ code: "not_found", message: "项目不存在或不可访问", traceId: "agents-denied" }, { status: 404 });
    if (path.endsWith(`/projects/${projectId}`)) return Response.json(project);
    if (path.endsWith("/projects")) return Response.json({ items: [project], nextCursor: null });
    if (path.endsWith("/answer-model")) return Response.json({ configured: true, model: "fast-model", protocol: "openai-compatible", defaultModelId: "fast", models: [{ id: "fast", name: "快速模型", model: "fast-model", protocol: "openai-compatible" }] });
    if (path.endsWith("/assistant-settings")) {
      if (request.method === "PUT") { const { expectedRevision, ...body } = await request.json(); expect(expectedRevision).toBe(revision); Object.assign(active, body, { revision: ++revision }); }
      return Response.json(active);
    }
    if (path.endsWith("/assistants")) {
      if (request.method === "GET") return Response.json({ items: profiles.map(({ id, name, modelId, avatarDataUrl }) => ({ id, name, modelId, avatarDataUrl })) });
      const { expectedRevision, ...body } = await request.json();
      expect(expectedRevision).toBe(revision);
      active = { ...body, id: secondId, avatarDataUrl: null, revision: ++revision }; profiles.push(active);
      return Response.json(active, { status: 201 });
    }
    if (path.endsWith("/select")) {
      const { expectedRevision } = await request.json(); expect(expectedRevision).toBe(revision);
      active = profiles.find(item => path.includes(item.id))!; active.revision = ++revision;
      return Response.json(active);
    }
    if (path.endsWith("/skills")) return Response.json({ items: [] });
    if (path.endsWith("/conversations")) return Response.json({ items: [], nextCursor: null });
    if (path.endsWith("/resources")) return Response.json({ items: [], nextCursor: null, capabilities: { canWrite: false } });
    throw new Error(`Unexpected ${request.method} ${path}`);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter initialEntries={[`/projects/${projectId}/${module}`]}><ThemeProvider><QueryClientProvider client={client}>
    <SessionProvider restoredIdentity={identity}><AppRoutes /></SessionProvider>
  </QueryClientProvider></ThemeProvider></MemoryRouter>);
  return { profiles, writes, user: userEvent.setup(), client };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); });

test("sidebar management creates and edits the same project assistant without leaving the page", async () => {
  const { user, profiles, writes, client } = mount("knowledge");
  await waitFor(() => expect(screen.getByLabelText("当前助手")).toHaveValue(firstId));
  await user.type(screen.getByLabelText("向项目知识提问"), "保留原助手的问题草稿");
  await user.click(within(screen.getByRole("navigation", { name: "主导航" })).getByRole("link", { name: "智能体" }));
  expect(await screen.findByRole("heading", { name: "智能体", level: 1 })).toBeVisible();
  await user.click(await screen.findByRole("button", { name: "新建智能体" }));
  await waitFor(() => expect(screen.getByLabelText("当前助手")).toHaveValue(secondId));
  expect(screen.getByRole("heading", { name: "智能体", level: 1 })).toBeVisible();
  await user.clear(screen.getByLabelText("助手名称"));
  await user.type(screen.getByLabelText("助手名称"), "代码复核员");
  await user.type(screen.getByLabelText("行为说明"), "核对改动与测试结果");
  await user.selectOptions(screen.getByLabelText("回答模型"), "fast");
  await user.click(screen.getByRole("button", { name: "保存助手配置" }));
  await screen.findByText("助手配置已保存。");
  expect(profiles[1]).toMatchObject({ name: "代码复核员", instructions: "核对改动与测试结果", modelId: "fast" });
  expect(writes).toHaveLength(2);
  expect(writes[0]!.url).toContain(`/projects/${projectId}/knowledge/assistants`);
  expect(writes[0]!.headers.get("X-CSRF-Token")).toBe("csrf-test");
  await user.selectOptions(screen.getByLabelText("当前助手"), firstId);
  await waitFor(() => expect(screen.getByLabelText("助手名称")).toHaveValue("岑宁"));
  expect(screen.getByRole("heading", { name: "智能体", level: 1 })).toBeVisible();
  await user.click(within(screen.getByRole("navigation", { name: "主导航" })).getByRole("link", { name: "知识" }));
  expect(await screen.findByLabelText("向项目知识提问")).toHaveValue("保留原助手的问题草稿");
  client.clear();
});

test("the direct agents route with denied project access exposes no creation form", async () => {
  const { writes, client } = mount("agents", true);
  expect(await screen.findByRole("alert")).toHaveTextContent("项目不存在或不可访问");
  expect(screen.queryByRole("button", { name: "新建智能体" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("助手名称")).not.toBeInTheDocument();
  expect(writes).toHaveLength(0);
  client.clear();
});
