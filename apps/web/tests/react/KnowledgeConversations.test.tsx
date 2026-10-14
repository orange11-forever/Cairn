import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectConversationsProvider } from "../../src/components/knowledge/ProjectConversationsContext.tsx";
import { KnowledgeConversations } from "../../src/components/knowledge/KnowledgeConversations.tsx";
import type { KnowledgeConversation } from "../../src/api/knowledgeConversations.ts";
import { SessionProvider, useSession } from "../../src/session/SessionContext.tsx";
import type { IdentityContext } from "../../src/api/auth.ts";
import { PrimaryNavigation } from "../../src/components/PrimaryNavigation.tsx";

const pid = "00000000-0000-4000-8000-000000000010";
const cid = "00000000-0000-4000-8000-000000000011";
const stamp = "2026-10-12T12:00:00Z";
const empty = (id = cid): KnowledgeConversation => ({ id, title: "新对话", revision: 1, createdAt: stamp, updatedAt: stamp, turns: [] });
function Location() { return <output aria-label="当前地址">{useLocation().search}</output>; }
function mount(entry = `/projects/${pid}/knowledge`, props: { sessionSignal?: AbortSignal; generation?: number } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const citation = vi.fn();
  const rendered = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><ProjectConversationsProvider organizationId="org" userId="user" projectId={pid} generation={props.generation ?? 1} csrfToken="csrf" sessionSignal={props.sessionSignal ?? new AbortController().signal}><KnowledgeConversations organizationId="org" projectId={pid} sessionSignal={props.sessionSignal ?? new AbortController().signal} onAccessUnavailable={vi.fn()} onOpenCitation={citation} projectName="合成项目" /><Location /></ProjectConversationsProvider></MemoryRouter></QueryClientProvider>);
  return { ...rendered, client, citation, user: userEvent.setup() };
}
function server(initial = empty(), failAppend = false, failReread = false, streaming?: { wait: Promise<void> }) {
  let detail = initial;
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const path = new URL(request.url).pathname;
    if (path.endsWith("/assistant-settings")) return Response.json({name:"岑宁",instructions:"",enabledSkillIds:[],revision:0});
    if (path.endsWith("/assistants")) return Response.json({ items: [] });
    if (path.endsWith("/skills")) return Response.json({items:[]});
    if (path.endsWith("/answer-model")) return Response.json({ configured: true, model: "gpt-test", protocol: streaming === undefined ? "openai-compatible" : "openai-responses", defaultModelId: "default", models: [{ id: "default", name: "gpt-test", model: "gpt-test", protocol: streaming === undefined ? "openai-compatible" : "openai-responses" }] });
    if (path.endsWith("/conversations") && request.method === "GET") { const { turns: _turns, ...summary } = detail; return Response.json({ items: [summary], nextCursor: null }); }
    if (path.endsWith("/conversations") && request.method === "POST") { detail = empty((await request.clone().json()).id); return Response.json(detail, { status: 201 }); }
    if (path.endsWith("/turns") || path.endsWith("/turns/stream")) {
      const body = await request.clone().json();
      const n = detail.turns.length + 1;
      detail = { ...detail, title: body.question, revision: n + 1, turns: [...detail.turns, { id: body.id, sequence: n, question: body.question, assistantName: "岑宁", assistantRevision: 0, skillId: null, createdAt: stamp, answerUnavailable: false, contextTruncated: false, answer: { status: "answered", retrievalMode: "hybrid", paragraphs: [{ text: `第${n}轮合成答案`, citationIds: ["S1"] }], citations: [{ id: "S1", resourceId: pid, resourceVersionId: cid, chunkId: body.id, title: `第${n}轮资料`, excerpt: "合成证据", mediaType: "text/plain", locator: { type: "text", headingPath: [], lineStart: 1, lineEnd: 1 }, score: 0.8 }] } }] };
      if (failAppend) throw new TypeError("response lost after commit");
      if (streaming !== undefined) {
        const response = detail;
        const paragraph = response.turns.at(-1)!.answer!.paragraphs[0]!;
        return new Response(new ReadableStream({ async start(controller) {
          const frame = (value: unknown) => new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`);
          controller.enqueue(frame({ type: "paragraph", conversationId: detail.id, turnId: body.id, index: 0, paragraph }));
          await streaming.wait;
          try { controller.enqueue(frame({ type: "complete", conversationId: response.id, turnId: body.id, conversation: response })); controller.close(); } catch { /* The stopped client has closed its reader. */ }
        } }), { headers: { "Content-Type": "text/event-stream" } });
      }
    }
    if (failReread && requests.some(r => new URL(r.url).pathname.endsWith("/turns"))) throw new TypeError("read failed");
    return Response.json(detail);
  }));
  return { requests, detail: () => detail, replace: (value: KnowledgeConversation) => { detail = value; } };
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("sends two persisted turns, keeps their citations separate, and puts the conversation in the URL", async () => {
  const api = server();
  const { user, citation, unmount } = mount();
  const input = screen.getByLabelText("向项目知识提问");
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  await user.type(input, "第一轮问题"); await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("第1轮合成答案");
  expect(input).toHaveValue("");
  await user.type(input, "第二轮问题"); await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("第2轮合成答案");
  expect(screen.getByText("第1轮合成答案")).toBeInTheDocument();
  const first = screen.getByRole("region", { name: "第1轮问答" });
  await user.click(within(first).getByRole("button", { name: "查看引用上下文" }));
  expect(citation).toHaveBeenCalledWith(expect.objectContaining({ title: "第1轮资料" }));
  expect(screen.getByLabelText("当前地址")).toHaveTextContent(`conversation=${api.detail().id}`);
  const posts = api.requests.filter(r => r.method === "POST");
  expect(posts).toHaveLength(3);
  expect((await posts[2]!.clone().json()).expectedRevision).toBe(2);
  unmount();
  const restored = server(api.detail());
  mount(`/projects/${pid}/knowledge?conversation=${api.detail().id}`);
  await screen.findByText("第2轮合成答案");
  expect(screen.getByText("第1轮合成答案")).toBeInTheDocument();
  expect(restored.requests.some(request => request.method === "POST")).toBe(false);
});

test("a failed reread keeps the recovery token and an edited draft, with sending locked", async () => {
  const api = server(empty(), true, true);
  const { user } = mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  const input = screen.getByLabelText("向项目知识提问");
  await user.type(input, "最初发送的问题"); await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText(/发送结果尚未确认，请重新读取会话/);
  await user.clear(input); await user.type(input, "后来修改的草稿");
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  await screen.findByText("重新读取失败，请保留草稿并再次读取会话。");
  expect(input).toHaveValue("后来修改的草稿");
  expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  expect(api.requests.filter(r => r.method === "POST")).toHaveLength(1);
});

test("successful recovery clears only the unchanged submitted draft", async () => {
  server(empty(), true);
  const { user } = mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  const input = screen.getByLabelText("向项目知识提问");
  await user.type(input, "最初发送的问题"); await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText(/发送结果尚未确认，请重新读取会话/);
  await user.clear(input); await user.type(input, "后来修改的草稿");
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  await screen.findByText("第1轮合成答案");
  expect(input).toHaveValue("后来修改的草稿");
  expect(screen.getByRole("button", { name: "生成回答" })).toBeEnabled();
});

const identity: IdentityContext = { user: { id: "user", email: "test@example.com", displayName: "旧账号" }, organization: { id: "org", slug: "org", name: "测试组织" }, membership: { id: "member", role: "member" }, csrfToken: "csrf" };
function SessionChat() {
  const { session, establishSession } = useSession();
  const navigate = useNavigate();
  if (session === null) return <p>会话已退出</p>;
  return <><p>{session.user.displayName}</p><button onClick={() => { establishSession({ ...identity, user: { ...identity.user, id: "new-user", displayName: "新账号" } }); navigate(`/projects/${pid}/knowledge?conversation=${cid}`); }}>切换账号</button><ProjectConversationsProvider key={session.generation} organizationId="org" userId={session.user.id} projectId={pid} generation={session.generation} csrfToken="csrf" sessionSignal={session.signal}><KnowledgeConversations organizationId="org" projectId={pid} sessionSignal={session.signal} onAccessUnavailable={vi.fn()} /></ProjectConversationsProvider></>;
}
test.each([false, true])("current 401 expires session, late old-generation 401 leaves new session intact (stale=%s)", async stale => {
  server();
  const base = globalThis.fetch;
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new URL((input as Request).url).pathname.endsWith("/turns") ? new Promise<Response>(done => { resolve = done; }) : base(input)));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${pid}/knowledge?conversation=${cid}`]}><SessionProvider restoredIdentity={identity} sessionApi={{ restore: async () => identity, logout: async () => undefined, prepareLogin: async () => undefined }}><SessionChat /></SessionProvider></MemoryRouter></QueryClientProvider>);
  const user = userEvent.setup();
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  await user.type(screen.getByLabelText("向项目知识提问"), "会话边界问题");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  await waitFor(() => expect(resolve).toBeDefined());
  if (stale) { await user.click(screen.getByRole("button", { name: "切换账号" })); await screen.findByText("新账号"); }
  await act(async () => resolve(Response.json({ code: "session_invalid", message: "会话无效", traceId: "session-test" }, { status: 401 })));
  if (stale) { expect(screen.getByText("新账号")).toBeInTheDocument(); expect(screen.queryByText("会话已退出")).toBeNull(); }
  else expect(await screen.findByText("会话已退出")).toBeInTheDocument();
});

test("409 keeps the draft and requires an explicit reread before another send", async () => {
  server(); const base = globalThis.fetch;
  const posts: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (new URL(request.url).pathname.endsWith("/turns")) { posts.push(request); return Response.json({ code: "conversation_conflict", message: "对话已变化", traceId: "conflict" }, { status: 409 }); }
    return base(input);
  }));
  const { user } = mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  const input = screen.getByLabelText("向项目知识提问");
  await user.type(input, "冲突后保留草稿"); await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("对话或资料已变化，请重新读取会话后再发送。");
  expect(input).toHaveValue("冲突后保留草稿"); expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  await screen.findByText("会话已重新读取，这个问题尚未保存，可以再次发送。");
  await waitFor(() => expect(screen.getByRole("button", { name: "生成回答" })).toBeEnabled());
  expect(posts).toHaveLength(1);
});

test("reread redacts stale answers and citations while keeping the owner's question", async () => {
  const api = server(); const { user } = mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  await user.type(screen.getByLabelText("向项目知识提问"), "核验旧引用的问题"); await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("第1轮合成答案");
  api.replace({ ...api.detail(), turns: api.detail().turns.map(turn => ({ ...turn, answer: null, answerUnavailable: true })) });
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  await screen.findByText("引用资料已变化或无法访问，这轮历史回答暂不可用。");
  expect(screen.queryByText("第1轮合成答案")).toBeNull(); expect(screen.queryByText("S1 · 第1轮资料")).toBeNull();
  expect(screen.getByText("核验旧引用的问题", { selector: ".knowledge-question-text" })).toBeInTheDocument();
});

test("missing private conversation stays local and can start a new conversation", async () => {
  server(); const base = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new URL((input as Request).url).pathname.endsWith(`/${cid}`) ? Response.json({ code: "not_found", message: "资源不存在", traceId: "missing" }, { status: 404 }) : base(input)));
  const { user } = mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("对话不存在或不可访问，可以新建对话。");
  await user.click(screen.getByRole("button", { name: "新建对话" }));
  expect(screen.getByText("从一个问题开始")).toBeInTheDocument();
  expect(screen.getByLabelText("当前地址")).not.toHaveTextContent("conversation=");
});

test("search, chat and source navigation preserve the selected conversation", () => {
  render(<MemoryRouter initialEntries={[`/projects/${pid}/knowledge?conversation=${cid}&view=chat`]}><PrimaryNavigation currentKnowledgePath={`/projects/${pid}/knowledge`} /></MemoryRouter>);
  for (const label of ["知识工作台", "搜索项目资料", "来源与同步"]) expect(screen.getByRole("link", { name: label }).getAttribute("href")).toContain(`conversation=${cid}`);
});

test("unconfigured model preserves readable history and shows redaction/context notices", async () => {
  const stored = { ...empty(), revision: 2, turns: [{ id: "00000000-0000-4000-8000-000000000012", sequence: 1, question: "自己的历史问题", assistantName: "岑宁", assistantRevision: 0, skillId: null, answer: null, answerUnavailable: true, contextTruncated: true, createdAt: stamp }] };
  const api = server(stored); const base = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new URL((input as Request).url).pathname.endsWith("/answer-model") ? Response.json({ configured: false, model: null, protocol: null, defaultModelId: null, models: [] }) : base(input)));
  mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("模型尚未配置，历史对话仍可读取。");
  await screen.findByText("自己的历史问题", { selector: ".knowledge-question-text" });
  expect(screen.getByText("这轮只使用了近期有效的历史，部分上下文已省略。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  expect(api.requests.some(request => request.method === "POST")).toBe(false);
});

test("refresh reads the selected URL conversation without posting", async () => {
  const api = server();
  mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("新对话", { selector: "option" });
  await waitFor(() => expect(screen.getByLabelText("选择对话")).toHaveValue(cid));
  expect(api.requests.some(r => r.method === "POST")).toBe(false);
});

test("lost append response requires reread and recovers the saved UUID without resubmitting", async () => {
  const api = server(empty(), true);
  const { user } = mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  const input = screen.getByLabelText("向项目知识提问");
  await user.type(input, "保存后丢响应"); await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByRole("button", { name: "重新读取会话" });
  expect(input).toHaveValue("保存后丢响应");
  expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  await screen.findByText("第1轮合成答案");
  expect(input).toHaveValue("");
  expect(api.requests.filter(r => r.method === "POST")).toHaveLength(1);
});


test.each([false, true])("Responses paragraph is provisional, then completion or stop clears preview (stop=%s)", async stop => {
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  server(empty(), false, false, { wait });
  const { user } = mount(`/projects/${pid}/knowledge?conversation=${cid}`);
  await screen.findByText("gpt-test", { selector: ".conversation-model-status span" });
  const input = screen.getByLabelText("向项目知识提问");
  await user.type(input, "正在生成的问题");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  const preview = await screen.findByRole("region", { name: "正在生成的回答" });
  expect(within(preview).getByText("第1轮合成答案")).toBeInTheDocument();
  expect(within(preview).getByText(/尚未保存/)).toBeInTheDocument();
  expect(within(preview).queryByRole("button", { name: "查看引用上下文" })).toBeNull();
  expect(input).toHaveValue("正在生成的问题");
  if (stop) {
    await user.click(screen.getByRole("button", { name: /停止等待/ }));
    expect(screen.queryByRole("region", { name: "正在生成的回答" })).toBeNull();
    expect(input).toHaveValue("正在生成的问题");
    expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
    await act(async () => { release(); });
    expect(screen.queryByText("第1轮合成答案")).toBeNull();
  } else {
    await act(async () => { release(); });
    await screen.findByRole("region", { name: "第1轮问答" });
    expect(screen.queryByRole("region", { name: "正在生成的回答" })).toBeNull();
    expect(input).toHaveValue("");
  }
});
