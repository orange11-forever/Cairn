import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectAnalysis } from "../../src/components/projects/ProjectAnalysis.tsx";

const reportSessionError = vi.fn();
vi.mock("../../src/session/SessionContext.tsx", () => ({
  useSessionErrorReporter: () => reportSessionError,
}));

const pid = "00000000-0000-4000-8000-000000004001";
const now = "2026-10-19T08:00:00Z";
const result = {
  projectId: pid,
  generatedAt: now,
  assistantName: "项目顾问",
  model: { id: "default", name: "分析模型", model: "synthetic", protocol: "openai-compatible" },
  snapshot: {
    project: { id: pid, revision: 1, name: "交付项目", description: "完成上线验收", createdAt: now, updatedAt: now },
    stages: [], milestones: [], dependencies: [],
    tasks: [{ id: "00000000-0000-4000-8000-000000005001", projectId: pid, revision: 1,
      title: "发布版本", description: "等待部署窗口", assigneeUserId: null, stageId: null,
      milestoneId: null, parentTaskId: null, status: "blocked", priority: "high", dueAt: "2026-10-20T09:00:00Z",
      acceptanceCriteria: "生产可访问", createdAt: now, updatedAt: now }],
  },
  status: "answered", retrievalMode: "keyword_fallback",
  paragraphs: [{ text: "风险：发布任务仍处于阻塞状态。", citationIds: ["S1"] }],
  citations: [],
};
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", "X-Request-ID": "analysis-trace" },
});
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

test("analysis is explicit, sends CSRF and displays findings with inspectable project evidence", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => { requests.push(request); return reply(result); }));
  render(<ProjectAnalysis projectId={pid} csrfToken="csrf" signal={new AbortController().signal} />);
  expect(requests).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "分析项目" }));
  expect(await screen.findByText(result.paragraphs[0]!.text)).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0]!.url).toContain(`/projects/${pid}/analysis`);
  expect(requests[0]!.method).toBe("POST");
  expect(requests[0]!.headers.get("X-CSRF-Token")).toBe("csrf");
  expect(screen.getByText(/项目顾问.*分析模型/)).toBeVisible();
  fireEvent.click(screen.getByText(/S1 · 项目结构快照/));
  expect(screen.getByText("发布版本")).toBeVisible();
  expect(screen.getByText(/优先级：高.*负责人：未分配/)).toBeVisible();
  expect(document.querySelector('time[datetime="2026-10-20T09:00:00Z"]')).toBeVisible();
  expect(screen.getByText(/本次未检索到知识资料/)).toBeVisible();
});

test("a failed reanalysis removes the previous result and offers an explicit retry", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(reply(result)).mockResolvedValueOnce(reply({
    code: "project_analysis_changed", message: "项目、资料或访问权限已变化，请重新分析", traceId: "analysis-trace",
  }, 409));
  vi.stubGlobal("fetch", fetch);
  render(<ProjectAnalysis projectId={pid} csrfToken="csrf" signal={new AbortController().signal} />);
  fireEvent.click(screen.getByRole("button", { name: "分析项目" }));
  await screen.findByText(result.paragraphs[0]!.text);
  fireEvent.click(screen.getByRole("button", { name: "重新分析" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("请重新分析");
  expect(screen.queryByText(result.paragraphs[0]!.text)).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("switching project aborts the request and ignores its late response", async () => {
  let finish!: (response: Response) => void;
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn((request: Request) => {
    requestSignal = request.signal;
    return new Promise<Response>(resolve => { finish = resolve; });
  }));
  const scope = new AbortController();
  const view = render(<ProjectAnalysis projectId={pid} csrfToken="csrf" signal={scope.signal} />);
  fireEvent.click(screen.getByRole("button", { name: "分析项目" }));
  await waitFor(() => expect(requestSignal).toBeDefined());
  expect(screen.getByRole("button", { name: "正在分析…" })).toBeDisabled();
  view.rerender(<ProjectAnalysis projectId="00000000-0000-4000-8000-000000004002" csrfToken="csrf" signal={scope.signal} />);
  expect(requestSignal?.aborted).toBe(true);
  await act(async () => { finish(reply(result)); });
  expect(screen.queryByText(result.paragraphs[0]!.text)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "分析项目" })).toBeEnabled();
});

test("session failure reaches shared invalidation and publishes no result", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => reply({ code: "session_invalid", message: "会话无效或已过期", traceId: "analysis-trace" }, 401)));
  const scope = new AbortController();
  render(<ProjectAnalysis projectId={pid} csrfToken="csrf" signal={scope.signal} />);
  fireEvent.click(screen.getByRole("button", { name: "分析项目" }));
  await waitFor(() => expect(reportSessionError).toHaveBeenCalledWith(expect.objectContaining({ code: "session_invalid" }), expect.any(AbortSignal)));
  expect(screen.queryByText(result.paragraphs[0]!.text)).not.toBeInTheDocument();
});

test.each([
  { ...result, projectId: "00000000-0000-4000-8000-000000004002" },
  { ...result, paragraphs: [{ text: "未知来源", citationIds: ["S6"] }] },
  { ...result, generatedAt: "invalid-time" },
])("malformed or mismatched analysis is rejected at the API boundary", async invalid => {
  vi.stubGlobal("fetch", vi.fn(async () => reply(invalid)));
  render(<ProjectAnalysis projectId={pid} csrfToken="csrf" signal={new AbortController().signal} />);
  fireEvent.click(screen.getByRole("button", { name: "分析项目" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("数据格式不正确");
});

test("insufficient evidence is shown without invented findings", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => reply({ ...result, status: "insufficient_evidence", paragraphs: [] })));
  render(<ProjectAnalysis projectId={pid} csrfToken="csrf" signal={new AbortController().signal} />);
  fireEvent.click(screen.getByRole("button", { name: "分析项目" }));
  expect(await screen.findByText(/现有信息不足以形成分析/)).toBeVisible();
  expect(screen.queryByText(result.paragraphs[0]!.text)).not.toBeInTheDocument();
});
