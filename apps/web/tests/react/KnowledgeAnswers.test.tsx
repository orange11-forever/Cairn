import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, expect, test, vi } from "vitest";

import { KnowledgeAnswers } from "../../src/components/knowledge/KnowledgeAnswers.tsx";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";

function renderAnswers(overrides: Partial<ComponentProps<typeof KnowledgeAnswers>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const props: ComponentProps<typeof KnowledgeAnswers> = {
    organizationId: "00000000-0000-4000-8000-000000002001",
    projectId: PROJECT_ID,
    csrfToken: "csrf-answer-test",
    sessionSignal: new AbortController().signal,
    onAccessUnavailable: vi.fn(),
    ...overrides,
  };
  const result = render(
    <QueryClientProvider client={queryClient}><KnowledgeAnswers {...props} /></QueryClientProvider>,
  );
  return { ...result, queryClient, props };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("submits one question and renders cited plain-text paragraphs", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json({
      status: "answered",
      retrievalMode: "hybrid",
      paragraphs: [{ text: "交付日期是 9 月 30 日。", citationIds: ["S1"] }],
      citations: [{
        id: "S1",
        resourceId: "00000000-0000-4000-8000-000000005001",
        resourceVersionId: "00000000-0000-4000-8000-000000006001",
        chunkId: "00000000-0000-4000-8000-000000007001",
        title: "项目说明.txt", mediaType: "text/plain",
        excerpt: "项目的交付日期是 9 月 30 日。",
        locator: { type: "text", headingPath: [], lineStart: 1, lineEnd: 2 }, score: 0.9,
      }],
    });
  }));
  const user = userEvent.setup();
  const { container } = renderAnswers();

  await user.type(screen.getByLabelText("向项目知识提问"), "  什么时候交付？  ");
  await user.click(screen.getByRole("button", { name: "生成回答" }));

  const answer = await screen.findByRole("region", { name: "生成式回答" });
  expect(within(answer).getByText("交付日期是 9 月 30 日。")).toBeInTheDocument();
  expect(screen.getByLabelText("向项目知识提问")).toHaveValue("什么时候交付?");
  expect(within(answer).getByText("S1 · 项目说明.txt")).toBeInTheDocument();
  expect(container.querySelector("script, iframe, object, embed")).toBeNull();
  expect(requests).toHaveLength(1);
  expect(await requests[0]!.clone().json()).toEqual({ question: "什么时候交付?" });
  expect(requests[0]!.headers.get("X-CSRF-Token")).toBe("csrf-answer-test");
});

test.each([
  [true, "第二轮草稿"],
  [false, ""],
] as const)("docked answer keeps a draft edited during pending=%s", async (editPending, expectedDraft) => {
  let resolveResponse!: (response: Response) => void;
  const fetchSpy = vi.fn(() => new Promise<Response>((resolve) => { resolveResponse = resolve; }));
  vi.stubGlobal("fetch", fetchSpy);
  const user = userEvent.setup();
  renderAnswers({ docked: true });
  const input = screen.getByLabelText("向项目知识提问");
  await user.type(input, "第一轮问题");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("正在查找资料并生成回答…");
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
  if (editPending) {
    await user.clear(input);
    await user.type(input, "第二轮草稿");
  }
  await act(async () => resolveResponse(Response.json({
    status: "insufficient_evidence", retrievalMode: "hybrid", paragraphs: [], citations: [],
  })));
  expect(await screen.findByText("现有项目资料不足以回答这个问题")).toBeInTheDocument();
  expect(input).toHaveValue(expectedDraft);
  expect(screen.getByText("第一轮问题", { selector: ".knowledge-answer-question span" }))
    .toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledTimes(1);
});

test("renders insufficient evidence and rejects invalid response invariants", async () => {
  const responses = [
    { status: "insufficient_evidence", retrievalMode: "keyword_fallback", paragraphs: [], citations: [] },
    { status: "answered", retrievalMode: "hybrid", paragraphs: [{ text: "坏回答", citationIds: ["S2"] }], citations: [] },
  ];
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(responses.shift())));
  const user = userEvent.setup();
  renderAnswers();
  const input = screen.getByLabelText("向项目知识提问");

  await user.type(input, "资料中有答案吗？");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  expect(await screen.findByText("现有项目资料不足以回答这个问题")).toBeInTheDocument();

  await user.clear(input);
  await user.type(input, "再问一个问题？");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("数据格式不正确");
});

test("cancel and resource deletion clear the answer and abort late requests", async () => {
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requestSignal = (input as Request).signal;
    return await new Promise<Response>((_resolve, reject) => {
      requestSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    });
  }));
  const user = userEvent.setup();
  const rendered = renderAnswers();
  await user.type(screen.getByLabelText("向项目知识提问"), "什么时候交付？");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("正在查找资料并生成回答…");
  await user.click(screen.getByRole("button", { name: "取消" }));
  await waitFor(() => expect(requestSignal?.aborted).toBe(true));
  expect(screen.queryByText("正在查找资料并生成回答…")).not.toBeInTheDocument();

  rendered.rerender(
    <QueryClientProvider client={new QueryClient()}>
      <KnowledgeAnswers
        organizationId="org" projectId={PROJECT_ID} csrfToken="csrf-answer-test"
        sessionSignal={new AbortController().signal} onAccessUnavailable={vi.fn()}
        resourceDeletion={{ revision: 1, title: "项目说明.txt" }}
      />
    </QueryClientProvider>,
  );
  expect(screen.getByText(/资料“项目说明.txt”已删除，回答已清空/)).toBeInTheDocument();
});

test.each([
  [404, "not_found", "资源不存在"],
  [409, "knowledge_changed", "项目资料已发生变化，请重新提问"],
  [429, "search_rate_limited", "提问过于频繁，请在 17 秒后重试"],
  [503, "answer_unavailable", "生成式回答暂时不可用"],
] as const)("presents answer HTTP %s without automatic retry", async (status, code, message) => {
  const fetchSpy = vi.fn(async () => new Response(JSON.stringify({
    code, message: status === 409 ? "知识已变化" : message, traceId: `trace-${status}`,
  }), {
    status,
    headers: { "Content-Type": "application/json", ...(status === 429 ? { "Retry-After": "17" } : {}) },
  }));
  vi.stubGlobal("fetch", fetchSpy);
  const onAccessUnavailable = vi.fn();
  const user = userEvent.setup();
  renderAnswers({ onAccessUnavailable });

  await user.type(screen.getByLabelText("向项目知识提问"), "错误边界问题");
  await user.click(screen.getByRole("button", { name: "生成回答" }));

  if (status === 404) await waitFor(() => expect(onAccessUnavailable).toHaveBeenCalledTimes(1));
  else expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(fetchSpy).toHaveBeenCalledTimes(1);
});

test("offline state clears an existing answer and never replays when connectivity returns", async () => {
  let online = true;
  vi.spyOn(window.navigator, "onLine", "get").mockImplementation(() => online);
  const storageSpy = vi.spyOn(Storage.prototype, "setItem");
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    status: "insufficient_evidence", retrievalMode: "hybrid", paragraphs: [], citations: [],
  })));
  const user = userEvent.setup();
  renderAnswers();
  await user.type(screen.getByLabelText("向项目知识提问"), "离线边界问题");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  expect(await screen.findByText("现有项目资料不足以回答这个问题")).toBeInTheDocument();

  online = false;
  window.dispatchEvent(new Event("offline"));
  expect(await screen.findByText("当前处于离线状态，回答已清空")).toBeInTheDocument();
  expect(screen.queryByText("现有项目资料不足以回答这个问题")).toBeNull();
  expect(screen.getByRole("button", { name: "生成回答" })).toBeDisabled();
  online = true;
  window.dispatchEvent(new Event("online"));
  expect(storageSpy).not.toHaveBeenCalled();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("resource deletion clears a completed answer without generating again", async () => {
  const fetchSpy = vi.fn(async () => Response.json({
    status: "insufficient_evidence", retrievalMode: "hybrid", paragraphs: [], citations: [],
  }));
  vi.stubGlobal("fetch", fetchSpy);
  const user = userEvent.setup();
  const rendered = renderAnswers();
  await user.type(screen.getByLabelText("向项目知识提问"), "删除资料边界");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  expect(await screen.findByText("现有项目资料不足以回答这个问题")).toBeInTheDocument();

  rendered.rerender(
    <QueryClientProvider client={rendered.queryClient}>
      <KnowledgeAnswers {...rendered.props}
        resourceDeletion={{ revision: 1, title: "已删除资料.pdf" }} />
    </QueryClientProvider>,
  );

  expect(await screen.findByText(/资料“已删除资料.pdf”已删除，回答已清空/)).toBeInTheDocument();
  expect(screen.queryByText("现有项目资料不足以回答这个问题")).toBeNull();
  expect(fetchSpy).toHaveBeenCalledTimes(1);
});

test("session abort clears pending work and masks a late session-invalid response", async () => {
  const session = new AbortController();
  let resolveResponse: ((value: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn(async () => await new Promise<Response>((resolve) => {
    resolveResponse = resolve;
  })));
  const user = userEvent.setup();
  renderAnswers({ sessionSignal: session.signal });
  await user.type(screen.getByLabelText("向项目知识提问"), "会话取消边界");
  await user.click(screen.getByRole("button", { name: "生成回答" }));
  await screen.findByText("正在查找资料并生成回答…");

  session.abort();
  resolveResponse?.(new Response(JSON.stringify({
    code: "session_invalid", message: "会话无效", traceId: "late-401",
  }), { status: 401, headers: { "Content-Type": "application/json" } }));

  await waitFor(() => expect(screen.queryByText("正在查找资料并生成回答…")).toBeNull());
  expect(screen.queryByText("会话无效")).toBeNull();
});
