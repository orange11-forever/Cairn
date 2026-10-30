import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectConversationsProvider } from "../../src/components/knowledge/ProjectConversationsContext.tsx";
import { KnowledgeConversations } from "../../src/components/knowledge/KnowledgeConversations.tsx";

const pid = "00000000-0000-4000-8000-000000000010", firstId = "00000000-0000-4000-8000-000000000011", secondId = "00000000-0000-4000-8000-000000000012";
afterEach(() => vi.unstubAllGlobals());

function mount(loseCreateResponse = false) {
  const profiles = [{ id: firstId, name: "岑宁", instructions: "先列计划", enabledSkillIds: ["knowledge-summary"], avatarDataUrl: null as string | null, revision: 1, modelId: "fast" as string | null }];
  let active = profiles[0]!, revision = 1, creates = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request, path = new URL(request.url).pathname;
    if (path.endsWith("/answer-model")) return Response.json({ configured: true, model: "synthetic-fast", protocol: "openai-compatible", defaultModelId: "fast", models: [{ id: "fast", name: "快速模型", model: "synthetic-fast", protocol: "openai-compatible" }] });
    if (path.endsWith("/assistant-settings")) {
      if (request.method === "PUT") { const { expectedRevision, ...body } = await request.json(); expect(expectedRevision).toBe(revision); Object.assign(active, body, { revision: ++revision }); }
      return Response.json(active);
    }
    if (path.endsWith("/assistants")) {
      if (request.method === "GET") return Response.json({ items: profiles.map(({ id, name, modelId, avatarDataUrl }) => ({ id, name, modelId, avatarDataUrl })) });
      const { expectedRevision, ...body } = await request.json(); expect(expectedRevision).toBe(revision);
      creates++; active = { ...body, id: secondId, revision: ++revision }; profiles.push(active);
      if (loseCreateResponse) throw new TypeError("response lost after create");
      return Response.json(active, { status: 201 });
    }
    if (path.endsWith("/select")) {
      const body = await request.json(); expect(body.expectedRevision).toBe(revision);
      active = profiles.find(item => path.includes(item.id))!; active.revision = ++revision;
      return Response.json(active);
    }
    if (path.endsWith("/skills")) return Response.json({ items: [{ id: "knowledge-summary", name: "资料摘要", description: "概括事实", defaultQuestion: "请总结当前项目资料", version: "v1", capabilities: ["knowledge.read"], sourceType: "builtin", runnable: true, warnings: [] }] });
    if (path.endsWith("/conversations")) return Response.json({ items: [], nextCursor: null });
    throw new Error(`Unexpected ${request.method} ${path}`);
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><ProjectConversationsProvider organizationId="org" userId="user" projectId={pid} generation={1} csrfToken="csrf" sessionSignal={new AbortController().signal}><KnowledgeConversations organizationId="org" projectId={pid} sessionSignal={new AbortController().signal} onAccessUnavailable={vi.fn()} /></ProjectConversationsProvider></MemoryRouter></QueryClientProvider>);
  return { profiles, creates: () => creates, switchElsewhere: () => {
    active = { id: secondId, avatarDataUrl: null, name: "另一助手", instructions: "不同的说明", enabledSkillIds: [], modelId: null, revision: ++revision };
    profiles.push(active);
  } };
}

test("create and switch keep each assistant configuration and preserve the question draft", async () => {
  const { profiles } = mount();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("向项目知识提问"), "保留这个问题");
  await user.click(screen.getByText("助手与技能"));
  const select = await screen.findByLabelText("当前助手");
  await waitFor(() => expect(select).toHaveValue(firstId));
  await user.click(screen.getByRole("button", { name: "新建助手" }));
  await waitFor(() => expect(select).toHaveValue(secondId));
  expect(screen.getByLabelText("行为说明")).toHaveValue("");
  expect(screen.getByLabelText("启用：资料摘要")).not.toBeChecked();
  await user.clear(screen.getByLabelText("助手名称"));
  await user.type(screen.getByLabelText("助手名称"), "复核助手");
  await user.type(screen.getByLabelText("行为说明"), "指出风险");
  expect(select).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "保存助手配置" }));
  await screen.findByText("助手配置已保存。");
  await user.selectOptions(select, firstId);
  await waitFor(() => expect(screen.getByLabelText("行为说明")).toHaveValue("先列计划"));
  expect(screen.getByLabelText("启用：资料摘要")).toBeChecked();
  expect(screen.getByLabelText("回答模型")).toHaveValue("fast");
  expect(screen.getByLabelText("向项目知识提问")).toHaveValue("保留这个问题");
  await user.selectOptions(select, secondId);
  await waitFor(() => expect(screen.getByLabelText("助手名称")).toHaveValue("复核助手"));
  expect(screen.getByLabelText("行为说明")).toHaveValue("指出风险");
  expect(profiles).toHaveLength(2);
});

test("lost create response requires explicit reread and recovers without a duplicate create", async () => {
  const state = mount(true);
  const user = userEvent.setup();
  await user.click(screen.getByText("助手与技能"));
  await waitFor(() => expect(screen.getByLabelText("当前助手")).toHaveValue(firstId));
  await user.click(screen.getByRole("button", { name: "新建助手" }));
  await screen.findByText(/助手切换或创建结果尚未确认/);
  expect(screen.getByRole("button", { name: "新建助手" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重新读取助手与技能" }));
  await waitFor(() => expect(screen.getByLabelText("当前助手")).toHaveValue(secondId));
  await waitFor(() => expect(screen.getByRole("button", { name: "新建助手" })).toBeEnabled());
  expect(state.creates()).toBe(1);
});

test("rereading a different active assistant never retargets an unsaved configuration draft", async () => {
  const state = mount();
  const user = userEvent.setup();
  await user.click(screen.getByText("助手与技能"));
  await waitFor(() => expect(screen.getByLabelText("当前助手")).toHaveValue(firstId));
  await user.clear(screen.getByLabelText("行为说明"));
  await user.type(screen.getByLabelText("行为说明"), "尚未保存的原助手说明");
  state.switchElsewhere();
  await user.click(screen.getByRole("button", { name: "重新读取助手与技能" }));
  await screen.findByText(/当前助手已在别处切换/);
  expect(screen.getByLabelText("行为说明")).toHaveValue("尚未保存的原助手说明");
  expect(screen.getByRole("button", { name: "保存助手配置" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "取消编辑" }));
  expect(screen.getByLabelText("行为说明")).toHaveValue("不同的说明");
  expect(state.profiles[0]!.instructions).toBe("先列计划");
});

test("switching assistants isolates new drafts and requests scoped history", async () => {
  mount();
  const user = userEvent.setup();
  await user.click(screen.getByText("助手与技能"));
  const select = await screen.findByLabelText("当前助手");
  await waitFor(() => expect(select).toHaveValue(firstId));
  await user.type(screen.getByLabelText("向项目知识提问"), "只属于第一个助手");
  await user.click(screen.getByRole("button", { name: "新建助手" }));
  await waitFor(() => expect(select).toHaveValue(secondId));
  expect(screen.getByLabelText("向项目知识提问")).toHaveValue("");
  await user.type(screen.getByLabelText("向项目知识提问"), "只属于第二个助手");
  await user.selectOptions(select, firstId);
  await waitFor(() => expect(screen.getByLabelText("向项目知识提问")).toHaveValue("只属于第一个助手"));
  const requests = vi.mocked(fetch).mock.calls.map(([input]) => input as Request).filter(request => new URL(request.url).pathname.endsWith("/conversations"));
  expect(requests.length).toBeGreaterThan(0);
  expect(requests.every(request => new URL(request.url).searchParams.get("currentAssistant") === "true")).toBe(true);
});

test("custom avatar and name are saved per assistant, previewed, and removable", async () => {
  const state = mount();
  const avatar = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB";
  const bitmap = { width: 200, height: 100, close: vi.fn() };
  vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue(bitmap));
  const drawImage = vi.fn();
  const context = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D);
  const encode = vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue(avatar);
  try {
    const user = userEvent.setup();
    await user.click(screen.getByText("助手与技能"));
    await waitFor(() => expect(screen.getByLabelText("当前助手")).toHaveValue(firstId));
    await user.upload(screen.getByLabelText("上传助手头像"), new File(["synthetic image"], "avatar.png", { type: "image/png" }));
    await screen.findByRole("button", { name: "移除头像" });
    await user.clear(screen.getByLabelText("助手名称"));
    await user.type(screen.getByLabelText("助手名称"), "我的计划员");
    await user.click(screen.getByRole("button", { name: "保存助手配置" }));
    await screen.findByText("助手配置已保存。");
    expect(state.profiles[0]!.avatarDataUrl).toBe(avatar);
    expect(state.profiles[0]!.name).toBe("我的计划员");
    expect(screen.getAllByRole("img", { name: "我的计划员的头像" }).length).toBeGreaterThan(0);
    expect(drawImage).toHaveBeenCalledWith(bitmap, 50, 0, 100, 100, 0, 0, 128, 128);
    expect(bitmap.close).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "新建助手" }));
    await waitFor(() => expect(screen.getByLabelText("当前助手")).toHaveValue(secondId));
    expect(screen.queryByRole("button", { name: "移除头像" })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("当前助手"), firstId);
    await screen.findByRole("button", { name: "移除头像" });
    await user.click(screen.getByRole("button", { name: "移除头像" }));
    await user.click(screen.getByRole("button", { name: "保存助手配置" }));
    await waitFor(() => expect(state.profiles[0]!.avatarDataUrl).toBeNull());
  } finally { context.mockRestore(); encode.mockRestore(); }
});
