import {
  createCairnClient,
  matchesComponentSchema,
  type components,
} from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { parseApiErrorResponse } from "./parseApiErrorResponse.ts";

export type KnowledgeCapabilities = components["schemas"]["KnowledgeCapabilities"];
export type KnowledgeResource = components["schemas"]["KnowledgeResourceResponse"];
export type KnowledgeResourcePage = components["schemas"]["KnowledgeResourcePage"];
export type KnowledgeSearchResponse = components["schemas"]["KnowledgeSearchResponse"];

function knowledgeClient() {
  return createCairnClient({ baseUrl: apiOrigins.identity });
}

function contractError(context: string): ApiError {
  console.error(`[contract] ${context} 响应不符合生成的 OpenAPI 契约`);
  return new ApiError("contract", "服务器返回的数据格式不正确，请联系管理员", {
    context,
  });
}

function retryAfterSeconds(response: Response): number | null {
  const value = response.headers.get("Retry-After");
  if (value === null || !/^\d+$/.test(value)) return null;
  const seconds = Number(value);
  return Number.isSafeInteger(seconds) ? seconds : null;
}

function responseError(error: unknown, response: Response, context: string): ApiError {
  const detail = parseApiErrorResponse(error, {
    message: `服务器返回 ${response.status}`,
    code: "http_error",
    traceId: response.headers.get("X-Request-ID"),
  });
  return new ApiError("http", detail.message, {
    status: response.status,
    code: detail.code,
    traceId: detail.traceId,
    retryAfterSeconds: retryAfterSeconds(response),
    context,
  });
}

function requestError(error: unknown, context: string, signal: AbortSignal): ApiError {
  if (error instanceof ApiError) return error;
  if (signal.aborted) {
    return new ApiError("aborted", "请求已被取消", { context, cause: error });
  }
  return new ApiError("network", "无法连接服务器，请检查网络", {
    context,
    cause: error,
  });
}

export async function fetchKnowledgeResources({
  projectId,
  cursor,
  signal,
}: {
  projectId: string;
  cursor: string | null;
  signal: AbortSignal;
}): Promise<KnowledgeResourcePage> {
  const context = "GET /api/v1/projects/{project_id}/knowledge/resources";
  try {
    const { data, error, response } = await knowledgeClient().GET(
      "/api/v1/projects/{project_id}/knowledge/resources",
      {
        params: {
          path: { project_id: projectId },
          query: cursor === null ? {} : { cursor },
        },
        signal,
      },
    );
    if (data === undefined) throw responseError(error, response, context);
    if (matchesComponentSchema("KnowledgeResourcePage", data)) return data;
    throw contractError(context);
  } catch (error) {
    throw requestError(error, context, signal);
  }
}

export async function searchKnowledge({
  projectId,
  query,
  limit,
  csrfToken,
  signal,
}: {
  projectId: string;
  query: string;
  limit: number;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<KnowledgeSearchResponse> {
  const context = "POST /api/v1/projects/{project_id}/knowledge/search";
  try {
    const { data, error, response } = await knowledgeClient().POST(
      "/api/v1/projects/{project_id}/knowledge/search",
      {
        params: {
          path: { project_id: projectId },
          header: { "X-CSRF-Token": csrfToken },
        },
        body: { query, limit },
        signal,
      },
    );
    if (data === undefined) throw responseError(error, response, context);
    if (matchesComponentSchema("KnowledgeSearchResponse", data)) return data;
    throw contractError(context);
  } catch (error) {
    throw requestError(error, context, signal);
  }
}
