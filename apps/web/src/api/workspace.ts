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
