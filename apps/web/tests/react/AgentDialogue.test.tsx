import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { AgentDialoguePage } from "../../src/pages/AgentDialoguePage.tsx";

const pid = "00000000-0000-4000-8000-000000004001", other = "00000000-0000-4000-8000-000000004002";
const aid = "00000000-0000-4000-8000-000000005001", second = "00000000-0000-4000-8000-000000005002";
const owner = "00000000-0000-4000-8000-000000006001", org = "00000000-0000-4000-8000-000000007001";
const now = "2026-11-07T00:00:00Z";
const model = {id: "default", name: "测试模型", model: "synthetic", protocol: "openai-compatible"};
const source = {originProjectId: pid, assistantId: aid};
const settings = {id: aid, name: "项目管家", instructions: "先说明", enabledSkillIds: [], revision: 1, modelId: null, avatarDataUrl: null};
const project = (id: string) => ({id, name: id === pid ? "原项目" : "新项目", description: null, revision: 1, createdAt: now, updatedAt: now});
let session: {session: {generation: number; identity: {user: {id: string}; organization: {id: string}; csrfToken: string}; signal: AbortSignal}};
vi.mock("../../src/session/SessionContext.tsx", () => ({useSession: () => session, useSessionErrorReporter: () => vi.fn()}));
const reply = (value: unknown, status = 200) => Response.json(value, {status});
function preview(target: string, intent: string, creation = false) {
  const common = {intent, generatedAt: now, model, suggestion: {status: "proposed", explanation: creation ? "创建新项目" : "创建任务", action: creation ? {type: "create_project", name: "新项目", description: null} : {type: "create_task", title: "发布验收", priority: "high", description: null, acceptanceCriteria: null, stageId: null, milestoneId: null}}};
  return {agent: source, targetProjectId: target, assistant: settings, preview: creation ? {organizationId: org, ...common} : {projectId: target, assistantName: settings.name, canExecute: true, snapshot: {project: project(target), stages: [], milestones: [], tasks: [], dependencies: []}, ...common}};
}
function Navigation() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate(`/projects/${pid}/agents/${second}/dialogue`)}>换 Agent</button><button onClick={() => navigate(`/projects/${pid}/agents/${aid}/dialogue?target=${other}`)}>换目标</button></>;
}
function mount(handler?: (request: Request) => Promise<Response | undefined>, initial = `/projects/${pid}/agents/${aid}/dialogue`) {
  session = {session: {generation: 1, identity: {user: {id: owner}, organization: {id: org}, csrfToken: "csrf"}, signal: new AbortController().signal}};
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    requests.push(request.clone());
    const custom = await handler?.(request); if (custom) return custom;
    const path = new URL(request.url).pathname;
    if (path.endsWith("/assistants")) return reply({items: [{id: aid, name: "项目管家", modelId: null, avatarDataUrl: null}, {id: second, name: "另一个 Agent", modelId: null, avatarDataUrl: null}]});
    if (path.endsWith("/answer-model")) return reply({configured: true, model: "synthetic", protocol: "openai-compatible", defaultModelId: "default", models: [model]});
    if (path.endsWith("/projects")) return reply({items: [project(pid), project(other)], nextCursor: null});
    if (path.endsWith(`/projects/${pid}`)) return reply(project(pid));
    if (path.endsWith(`/projects/${other}`)) return reply(project(other));
    throw new Error(`Unexpected ${request.method} ${path}`);
  }));
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  const content = () => <QueryClientProvider client={client}><MemoryRouter initialEntries={[initial]}><Navigation/><Routes><Route path="/projects/:projectId/agents/:assistantId/dialogue" element={<AgentDialoguePage/>}/></Routes></MemoryRouter></QueryClientProvider>;
  return {requests, client, ...render(content()), content};
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); });
async function send(text = "创建一个新项目") {
  await screen.findByLabelText("给这个 Agent 发消息");
  fireEvent.change(screen.getByLabelText("给这个 Agent 发消息"), {target: {value: text}});
  fireEvent.click(screen.getByRole("button", {name: "发送"}));
  await screen.findByRole("region", {name: "确认智能体操作"});
}

test("a named Agent previews writes and stays pinned after creating its working project", async () => {
  const writes: Record<string, any>[] = [], previews: Record<string, any>[] = [];
  const app = mount(async request => {
    if (request.url.endsWith("/agent-dialogue/preview")) { const body = await request.json(); previews.push(body); return reply(preview(body.targetProjectId, body.intent, previews.length === 1)); }
    if (request.url.endsWith("/agent-dialogue/operations") && request.method === "POST") {
      const body = await request.json(); writes.push(body); const operation = body.preview.preview;
      return reply({operationId: body.operationId, projectId: other, intent: operation.intent, action: operation.suggestion.action, explanation: operation.suggestion.explanation, generatedAt: now, appliedAt: now, result: {id: other, name: "新项目"}}, 201);
    }
  });
  expect(await screen.findByRole("heading", {name: "与项目管家对话"})).toBeVisible();
  expect(screen.getByText("测试模型 · 项目管理 Agent")).toBeVisible();
  await send(); expect(writes).toHaveLength(0); expect(previews[0]!.agent).toEqual(source);
  fireEvent.click(screen.getByRole("button", {name: "确认执行此操作"}));
  await waitFor(() => expect(screen.getByLabelText("当前工作项目")).toHaveValue(other));
  expect(screen.getByRole("heading", {name: "与项目管家对话"})).toBeVisible();
  expect(screen.getByText("项目已创建。我们继续在这个项目里管理任务。")).toBeVisible();
  await send("创建发布验收任务");
  expect(writes).toHaveLength(1); expect(previews[1]).toMatchObject({agent: source, targetProjectId: other});
  expect(writes[0]).toMatchObject({confirmed: true, preview: {agent: source, targetProjectId: pid}});
  app.client.clear();
});

test("an unknown creation result is recovered once by its Agent-scoped operation identifier", async () => {
  let payload: Record<string, any> | undefined, writes = 0;
  const app = mount(async request => {
    if (request.url.endsWith("/preview")) {const body = await request.json(); return reply(preview(pid, body.intent, true));}
    if (request.url.endsWith("/operations") && request.method === "POST") {writes++; payload = await request.json(); throw new TypeError("lost response");}
    if (request.url.includes("/operations/") && request.method === "GET") {
      expect(new URL(request.url).searchParams.get("assistant_id")).toBe(aid);
      expect(request.url).toContain(payload!.operationId);
      return reply({operationId: payload!.operationId, projectId: other, intent: payload!.preview.preview.intent, action: {type: "create_project", name: "新项目", description: null}, explanation: "创建新项目", generatedAt: now, appliedAt: now, result: {id: other}});
    }
  });
  await send(); fireEvent.click(screen.getByRole("button", {name: "确认执行此操作"}));
  await screen.findByText(/提交结果尚未确认/); expect(screen.getByRole("button", {name: "发送"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "查询操作结果"}));
  await waitFor(() => expect(screen.getByLabelText("当前工作项目")).toHaveValue(other));
  expect(writes).toBe(1); expect(sessionStorage.length).toBe(0); app.client.clear();
});

test("route and account changes discard drafts, proposals and foreign pending operation identifiers", async () => {
  const key = `cairn.pending-agent-operation:${org}:${owner}:${pid}:${aid}:${pid}`;
  sessionStorage.setItem(key, "00000000-0000-4000-8000-000000009001");
  const app = mount();
  await screen.findByLabelText("给这个 Agent 发消息");
  expect(screen.getByRole("button", {name: "发送"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "换 Agent"}));
  await screen.findByRole("heading", {name: "与另一个 Agent对话"});
  expect(screen.queryByRole("button", {name: "查询操作结果"})).toBeNull();
  fireEvent.change(screen.getByLabelText("给这个 Agent 发消息"), {target: {value: "此 Agent 的草稿"}});
  fireEvent.click(screen.getByRole("button", {name: "换目标"}));
  await screen.findByRole("heading", {name: "与项目管家对话"});
  expect(screen.getByLabelText("给这个 Agent 发消息")).toHaveValue("");
  expect(screen.queryByRole("button", {name: "查询操作结果"})).toBeNull();
  fireEvent.change(screen.getByLabelText("给这个 Agent 发消息"), {target: {value: "原账号草稿"}});
  session = {session: {...session.session, generation: 2, identity: {...session.session.identity, user: {id: "another-account"}}}};
  app.rerender(app.content());
  await waitFor(() => expect(screen.getByLabelText("给这个 Agent 发消息")).toHaveValue(""));
  expect(screen.queryByRole("button", {name: "查询操作结果"})).toBeNull();
  app.client.clear();
});

test("a late proposal never appears in another Agent dialogue", async () => {
  let finish!: (response: Response) => void;
  let requestSignal: AbortSignal | undefined;
  const app = mount(async request => {
    if (request.url.endsWith("/preview")) {requestSignal = request.signal; return new Promise(resolve => {finish = resolve;});}
  });
  await screen.findByLabelText("给这个 Agent 发消息");
  fireEvent.change(screen.getByLabelText("给这个 Agent 发消息"), {target: {value: "创建任务"}});
  fireEvent.click(screen.getByRole("button", {name: "发送"}));
  await waitFor(() => expect(requestSignal).toBeDefined());
  fireEvent.click(screen.getByRole("button", {name: "换 Agent"}));
  await screen.findByRole("heading", {name: "与另一个 Agent对话"});
  expect(requestSignal?.aborted).toBe(true);
  await act(async () => finish(reply(preview(pid, "创建任务"))));
  expect(screen.queryByRole("region", {name: "确认智能体操作"})).toBeNull();
  expect(screen.queryByText("创建任务")).toBeNull(); app.client.clear();
});
