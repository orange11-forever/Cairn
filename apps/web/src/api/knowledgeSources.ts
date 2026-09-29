import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { knowledgeContractError } from "./knowledgeRequest.ts";

export type KnowledgeSource = components["schemas"]["KnowledgeSourceResponse"];
export type KnowledgeSourcePage = components["schemas"]["KnowledgeSourcePage"];
export type KnowledgeSourceSync = components["schemas"]["KnowledgeSourceSyncResponse"];
export type KnowledgeSourceSyncPage = components["schemas"]["KnowledgeSourceSyncPage"];
export type FeishuSourceCreate = components["schemas"]["FeishuSourceCreateRequest"];
export type FeishuSourcePatch = components["schemas"]["FeishuSourcePatchRequest"];

const client = () => createCairnClient({ baseUrl: apiOrigins.identity });
const sameId = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return undefined;
  try { return JSON.parse(value) as unknown; } catch { return undefined; }
}

function failure(error: unknown, response: Response, context: string): ApiError {
  const parsed = typeof error === "string" ? parseJson(error) : error;
  const code = matchesComponentSchema("ErrorBody", parsed) ? parsed.code : null;
  const traceId = matchesComponentSchema("ErrorBody", parsed)
    ? parsed.traceId : response.headers.get("X-Request-ID");
  const message = response.status === 409 ? "该飞书文档已登记，请在来源列表中查看" :
    response.status === 404 ? "来源或项目不可用，请刷新页面" :
    response.status === 403 ? "没有权限执行此操作，请刷新页面" :
    response.status === 422 ? "提交的信息无效，请检查后重试" :
    response.status === 401 ? "会话已失效，请重新登录" :
    "来源操作暂时失败，请稍后重试";
  return new ApiError("http", message, { status: response.status, code, traceId, context });
}

function requestFailure(error: unknown, context: string, signal: AbortSignal): ApiError {
  // A late HTTP 401 from an old session must never expire the replacement session.
  if (signal.aborted) return new ApiError("aborted", "请求已被取消", { context, cause: error });
  if (error instanceof ApiError) return error;
  return new ApiError("network", "无法连接服务器，请检查网络", { context, cause: error });
}

function expectedBody(data: unknown, response: Response, status: number, context: string): unknown {
  if (response.status !== status || !response.ok) throw knowledgeContractError(context);
  const parsed = parseJson(data);
  if (parsed === undefined) throw knowledgeContractError(context);
  return parsed;
}

function checkedSource(value: unknown, projectId: string, context: string, sourceId?: string): KnowledgeSource {
  if (!matchesComponentSchema("KnowledgeSourceResponse", value) ||
    !sameId(value.projectId, projectId) ||
    (sourceId !== undefined && !sameId(value.id, sourceId)) ||
    (value.status === "disabled") !== (value.disabledAt !== null) ||
    (value.syncIntervalSeconds !== null &&
      (!Number.isInteger(value.syncIntervalSeconds) || value.syncIntervalSeconds < 300 || value.syncIntervalSeconds > 604800))) {
    throw knowledgeContractError(context);
  }
  return value;
}

function checkedSync(value: unknown, projectId: string, sourceId: string, context: string, syncId?: string): KnowledgeSourceSync {
  if (!matchesComponentSchema("KnowledgeSourceSyncResponse", value) ||
    !sameId(value.projectId, projectId) || !sameId(value.sourceId, sourceId) ||
    (syncId !== undefined && !sameId(value.id, syncId)) ||
    (value.resourceId === null) !== (value.resourceVersionId === null) ||
    (value.resourceId === null && value.resourceStatus !== null)) {
    throw knowledgeContractError(context);
  }
  return value;
}

export async function fetchKnowledgeSources({ projectId, cursor, signal }: {
  projectId: string; cursor: string | null; signal: AbortSignal;
}): Promise<KnowledgeSourcePage> {
  const context = "GET /api/v1/projects/{project_id}/knowledge/sources";
  try {
    const { data, error, response } = await client().GET("/api/v1/projects/{project_id}/knowledge/sources", {
      params: { path: { project_id: projectId }, query: cursor === null ? {} : { cursor } }, parseAs: "text", signal,
    });
    if (!response.ok) throw failure(error, response, context);
    const parsed = expectedBody(data, response, 200, context);
    if (!matchesComponentSchema("KnowledgeSourcePage", parsed)) throw knowledgeContractError(context);
    parsed.items.forEach((item) => checkedSource(item, projectId, context));
    return parsed;
  } catch (error) { throw requestFailure(error, context, signal); }
}

export async function fetchKnowledgeSource({ projectId, sourceId, signal }: {
  projectId: string; sourceId: string; signal: AbortSignal;
}): Promise<KnowledgeSource> {
  const context = "GET /api/v1/projects/{project_id}/knowledge/sources/{source_id}";
  try {
    const { data, error, response } = await client().GET("/api/v1/projects/{project_id}/knowledge/sources/{source_id}", {
      params: { path: { project_id: projectId, source_id: sourceId } }, parseAs: "text", signal,
    });
    if (!response.ok) throw failure(error, response, context);
    return checkedSource(expectedBody(data, response, 200, context), projectId, context, sourceId);
  } catch (error) { throw requestFailure(error, context, signal); }
}

export async function createFeishuSource({ projectId, body, csrfToken, signal }: {
  projectId: string; body: FeishuSourceCreate; csrfToken: string; signal: AbortSignal;
}): Promise<KnowledgeSource> {
  const context = "POST /api/v1/projects/{project_id}/knowledge/sources/feishu";
  try {
    const { data, error, response } = await client().POST("/api/v1/projects/{project_id}/knowledge/sources/feishu", {
      params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } },
      body, parseAs: "text", signal,
    });
    if (!response.ok) throw failure(error, response, context);
    const source = checkedSource(expectedBody(data, response, 201, context), projectId, context);
    if (source.documentId !== body.documentId || source.credentialRef !== body.credentialRef || source.name !== body.name.trim()) {
      throw knowledgeContractError(context);
    }
    return source;
  } catch (error) { throw requestFailure(error, context, signal); }
}

export async function patchFeishuSource({ projectId, sourceId, body, csrfToken, signal }: {
  projectId: string; sourceId: string; body: FeishuSourcePatch; csrfToken: string; signal: AbortSignal;
}): Promise<KnowledgeSource> {
  const context = "PATCH /api/v1/projects/{project_id}/knowledge/sources/{source_id}";
  try {
    const { data, error, response } = await client().PATCH("/api/v1/projects/{project_id}/knowledge/sources/{source_id}", {
      params: { path: { project_id: projectId, source_id: sourceId }, header: { "X-CSRF-Token": csrfToken } },
      body, parseAs: "text", signal,
    });
    if (!response.ok) throw failure(error, response, context);
    const source = checkedSource(expectedBody(data, response, 200, context), projectId, context, sourceId);
    if ((body.name !== undefined && body.name !== null && source.name !== body.name.trim()) ||
      (body.credentialRef !== undefined && body.credentialRef !== null && source.credentialRef !== body.credentialRef) ||
      (body.status !== undefined && body.status !== null && source.status !== body.status) ||
      (body.syncIntervalSeconds !== undefined && source.syncIntervalSeconds !== body.syncIntervalSeconds)) {
      throw knowledgeContractError(context);
    }
    return source;
  } catch (error) { throw requestFailure(error, context, signal); }
}

export async function disableFeishuSource({ projectId, sourceId, csrfToken, signal }: {
  projectId: string; sourceId: string; csrfToken: string; signal: AbortSignal;
}): Promise<void> {
  const context = "DELETE /api/v1/projects/{project_id}/knowledge/sources/{source_id}";
  try {
    const { data, error, response } = await client().DELETE("/api/v1/projects/{project_id}/knowledge/sources/{source_id}", {
      params: { path: { project_id: projectId, source_id: sourceId }, header: { "X-CSRF-Token": csrfToken } },
      parseAs: "text", signal,
    });
    if (!response.ok) throw failure(error, response, context);
    if (response.status !== 204 || (data !== undefined && data !== "")) throw knowledgeContractError(context);
  } catch (error) { throw requestFailure(error, context, signal); }
}

export async function queueFeishuSync({ projectId, sourceId, csrfToken, signal }: {
  projectId: string; sourceId: string; csrfToken: string; signal: AbortSignal;
}): Promise<KnowledgeSourceSync> {
  const context = "POST /api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs";
  try {
    const { data, error, response } = await client().POST("/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs", {
      params: { path: { project_id: projectId, source_id: sourceId }, header: { "X-CSRF-Token": csrfToken } },
      body: {}, parseAs: "text", signal,
    });
    if (!response.ok) throw failure(error, response, context);
    return checkedSync(expectedBody(data, response, 202, context), projectId, sourceId, context);
  } catch (error) { throw requestFailure(error, context, signal); }
}

export async function fetchFeishuSyncs({ projectId, sourceId, cursor, signal }: {
  projectId: string; sourceId: string; cursor: string | null; signal: AbortSignal;
}): Promise<KnowledgeSourceSyncPage> {
  const context = "GET /api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs";
  try {
    const { data, error, response } = await client().GET("/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs", {
      params: { path: { project_id: projectId, source_id: sourceId }, query: cursor === null ? {} : { cursor } },
      parseAs: "text", signal,
    });
    if (!response.ok) throw failure(error, response, context);
    const parsed = expectedBody(data, response, 200, context);
    if (!matchesComponentSchema("KnowledgeSourceSyncPage", parsed)) throw knowledgeContractError(context);
    parsed.items.forEach((item) => checkedSync(item, projectId, sourceId, context));
    return parsed;
  } catch (error) { throw requestFailure(error, context, signal); }
}

export async function fetchFeishuSync({ projectId, sourceId, syncId, signal }: {
  projectId: string; sourceId: string; syncId: string; signal: AbortSignal;
}): Promise<KnowledgeSourceSync> {
  const context = "GET /api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs/{sync_id}";
  try {
    const { data, error, response } = await client().GET("/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs/{sync_id}", {
      params: { path: { project_id: projectId, source_id: sourceId, sync_id: syncId } }, parseAs: "text", signal,
    });
    if (!response.ok) throw failure(error, response, context);
    return checkedSync(expectedBody(data, response, 200, context), projectId, sourceId, context, syncId);
  } catch (error) { throw requestFailure(error, context, signal); }
}
