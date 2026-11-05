import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectCommandPanel } from "../../src/components/projects/ProjectCommandPanel.tsx";
import { projectKeys, taskKeys } from "../../src/queries/projects.ts";
import { SessionProvider } from "../../src/session/SessionContext.tsx";

const id = "00000000-0000-4000-8000-000000004001";
const now = "2026-11-04T11:00:00Z";
const identity = { user: { id: "user", email: "user@example.com", displayName: "用户" }, organization: { id: "00000000-0000-4000-8000-000000002001", name: "组织", slug: "org" }, membership: { id: "member", role: "owner" as const }, csrfToken: "csrf" };
const project = { id, name: "交付项目", description: null, revision: 1, createdAt: now, updatedAt: now };
const preview = { projectId: id, intent: "创建发布验收任务", generatedAt: now, assistantName: "岑宁", model: { id: "default", name: "测试模型", model: "synthetic", protocol: "openai-compatible" }, canExecute: true,
  snapshot: { project, tasks: [], stages: [], milestones: [], dependencies: [] },
  suggestion: { status: "proposed", explanation: "先核对任务再创建。", action: { type: "create_task", title: "发布验收", description: null, priority: "high", acceptanceCriteria: null, stageId: null, milestoneId: null } } };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); });

function mount(projectId: string | null = id, viewer = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(projectKeys.detail(identity.organization.id, id), project);
  client.setQueryData(taskKeys.list(identity.organization.id, id), { pages: [{ items: [], nextCursor: null }], pageParams: [null] });
  const wrap = (target: string | null) => <MemoryRouter><QueryClientProvider client={client}><SessionProvider restoredIdentity={{ ...identity, membership: { ...identity.membership, role: viewer ? "viewer" : "owner" } }}><ProjectCommandPanel projectId={target} /></SessionProvider></QueryClientProvider></MemoryRouter>;
  const view = render(wrap(projectId));
  return { client, switchProject: (target: string) => view.rerender(wrap(target)) };
}

test("the central command uses the current project, previews first, then invalidates its tasks", async () => {
  const writes: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    expect(request.url).toContain(`/projects/${id}/`);
    expect(request.headers.get("X-CSRF-Token")).toBe("csrf");
    if (request.url.endsWith("operation-preview")) return json(preview);
    const body = await request.json(); writes.push(body);
    return json({ operationId: body.operationId, projectId: id, intent: preview.intent, action: preview.suggestion.action, explanation: preview.suggestion.explanation, generatedAt: now, appliedAt: now, result: { id: "task", title: "发布验收" } }, 201);
  }));
  const { client } = mount();
  fireEvent.change(screen.getByLabelText("你要执行的操作"), { target: { value: preview.intent } });
  fireEvent.click(screen.getByRole("button", { name: "生成待确认操作" }));
  await screen.findByRole("group", { name: "确认助手操作" });
  expect(writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "确认执行此操作" }));
  await screen.findByText("操作已执行，真实项目内容已更新。");
  expect(writes).toHaveLength(1);
  expect(client.getQueryState(taskKeys.list(identity.organization.id, id))?.isInvalidated).toBe(true);
  expect(screen.getByRole("link", { name: "查看项目任务" })).toHaveAttribute("href", `/projects/${id}/tasks`);
});

test("switching projects cancels an outstanding command and discards its suggestion", async () => {
  let finish!: (value: Response) => void;
  let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn((request: Request) => { signal = request.signal; return new Promise<Response>(resolve => { finish = resolve; }); }));
  const view = mount();
  fireEvent.change(screen.getByLabelText("你要执行的操作"), { target: { value: preview.intent } });
  fireEvent.click(screen.getByRole("button", { name: "生成待确认操作" }));
  await waitFor(() => expect(signal).toBeDefined());
  view.switchProject("00000000-0000-4000-8000-000000004002");
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(json(preview)));
  expect(screen.queryByRole("group", { name: "确认助手操作" })).toBeNull();
  expect(screen.getByLabelText("你要执行的操作")).toHaveValue("");
});

test("without a project the panel offers creation only to a writable member", () => {
  mount(null, true);
  expect(screen.getByText(/选择一个项目/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "新建项目" })).toBeNull();
  expect(screen.queryByLabelText("你要执行的操作")).toBeNull();
});

test("a natural language project creation works without selecting a project and confirms only once", async () => {
  const writes: Record<string, unknown>[] = [];
  const organizationId = "00000000-0000-4000-8000-000000002001";
  const suggestion = { organizationId, intent: "创建发布工作区", generatedAt: now, model: preview.model,
    suggestion: { status: "proposed", explanation: "创建用于发布验收的项目", action: { type: "create_project", name: "发布工作区", description: "发布验收" } } };
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    if (request.url.endsWith("/project-creations/preview")) return json(suggestion);
    expect(request.url).toMatch(/\/project-creations$/);
    const body = await request.json(); writes.push(body);
    return json({ operationId: body.operationId, projectId: id, intent: suggestion.intent,
      action: suggestion.suggestion.action, explanation: suggestion.suggestion.explanation,
      generatedAt: now, appliedAt: now, result: { ...project, name: "发布工作区" } }, 201);
  }));
  mount(null);
  fireEvent.change(screen.getByLabelText("描述要创建的项目"), { target: { value: suggestion.intent } });
  fireEvent.click(screen.getByRole("button", { name: "生成项目预览" }));
  await screen.findByRole("group", { name: "确认创建项目" });
  expect(writes).toHaveLength(0);
  const confirm = screen.getByRole("button", { name: "确认创建项目" });
  fireEvent.click(confirm); fireEvent.click(confirm);
  const link = await screen.findByRole("link", { name: "打开新项目" });
  expect(link).toHaveAttribute("href", `/projects/${id}/tasks`);
  expect(writes).toHaveLength(1);
});

test("a coding suggestion offers a handoff with the selected task and never writes a member assignment", async () => {
  const tid = "00000000-0000-4000-8000-000000005001";
  const action = { type: "dispatch_task", taskId: tid, assistantId: null, assistantName: "岑宁" };
  const task = { id: tid, projectId: id, title: "修复加法", description: "修复边界条件", acceptanceCriteria: "通过测试", status: "todo", priority: "high", revision: 3, createdAt: now, updatedAt: now,
    stageId: null, milestoneId: null, parentTaskId: null, assigneeUserId: null, dueAt: null, estimatedEffortMinutes: null, remainingEffortMinutes: null };
  const fetch = vi.fn(async () => json({ ...preview, snapshot: { ...preview.snapshot, tasks: [task] },
    suggestion: { status: "proposed", explanation: "准备交给岑宁执行", action } }));
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.change(screen.getByLabelText("你要执行的操作"), { target: { value: preview.intent } });
  fireEvent.click(screen.getByRole("button", { name: "生成待确认操作" }));
  const link = await screen.findByRole("link", { name: "前往代码工作区确认派发" });
  expect(link).toHaveAttribute("href", `/projects/${id}/code`);
  expect(screen.queryByRole("button", { name: "确认执行此操作" })).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("an ambiguous creation blocks new writes until its saved result is recovered", async () => {
  let operationId = "";
  let writes = 0;
  const suggestion = { organizationId: identity.organization.id, intent: "创建发布工作区", generatedAt: now, model: preview.model,
    suggestion: { status: "proposed", explanation: "创建项目", action: { type: "create_project", name: "发布工作区", description: null } } };
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    if (request.url.endsWith("/preview")) return json(suggestion);
    if (request.method === "POST") {
      operationId = (await request.json()).operationId; writes += 1;
      throw new TypeError("Connection lost after commit");
    }
    expect(request.url).toContain(operationId);
    return json({ operationId, projectId: id, intent: suggestion.intent, action: suggestion.suggestion.action,
      explanation: "创建项目", generatedAt: now, appliedAt: now, result: { ...project, name: "发布工作区" } });
  }));
  mount();
  fireEvent.click(screen.getByRole("tab", { name: "创建项目" }));
  fireEvent.change(screen.getByLabelText("描述要创建的项目"), { target: { value: suggestion.intent } });
  fireEvent.click(screen.getByRole("button", { name: "生成项目预览" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认创建项目" }));
  await screen.findByText(/创建结果尚未确认/);
  expect(screen.getByRole("tab", { name: "项目操作" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "生成项目预览" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "查询创建结果" }));
  await screen.findByRole("link", { name: "打开新项目" });
  expect(writes).toBe(1);
  await waitFor(() => expect(screen.getByRole("tab", { name: "项目操作" })).toBeEnabled());
});

test("the planning view exposes the existing preview flow without starting it automatically", () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(screen.getByRole("tab", { name: "拆分任务" }));
  expect(screen.getByRole("button", { name: "生成规划预览" })).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

test("an uncertain operation keeps the planning tab locked until its result is reconciled", () => {
  sessionStorage.setItem(`cairn.pending-operation:user:${id}`, "00000000-0000-4000-8000-000000006001");
  mount();
  expect(screen.getByRole("tab", { name: "拆分任务" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "查询操作结果" })).toBeEnabled();
});

test("an uncertain plan keeps the operation tab locked", () => {
  sessionStorage.setItem(`cairn.pending-plan:user:${id}`, "00000000-0000-4000-8000-000000006001");
  mount();
  fireEvent.click(screen.getByRole("tab", { name: "拆分任务" }));
  expect(screen.getByRole("tab", { name: "项目操作" })).toBeDisabled();
  expect(screen.getByText(/上次提交结果尚未确认/)).toBeInTheDocument();
});
