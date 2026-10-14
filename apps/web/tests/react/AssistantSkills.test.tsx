import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectConversationsProvider } from "../../src/components/knowledge/ProjectConversationsContext.tsx";
import { KnowledgeConversations } from "../../src/components/knowledge/KnowledgeConversations.tsx";

const pid = "00000000-0000-4000-8000-000000000010", stamp = "2026-10-12T12:00:00Z";
afterEach(() => { vi.unstubAllGlobals(); });
test("saved assistant and enabled skill affect the explicitly submitted turn", async () => {
  let config = { name: "岑宁", instructions: "", enabledSkillIds: [] as string[], revision: 0 };
  const turns: unknown[] = [];
  let conversation: unknown = null;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request, path = new URL(request.url).pathname;
    if (path.endsWith("/answer-model")) return Response.json({ configured: true, model: "gpt-test", protocol: "openai-compatible", defaultModelId: "default", models: [{ id: "default", name: "gpt-test", model: "gpt-test", protocol: "openai-compatible" }] });
    if (path.endsWith("/assistant-settings")) {
      if (request.method === "PUT") { const body = await request.clone().json(); config = { name: body.name, instructions: body.instructions, enabledSkillIds: body.enabledSkillIds, revision: body.expectedRevision + 1 }; }
      return Response.json(config);
    }
    if (path.endsWith("/assistants")) return Response.json({ items: [] });
    if (path.endsWith("/skills")) return Response.json({ items: [{ id: "knowledge-summary", name: "资料摘要", description: "概括事实", defaultQuestion: "请总结当前项目资料", version: "v1", capabilities: ["knowledge.read"], sourceType: "builtin", runnable: true, warnings: [] }] });
    if (path.endsWith("/conversations") && request.method === "GET") return Response.json({ items: [], nextCursor: null });
    const body = request.method === "POST" ? await request.clone().json() : null;
    if (path.endsWith("/conversations")) { conversation = { id: body.id, title: "新对话", revision: 1, createdAt: stamp, updatedAt: stamp, turns: [] }; return Response.json(conversation, { status: 201 }); }
    if (path.endsWith("/turns")) { turns.push(body); conversation = { id: path.split("/").at(-2), title: body.question, revision: 2, createdAt: stamp, updatedAt: stamp, turns: [{ id: body.id, sequence: 1, question: body.question, assistantName: config.name, assistantRevision: body.assistantRevision, skillId: body.skillId, answer: { status: "insufficient_evidence", retrievalMode: "hybrid", paragraphs: [], citations: [] }, answerUnavailable: false, contextTruncated: false, createdAt: stamp }] }; return Response.json(conversation); }
    if (conversation !== null) return Response.json(conversation);
    return Response.json({ code: "not_found", message: "未找到", traceId: "test" }, { status: 404 });
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[`/projects/${pid}/knowledge`]}><ProjectConversationsProvider organizationId="org" userId="user" projectId={pid} generation={1} csrfToken="csrf" sessionSignal={new AbortController().signal}><KnowledgeConversations organizationId="org" projectId={pid} sessionSignal={new AbortController().signal} onAccessUnavailable={vi.fn()} /></ProjectConversationsProvider></MemoryRouter></QueryClientProvider>);
  const user = userEvent.setup();
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  await user.click(screen.getByText("助手与技能"));
  const name = await screen.findByLabelText("助手名称"); await user.clear(name); await user.type(name, "合成助手");
  await user.click(screen.getByLabelText("启用：资料摘要"));
  await user.click(screen.getByRole("button", { name: "保存助手配置" }));
  await screen.findByText("助手配置已保存。");
  await user.selectOptions(screen.getByLabelText("使用技能"), "knowledge-summary");
  expect(screen.getByLabelText("向项目知识提问")).toHaveValue("请总结当前项目资料");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("现有项目资料不足以回答这个问题");
  expect(turns).toHaveLength(1); expect(turns[0]).toMatchObject({ assistantRevision: 1, skillId: "knowledge-summary" });
});

test("GitHub preview and failed import recover the same UUID without enabling", async () => {
  const preview = { name: "导入技能", description: "合成描述", defaultQuestion: "总结项目", version: "v1", capabilities: ["knowledge.read"], sourceType: "github", sourceMetadata: { path: "SKILL.md" }, runnable: true, warnings: [], body: "只读指导", resources: [], digest: "a".repeat(64) };
  const imports: { id: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request, path = new URL(request.url).pathname;
    if (path.endsWith("/answer-model")) return Response.json({ configured: true, model: "gpt-test", protocol: "openai-responses", defaultModelId: "default", models: [{ id: "default", name: "gpt-test", model: "gpt-test", protocol: "openai-responses" }] });
    if (path.endsWith("/assistant-settings")) return Response.json({ name: "岑宁", instructions: "", enabledSkillIds: [], revision: 0 });
    if (path.endsWith("/assistants")) return Response.json({ items: [] });
    if (path.endsWith("/skills")) return Response.json({ items: [] });
    if (path.endsWith("/conversations")) return Response.json({ items: [], nextCursor: null });
    if (path.endsWith("/preview")) return Response.json(preview);
    if (path.endsWith("/import")) { const body = await request.clone().json(); imports.push(body); if (imports.length === 1) throw new TypeError("response lost"); return Response.json({ ...preview, id: body.id }, { status: 200 }); }
    throw new Error("Unexpected route");
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><ProjectConversationsProvider organizationId="org" userId="user" projectId={pid} generation={1} csrfToken="csrf" sessionSignal={new AbortController().signal}><KnowledgeConversations organizationId="org" projectId={pid} sessionSignal={new AbortController().signal} onAccessUnavailable={vi.fn()} /></ProjectConversationsProvider></MemoryRouter></QueryClientProvider>);
  const user = userEvent.setup(); await screen.findByText("gpt-test", { selector: ".conversation-model-status span" }); await user.click(screen.getByText("助手与技能"));
  await user.selectOptions(screen.getByLabelText("导入来源"), "github"); await user.type(screen.getByLabelText("GitHub 地址"), "https://github.com/example/public");
  await user.click(screen.getByRole("button", { name: "预览技能" })); await screen.findByRole("region", { name: "技能导入预览" }); expect(imports).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "确认导入技能" })); await screen.findByRole("button", { name: "重新确认导入结果（同一请求）" });
  await user.click(screen.getByRole("button", { name: "重新确认导入结果（同一请求）" })); await screen.findByText("技能已导入，尚未启用。请勾选并保存助手配置。");
  expect(imports).toHaveLength(2); expect(imports[0]!.id).toBe(imports[1]!.id); expect(screen.getByLabelText("使用技能")).toHaveValue("");
});

test("pending assistant save locks edit and cancel controls until its response", async () => {
  let finish!: (response: Response) => void;
  const config = { name: "岑宁", instructions: "", enabledSkillIds: [], revision: 0 };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request, path = new URL(request.url).pathname;
    if (path.endsWith("/assistant-settings")) return request.method === "PUT" ? new Promise<Response>(resolve => { finish = resolve; }) : Response.json(config);
    if (path.endsWith("/assistants")) return Response.json({ items: [] });
    if (path.endsWith("/skills")) return Response.json({ items: [] });
    if (path.endsWith("/answer-model")) return Response.json({ configured: false, model: null, protocol: null, defaultModelId: null, models: [] });
    return Response.json({ items: [], nextCursor: null });
  }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><ProjectConversationsProvider organizationId="org" userId="user" projectId={pid} generation={1} csrfToken="csrf" sessionSignal={new AbortController().signal}><KnowledgeConversations organizationId="org" projectId={pid} sessionSignal={new AbortController().signal} onAccessUnavailable={vi.fn()} /></ProjectConversationsProvider></MemoryRouter></QueryClientProvider>);
  const user = userEvent.setup(); await user.click(screen.getByText("助手与技能"));
  const name = await screen.findByLabelText("助手名称"); await user.clear(name); await user.type(name, "保存中的名称");
  await user.click(screen.getByRole("button", { name: "保存助手配置" }));
  expect(name).toBeDisabled(); expect(screen.getByRole("button", { name: "取消编辑" })).toBeDisabled();
  finish(Response.json({ ...config, name: "保存中的名称", revision: 1 }));
  await screen.findByText("助手配置已保存。"); expect(name).toHaveValue("保存中的名称");
});
