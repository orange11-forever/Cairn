import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { AppShell } from "../../src/components/AppShell.tsx";
import { KnowledgePage } from "../../src/pages/KnowledgePage.tsx";
import { SessionProvider } from "../../src/session/SessionContext.tsx";
import { ThemeProvider } from "../../src/theme/ThemeContext.tsx";
import type { IdentityContext } from "../../src/api/auth.ts";
import type { KnowledgeConversation } from "../../src/api/knowledgeConversations.ts";

const pid = "00000000-0000-4000-8000-000000000010", cid = "00000000-0000-4000-8000-000000000011";
const stamp = "2026-10-12T12:00:00Z";
const identity: IdentityContext = { user: { id: "user", email: "test@example.com", displayName: "账号" }, organization: { id: "org", slug: "org", name: "组织" }, membership: { id: "member", role: "owner" }, csrfToken: "csrf" };
const stored: KnowledgeConversation = { id: cid, title: "私有历史标题", revision: 2, createdAt: stamp, updatedAt: stamp, turns: [{ id: "00000000-0000-4000-8000-000000000012", sequence: 1, question: "私有历史问题", assistantName: "岑宁", assistantRevision: 0, skillId: null, answerUnavailable: false, contextTruncated: false, createdAt: stamp, answer: { status: "answered", retrievalMode: "hybrid", paragraphs: [{ text: "私有历史回答", citationIds: ["S1"] }], citations: [{ id: "S1", resourceId: pid, resourceVersionId: cid, chunkId: cid, title: "私有证据标题", excerpt: "私有证据摘录", mediaType: "text/plain", locator: { type: "text", headingPath: [], lineStart: 1, lineEnd: 1 }, score: 0.8 }] } }] };
vi.mock("../../src/queries/projects.ts", async original => ({ ...await original<object>(), useProjectQuery: () => ({ isSuccess: true, isFetching: false, data: { name: "合成项目" } }), useProjectsQuery: () => ({ data: undefined }) }));
vi.mock("../../src/queries/knowledge.ts", async original => ({ ...await original<object>(), useKnowledgeResourcesQuery: () => ({ isPending: false, isError: false, fetchStatus: "idle", data: { pages: [{ items: [], capabilities: { canWrite: false } }] } }) }));
function Sources() { const location = useLocation(); return <><output aria-label="来源地址">{location.search}</output><Link to={`/projects/${pid}/knowledge${location.search}`}>返回项目知识</Link></>; }
function mount() {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${pid}/knowledge?conversation=${cid}&view=chat`]}><ThemeProvider><SessionProvider restoredIdentity={identity}><Routes><Route element={<AppShell identity={identity} onLogout={async () => undefined} logoutError={null} />}><Route path="/projects/:projectId/knowledge" element={<KnowledgePage />} /><Route path="/projects/:projectId/knowledge/sources" element={<Sources />} /></Route></Routes></SessionProvider></ThemeProvider></MemoryRouter></QueryClientProvider>);
  return { client, user: userEvent.setup() };
}
function fixture() {
  const { turns: _turns, ...summary } = stored;
  let denied: "list" | "model" | "detail" | null = null;
  let hold = false;
  let resolve!: (response: Response) => void;
  let reject!: (error: Error) => void;
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request, path = new URL(request.url).pathname;
    if (path.endsWith("/assistant-settings")) return Response.json({name:"岑宁",instructions:"",enabledSkillIds:[],revision:0});
    if (path.endsWith("/skills")) return Response.json({items:[]});
    if (path.endsWith("/turns")) throw new TypeError("lost append response");
    if (path.endsWith("/assistants")) return Response.json({ items: [] });
    const target = path.endsWith("/answer-model") ? "model" : path.endsWith("/conversations") ? "list" : "detail";
    if (target === denied) return Response.json({ code: "not_found", message: "资源不存在", traceId: "denied" }, { status: 404 });
    if (target === "model") return Response.json({ configured: true, model: "gpt-test", protocol: "openai-compatible", defaultModelId: "default", models: [{ id: "default", name: "gpt-test", model: "gpt-test", protocol: "openai-compatible" }] });
    if (target === "list") return Response.json({ items: [summary], nextCursor: null });
    if (hold) return new Promise<Response>((done, fail) => { resolve = done; reject = fail; });
    return Response.json(stored);
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, deny: (target: typeof denied) => { denied = target; }, hold: () => { hold = true; }, release: () => { hold = false; }, resolve: (response: Response) => resolve(response), reject: () => reject(new TypeError("read failed")) };
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test.each(["network", "503", "contract", "404", "cancel"])("manual reread hides history through pending/%s/retry and keeps sending unverified", async failure => {
  const api = fixture(); const { user } = mount();
  await screen.findByText("私有历史回答");
  api.hold();
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  expect(screen.queryByText("私有历史回答")).toBeNull(); expect(screen.queryByText("私有证据摘录")).toBeNull();
  if (failure === "cancel") await user.click(screen.getByRole("button", { name: "停止等待" }));
  else await act(async () => {
    if (failure === "network") api.reject();
    else api.resolve(Response.json(failure === "contract" ? { ...stored, revision: 99 } : { code: "not_found", message: "无法读取", traceId: "read" }, { status: failure === "503" ? 503 : failure === "404" ? 404 : 200 }));
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "重新读取会话" })).toBeEnabled());
  expect(screen.queryByText("私有历史回答")).toBeNull(); expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  expect(screen.queryByText("私有历史回答")).toBeNull(); expect(screen.queryByText("私有证据摘录")).toBeNull();
  api.release();
  await act(async () => api.resolve(Response.json(stored)));
  await screen.findByText("私有历史回答");
});

test.each(["list", "model"] as const)("project %s404 clears private sidebar/selector titles and detail", async target => {
  const api = fixture(); const { client } = mount();
  await screen.findByText("私有历史回答");
  const sidebar = screen.getByRole("region", { name: "项目对话历史" });
  expect(within(sidebar).getByText("私有历史标题")).toBeInTheDocument();
  api.deny(target);
  await act(async () => { await client.invalidateQueries({ predicate: query => query.queryKey.at(-1) === target }); });
  await waitFor(() => expect(within(sidebar).queryByText("私有历史标题")).toBeNull());
  expect(screen.queryByText("私有历史回答")).toBeNull();
  expect(screen.queryByText("私有历史标题", { selector: "option" })).toBeNull();
});

test("conversation-only404 keeps authorized project titles in shell history", async () => {
  const api = fixture(); const { user } = mount();
  await screen.findByText("私有历史回答"); api.deny("detail");
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  await screen.findByText("重新读取失败，请保留草稿并再次读取会话。");
  expect(within(screen.getByRole("region", { name: "项目对话历史" })).getByText("私有历史标题")).toBeInTheDocument();
});

test.each([false, true])("explorer source roundtrip preserves selected draft and recovery=%s", async recovery => {
  fixture(); const { user } = mount();
  await screen.findByText("私有历史回答");
  const input = screen.getByLabelText("向项目知识提问");
  await user.type(input, "来源页面往返草稿");
  if (recovery) { await user.click(screen.getByRole("button", { name: "生成回答" })); await screen.findByText(/发送结果尚未确认，请重新读取会话/); }
  await user.click(screen.getByRole("link", { name: "打开来源与同步" }));
  expect(screen.getByLabelText("来源地址")).toHaveTextContent(`conversation=${cid}`);
  await user.click(screen.getByRole("link", { name: "返回项目知识" }));
  expect(screen.getByLabelText("向项目知识提问")).toHaveValue("来源页面往返草稿");
  expect(screen.getByLabelText("选择对话")).toHaveValue(cid);
  if (recovery) expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
});

test("append404 keeps loaded history unverified through explicit reread retry", async () => {
  const api = fixture(); const base = globalThis.fetch;
  let resolveAppend!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new URL((input as Request).url).pathname.endsWith("/turns") ? new Promise<Response>(resolve => { resolveAppend = resolve; }) : base(input)));
  const { user } = mount();
  await screen.findByText("私有历史回答");
  await user.type(screen.getByLabelText("向项目知识提问"), "新增问题保留草稿");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  await waitFor(() => expect(resolveAppend).toBeDefined());
  await act(async () => resolveAppend(Response.json({ code: "not_found", message: "资源不存在", traceId: "append-denied" }, { status: 404 })));
  await screen.findByText(/发送结果尚未确认，请重新读取会话/);
  expect(screen.queryByText("私有历史回答")).toBeNull(); expect(screen.queryByText("私有证据摘录")).toBeNull();
  expect(screen.getByLabelText("向项目知识提问")).toHaveValue("新增问题保留草稿");
  expect(within(screen.getByRole("region", { name: "项目对话历史" })).getByText("私有历史标题")).toBeInTheDocument();
  api.hold();
  await user.click(screen.getByRole("button", { name: "重新读取会话" }));
  expect(screen.queryByText("私有历史回答")).toBeNull(); expect(screen.queryByText("私有证据摘录")).toBeNull();
  api.release();
  await act(async () => api.resolve(Response.json(stored)));
  await screen.findByText("私有历史回答");
});
