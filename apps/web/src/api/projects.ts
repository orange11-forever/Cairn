import {
  createCairnClient,
  matchesComponentSchema,
  type components,
} from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { parseApiErrorResponse } from "./parseApiErrorResponse.ts";

export type Project = components["schemas"]["ProjectResponse"];
export type ProjectPage = components["schemas"]["ProjectPage"];
export type Task = components["schemas"]["TaskResponse"];
export type TaskPage = components["schemas"]["TaskPage"];
export type TaskStatus = components["schemas"]["TaskStatus"];

function projectsClient() {
  return createCairnClient({ baseUrl: apiOrigins.identity });
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
    context,
  });
}

function contractError(context: string): ApiError {
  console.error(`[contract] ${context} 响应不符合生成的 OpenAPI 契约`);
  return new ApiError("contract", "服务器返回的数据格式不正确，请联系管理员", {
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

export async function fetchProjects({
  cursor,
  signal,
}: {
  cursor: string | null;
  signal: AbortSignal;
}): Promise<ProjectPage> {
  const context = "GET /api/v1/projects";
  try {
    const { data, error, response } = await projectsClient().GET("/api/v1/projects", {
      params: { query: cursor === null ? {} : { cursor } },
      signal,
    });
    if (data !== undefined) {
      if (matchesComponentSchema("ProjectPage", data)) return data;
      throw contractError(context);
    }
    throw responseError(error, response, context);
  } catch (error) {
    throw requestError(error, context, signal);
  }
}

export async function fetchProjectTasks(
  {
    projectId,
    cursor,
    signal,
  }: {
    projectId: string;
    cursor: string | null;
    signal: AbortSignal;
  },
): Promise<TaskPage> {
  const context = "GET /api/v1/projects/{project_id}/tasks";
  try {
    const { data, error, response } = await projectsClient().GET(
      "/api/v1/projects/{project_id}/tasks",
      {
        params: {
          path: { project_id: projectId },
          query: cursor === null ? {} : { cursor },
        },
        signal,
      },
    );
    if (data !== undefined) {
      if (matchesComponentSchema("TaskPage", data)) return data;
      throw contractError(context);
    }
    throw responseError(error, response, context);
  } catch (error) {
    throw requestError(error, context, signal);
  }
}

export async function transitionTaskStatus({
  taskId,
  status,
  csrfToken,
  signal,
}: {
  taskId: string;
  status: TaskStatus;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<Task> {
  const context = "PATCH /api/v1/tasks/{task_id}/status";
  try {
    const { data, error, response } = await projectsClient().PATCH(
      "/api/v1/tasks/{task_id}/status",
      {
        params: {
          path: { task_id: taskId },
          header: { "X-CSRF-Token": csrfToken },
        },
        body: { status },
        signal,
      },
    );
    if (data !== undefined) {
      if (matchesComponentSchema("TaskResponse", data)) return data;
      throw contractError(context);
    }
    const apiError = responseError(error, response, context);
    if (apiError.status === 404 && apiError.code === "not_found") {
      throw new ApiError(
        "http",
        "项目不存在或你已失去编辑权限，请刷新项目列表",
        {
          status: apiError.status,
          code: apiError.code,
          traceId: apiError.traceId,
          context: apiError.context,
        },
      );
    }
    throw apiError;
  } catch (error) {
    throw requestError(error, context, signal);
  }
}
