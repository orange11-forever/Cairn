import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectConversationsProvider } from "../../src/components/knowledge/ProjectConversationsContext.tsx";
import { KnowledgeConversations } from "../../src/components/knowledge/KnowledgeConversations.tsx";

const pid = "00000000-0000-4000-8000-000000000010";
const models = [
  { id: "fast", name: "快速模型", model: "synthetic-fast", protocol: "openai-compatible" },
  { id: "reasoning", name: "推理模型", model: "synthetic-reasoner", protocol: "openai-responses" },
];
afterEach(() => vi.unstubAllGlobals());

function mount(initialModel: string | null = null, defaultModelId = "fast") {
  let config = { name: "岑宁", instructions: "", enabledSkillIds: [], revision: 0, modelId: initialModel };
  const saves: unknown[] = [];
  const submitted: string[] = [];
  const stamp = "2026-10-14T11:00:00Z";
  let conversation: unknown = null;
  const defaultModel = models.find(item => item.id === defaultModelId)!;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request, path = new URL(request.url).pathname;
    if (path.endsWith("/answer-model")) return Response.json({ configured: true, model: defaultModel.model, protocol: defaultModel.protocol, defaultModelId, models });
    if (path.endsWith("/assistant-settings")) {
      if (request.method === "PUT") {
        const { expectedRevision, ...body } = await request.json();
        saves.push(body); config = { ...body, revision: expectedRevision + 1 };
      }
      return Response.json(config);
    }
    if (path.endsWith("/assistants")) return Response.json({ items: [] });
    if (path.endsWith("/skills")) return Response.json({ items: [] });
    if (path.endsWith("/conversations") && request.method === "GET") return Response.json({ items: [], nextCursor: null });
    if (path.endsWith("/conversations")) {
      const body = await request.json();
      conversation = { id: body.id, title: "新对话", revision: 1, createdAt: stamp, updatedAt: stamp, turns: [] };
      return Response.json(conversation, { status: 201 });
    }
    if (path.endsWith("/turns") || path.endsWith("/turns/stream")) {
      submitted.push(path);
      const body = await request.json(), id = path.split("/conversations/")[1]!.split("/")[0]!;
      conversation = { id, title: body.question, revision: 2, createdAt: stamp, updatedAt: stamp, turns: [{ id: body.id, sequence: 1, question: body.question, assistantName: config.name, assistantRevision: body.assistantRevision, skillId: null, model: models.find(item => item.id === (config.modelId ?? defaultModelId)), answer: { status: "insufficient_evidence", retrievalMode: "hybrid", paragraphs: [], citations: [] }, answerUnavailable: false, contextTruncated: false, createdAt: stamp }] };
      return path.endsWith("/stream") ? new Response(`data: ${JSON.stringify({ type: "complete", conversationId: id, turnId: body.id, conversation })}\n\n`, { headers: { "Content-Type": "text/event-stream" } }) : Response.json(conversation);
    }
    if (conversation !== null) return Response.json(conversation);
    throw new Error(`Unexpected request ${request.method} ${path}`);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><MemoryRouter><ProjectConversationsProvider organizationId="org" userId="user" projectId={pid} generation={1} csrfToken="csrf" sessionSignal={new AbortController().signal}><KnowledgeConversations organizationId="org" projectId={pid} sessionSignal={new AbortController().signal} onAccessUnavailable={vi.fn()} /></ProjectConversationsProvider></MemoryRouter></QueryClientProvider>);
  return { saves, submitted, ...view };
}

test("model choice stays a draft until saved and updates the active answer model", async () => {
  const { saves } = mount();
  const user = userEvent.setup();
  await user.click(screen.getByText("助手与技能"));
  const choice = await screen.findByLabelText("回答模型");
  await user.selectOptions(choice, "reasoning");
  expect(saves).toHaveLength(0);
  expect(screen.getByRole("status", { name: "当前回答模型" })).toHaveTextContent("快速模型");
  await user.click(screen.getByRole("button", { name: "保存助手配置" }));
  await screen.findByText("助手配置已保存。");
  expect(saves).toHaveLength(1);
  expect(saves[0]).toMatchObject({ modelId: "reasoning" });
  expect(screen.getByRole("status", { name: "当前回答模型" })).toHaveTextContent("推理模型");
  expect(choice).toHaveValue("reasoning");
});

test.each([
  { defaultId: "fast", selectedId: "reasoning", suffix: "/turns/stream" },
  { defaultId: "reasoning", selectedId: "fast", suffix: "/turns" },
])("sending with selected $selectedId uses its protocol instead of default $defaultId", async ({ defaultId, selectedId, suffix }) => {
  const { submitted } = mount(null, defaultId);
  const user = userEvent.setup();
  await user.click(screen.getByText("助手与技能"));
  await user.selectOptions(await screen.findByLabelText("回答模型"), selectedId);
  await user.click(screen.getByRole("button", { name: "保存助手配置" }));
  await screen.findByText("助手配置已保存。");
  await user.type(screen.getByLabelText("向项目知识提问"), "本次应该准备什么");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("现有项目资料不足以回答这个问题");
  expect(submitted).toHaveLength(1);
  expect(submitted[0]).toMatch(new RegExp(`${suffix}$`));
  expect(screen.getByRole("region", { name: "第1轮问答" })).toHaveTextContent(selectedId === "reasoning" ? "推理模型" : "快速模型");
});

test("a removed selection prevents sending until an available model is explicitly saved", async () => {
  mount("removed");
  const user = userEvent.setup();
  await screen.findByText(/所选模型已不可用/);
  expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  await user.click(screen.getByText("助手与技能"));
  expect(await screen.findByLabelText("回答模型")).toHaveValue("removed");
  await user.selectOptions(screen.getByLabelText("回答模型"), "fast");
  expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "保存助手配置" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "生成回答" })).toBeEnabled());
});
