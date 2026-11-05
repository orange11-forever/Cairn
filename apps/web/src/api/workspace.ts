import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { parseApiErrorResponse } from "./parseApiErrorResponse.ts";

export type GitHubDeviceStarted = components["schemas"]["GitHubDeviceStarted"];
export type GitHubDeviceResult = components["schemas"]["GitHubDeviceResult"];
export type GitHubRepository = components["schemas"]["GitHubRepository"];
export type RepositoryBinding = components["schemas"]["RepositoryBinding"];
export type RepositoryBindRequest = components["schemas"]["RepositoryBindRequest"];
export type GitHubConnection = components["schemas"]["GitHubConnection"];
export type RepositorySnapshot = components["schemas"]["RepositorySnapshot"];
export type ArchitectureAnalysis = components["schemas"]["ArchitectureAnalysis"];
const client = () => createCairnClient({ baseUrl: apiOrigins.identity });
const headers = (csrfToken?: string) => csrfToken ? { "X-CSRF-Token": csrfToken } : {};

type Result = { data?: unknown; error?: unknown; response: Response };
async function perform(signal: AbortSignal, run: (signal: AbortSignal) => Promise<Result>, timeout = 30_000): Promise<Result> {
  const combined = AbortSignal.any([signal, AbortSignal.timeout(timeout)]);
  try {
    const result = await run(combined);
    if (!result.response.ok) {
      const detail = parseApiErrorResponse(result.error, { message: "仓库操作失败，请重试", code: "http_error", traceId: result.response.headers.get("X-Request-ID") });
      throw new ApiError("http", detail.message, { code: detail.code, status: result.response.status, traceId: detail.traceId });
    }
    return result;
  } catch (error) {
    if (combined.aborted) throw new ApiError(signal.aborted ? "aborted" : "timeout", "请求已中断。请刷新关联状态并检查目标目录后再操作。", { cause: error });
    if (error instanceof ApiError) throw error;
    throw new ApiError("network", "无法连接本地服务，请刷新状态后重试", { cause: error });
  }
}
function parse<Name extends keyof components["schemas"]>(name: Name, result: Result): components["schemas"][Name] {
  if (!matchesComponentSchema(name, result.data)) throw new ApiError("contract", "仓库响应格式无效，请更新 Cairn");
  return result.data;
}

export type TerminalSnapshot = components['schemas']['TerminalSnapshot'];
export async function fetchTerminal(projectId: string, after: number, signal: AbortSignal) {
  const result = await perform(signal, signal => client().GET('/api/v1/desktop/projects/{project_id}/terminal', { params: { path: { project_id: projectId }, query: { after } }, signal }));
  return result.data === null ? null : parse('TerminalSnapshot', result);
}
export async function startTerminal(projectId: string, body: components['schemas']['TerminalStart'], csrfToken: string, signal: AbortSignal) {
  return parse('TerminalSnapshot', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/terminal', { params: { path: { project_id: projectId }, header: { 'X-CSRF-Token': csrfToken } }, body, signal })));
}
export async function writeTerminal(projectId: string, terminalId: string, data: string, csrfToken: string, signal: AbortSignal) {
  await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/terminal/{terminal_id}/input', { params: { path: { project_id: projectId, terminal_id: terminalId }, header: { 'X-CSRF-Token': csrfToken } }, body: { data }, signal }));
}
export async function resizeTerminal(projectId: string, terminalId: string, cols: number, rows: number, csrfToken: string, signal: AbortSignal) {
  await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/terminal/{terminal_id}/resize', { params: { path: { project_id: projectId, terminal_id: terminalId }, header: { 'X-CSRF-Token': csrfToken } }, body: { cols, rows }, signal }));
}
export async function closeTerminal(projectId: string, terminalId: string, csrfToken: string, signal: AbortSignal) {
  return parse('TerminalSnapshot', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/terminal/{terminal_id}/close', { params: { path: { project_id: projectId, terminal_id: terminalId }, header: { 'X-CSRF-Token': csrfToken } }, signal })));
}

export async function startGitHubDevice({ intent, csrfToken }: { intent: "login" | "link" | "repositories"; csrfToken?: string }, signal: AbortSignal) {
  return parse("GitHubDeviceStarted", await perform(signal, signal => client().POST("/api/v1/desktop/github/device", { body: { intent }, headers: headers(csrfToken), signal })));
}
export async function pollGitHubDevice(attemptId: string, csrfToken: string | undefined, signal: AbortSignal) {
  return parse("GitHubDeviceResult", await perform(signal, signal => client().POST("/api/v1/desktop/github/device/poll", { body: { attemptId }, headers: headers(csrfToken), signal })));
}
export async function cancelGitHubDevice({ attemptId, csrfToken }: { attemptId: string; csrfToken?: string }, signal: AbortSignal) {
  await perform(signal, signal => client().DELETE("/api/v1/desktop/github/device", { body: { attemptId }, headers: headers(csrfToken), signal }));
  return true;
}
export async function fetchGitHubConnection(signal: AbortSignal) {
  return parse("GitHubConnection", await perform(signal, signal => client().GET("/api/v1/desktop/github/connection", { signal })));
}
export async function disconnectGitHub(csrfToken: string, signal: AbortSignal) {
  await perform(signal, signal => client().DELETE("/api/v1/desktop/github/connection", { params: { header: { "X-CSRF-Token": csrfToken } }, signal }));
  return true;
}
export async function fetchGitHubRepositories(page: number, signal: AbortSignal) {
  return parse("GitHubRepositoryPage", await perform(signal, signal => client().GET("/api/v1/desktop/github/repositories", { params: { query: { page } }, signal })));
}
export async function fetchWorkspace(projectId: string, signal: AbortSignal) {
  return parse("WorkspaceStatus", await perform(signal, signal => client().GET("/api/v1/desktop/projects/{project_id}/repository", { params: { path: { project_id: projectId } }, signal })));
}
export async function bindRepository({ projectId, csrfToken, ...body }: RepositoryBindRequest & { projectId: string; csrfToken: string }, signal: AbortSignal) {
  return parse("RepositoryBinding", await perform(signal, signal => client().PUT("/api/v1/desktop/projects/{project_id}/repository", { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, body, signal }), 210_000));
}
export async function unbindRepository({ projectId, csrfToken }: { projectId: string; csrfToken: string }, signal: AbortSignal) {
  await perform(signal, signal => client().DELETE("/api/v1/desktop/projects/{project_id}/repository", { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, signal }));
  return true;
}

export async function fetchRepositorySources(projectId: string, signal: AbortSignal) {
  return parse("RepositorySnapshot", await perform(signal, signal => client().GET("/api/v1/desktop/projects/{project_id}/architecture", { params: { path: { project_id: projectId } }, signal })));
}
export async function analyzeArchitecture({ projectId, csrfToken, ...body }: components["schemas"]["ArchitectureRequest"] & { projectId: string; csrfToken: string }, signal: AbortSignal) {
  return parse("ArchitectureAnalysis", await perform(signal, signal => client().POST("/api/v1/desktop/projects/{project_id}/architecture", { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, body, signal }), 120_000));
}

export type FileDocument = components['schemas']['FileDocument'];
export type FileDiff = components['schemas']['FileDiff'];
export async function fetchFileTree(projectId: string, signal: AbortSignal) {
  return parse('FileTree', await perform(signal, signal => client().GET('/api/v1/desktop/projects/{project_id}/files', { params: { path: { project_id: projectId } }, signal })));
}
export async function readWorkspaceFile(projectId: string, path: string, signal: AbortSignal) {
  return parse('FileDocument', await perform(signal, signal => client().GET('/api/v1/desktop/projects/{project_id}/file', { params: { path: { project_id: projectId }, query: { path } }, signal })));
}
export async function saveWorkspaceFile(projectId: string, body: components['schemas']['SaveFileRequest'], csrfToken: string, signal: AbortSignal) {
  return parse('FileDocument', await perform(signal, signal => client().PUT('/api/v1/desktop/projects/{project_id}/file', { params: { path: { project_id: projectId }, header: { 'X-CSRF-Token': csrfToken } }, body, signal })));
}
export async function fetchWorkspaceChanges(projectId: string, signal: AbortSignal) {
  return parse('RepositoryChanges', await perform(signal, signal => client().GET('/api/v1/desktop/projects/{project_id}/changes', { params: { path: { project_id: projectId } }, signal })));
}
export async function fetchFileDiff(projectId: string, path: string, signal: AbortSignal) {
  return parse('FileDiff', await perform(signal, signal => client().GET('/api/v1/desktop/projects/{project_id}/diff', { params: { path: { project_id: projectId }, query: { path } }, signal })));
}

export type CodingRun = components['schemas']['CodingRun'];
export type CodingChange = components['schemas']['CodingChange'];
export async function fetchCodingRuns(projectId: string, signal: AbortSignal) {
  return parse('CodingRunList', await perform(signal, signal => client().GET('/api/v1/desktop/projects/{project_id}/coding-runs', { params: { path: { project_id: projectId } }, signal })));
}
export async function fetchCodingRun(projectId: string, runId: string, signal: AbortSignal) {
  return parse('CodingRun', await perform(signal, signal => client().GET('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}', { params: { path: { project_id: projectId, run_id: runId } }, signal })));
}
export async function fetchCodingOverview(signal: AbortSignal) {
  return parse('CodingOverview', await perform(signal, signal => client().GET('/api/v1/desktop/coding-runs', { signal })));
}
export async function setCodingConcurrency(limit: number, csrfToken: string, signal: AbortSignal) {
  return parse('CodingConcurrency', await perform(signal, signal => client().PUT('/api/v1/desktop/coding-concurrency', { params: { header: { 'X-CSRF-Token': csrfToken } }, body: { limit }, signal })));
}
export async function startCodingRun(projectId: string, body: components['schemas']['CodingStart'], csrfToken: string, signal: AbortSignal) {
  return parse('CodingRun', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/coding-runs', { params: { path: { project_id: projectId }, header: { 'X-CSRF-Token': csrfToken } }, body, signal })));
}
export async function decideCodingCommand(projectId: string, runId: string, body: components['schemas']['CommandDecision'], csrfToken: string, signal: AbortSignal) {
  return parse('CodingRun', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/decision', { params: { path: { project_id: projectId, run_id: runId }, header: { 'X-CSRF-Token': csrfToken } }, body, signal })));
}
export async function cancelCodingRun(projectId: string, runId: string, csrfToken: string, signal: AbortSignal) {
  return parse('CodingRun', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/cancel', { params: { path: { project_id: projectId, run_id: runId }, header: { 'X-CSRF-Token': csrfToken } }, signal })));
}

export type DeliveryReview = components['schemas']['DeliveryReview'];
export type RemoteTarget = components['schemas']['RemoteTarget'];
export async function fetchDeliveryReview(projectId: string, runId: string, signal: AbortSignal) {
  return parse('DeliveryReview', await perform(signal, signal => client().GET('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/delivery', { params: { path: { project_id: projectId, run_id: runId } }, signal })));
}
export async function commitCodingRun(projectId: string, runId: string, body: components['schemas']['CommitRequest'], csrfToken: string, signal: AbortSignal) {
  return parse('CodingRun', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/delivery/commit', { params: { path: { project_id: projectId, run_id: runId }, header: { 'X-CSRF-Token': csrfToken } }, body, signal }), 180_000));
}
export async function prepareCodingTarget(projectId: string, runId: string, baseBranch: string, csrfToken: string, signal: AbortSignal) {
  return parse('RemoteTarget', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/delivery/target', { params: { path: { project_id: projectId, run_id: runId }, header: { 'X-CSRF-Token': csrfToken } }, body: { baseBranch }, signal }), 90_000));
}
export async function pushCodingRun(projectId: string, runId: string, target: RemoteTarget, csrfToken: string, signal: AbortSignal) {
  return parse('CodingRun', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/delivery/push', { params: { path: { project_id: projectId, run_id: runId }, header: { 'X-CSRF-Token': csrfToken } }, body: { target, allowPush: true }, signal }), 240_000));
}
export async function createCodingPullRequest(projectId: string, runId: string, body: components['schemas']['PullRequestInput'], csrfToken: string, signal: AbortSignal) {
  return parse('CodingRun', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/delivery/pull-request', { params: { path: { project_id: projectId, run_id: runId }, header: { 'X-CSRF-Token': csrfToken } }, body, signal }), 120_000));
}
export async function reconcileCodingDelivery(projectId: string, runId: string, csrfToken: string, signal: AbortSignal) {
  return parse('CodingRun', await perform(signal, signal => client().POST('/api/v1/desktop/projects/{project_id}/coding-runs/{run_id}/delivery/reconcile', { params: { path: { project_id: projectId, run_id: runId }, header: { 'X-CSRF-Token': csrfToken } }, signal }), 90_000));
}
