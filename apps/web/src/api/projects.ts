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

function responseError(
  error: unknown,
  response: Response,
  context: string,
): ApiError {
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

function requestError(
  error: unknown,
  context: string,
  signal: AbortSignal,
): ApiError {
  if (signal.aborted) {
    return new ApiError("aborted", "请求已被取消", { context, cause: error });
  }
  if (error instanceof ApiError) return error;
  return new ApiError("network", "无法连接服务器，请检查网络", {
    context,
    cause: error,
  });
}

function parseJsonBody(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return undefined;
  }
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
    const { data, error, response } = await projectsClient().GET(
      "/api/v1/projects",
      {
        params: { query: cursor === null ? {} : { cursor } },
        signal,
      },
    );
    if (data !== undefined) {
      if (matchesComponentSchema("ProjectPage", data)) return data;
      throw contractError(context);
    }
    throw responseError(error, response, context);
  } catch (error) {
    throw requestError(error, context, signal);
  }
}

export async function fetchProject({
  projectId,
  signal,
}: {
  projectId: string;
  signal: AbortSignal;
}): Promise<Project> {
  const context = "GET /api/v1/projects/{project_id}";
  try {
    const { data, error, response } = await projectsClient().GET(
      "/api/v1/projects/{project_id}",
      { params: { path: { project_id: projectId } }, parseAs: "text", signal },
    );
    const parsedData = parseJsonBody(data);
    if (response.ok) {
      if (
        response.status === 200 &&
        matchesComponentSchema("ProjectResponse", parsedData) &&
        parsedData.id.toLowerCase() === projectId.toLowerCase()
      )
        return parsedData;
      throw contractError(context);
    }
    throw responseError(parseJsonBody(error), response, context);
  } catch (error) {
    throw requestError(error, context, signal);
  }
}

export async function fetchProjectTasks({
  projectId,
  cursor,
  signal,
}: {
  projectId: string;
  cursor: string | null;
  signal: AbortSignal;
}): Promise<TaskPage> {
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
  expectedRevision,
  csrfToken,
  signal,
}: {
  taskId: string;
  status: TaskStatus;
  expectedRevision?: number;
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
        body: {
          status,
          ...(expectedRevision === undefined ? {} : { expectedRevision }),
        },
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

export type TaskCreate = components["schemas"]["TaskCreateRequest"];
export type TaskUpdate = components["schemas"]["TaskUpdateRequest"];
export type AssigneePage = components["schemas"]["AssigneePage"];
export type DependencyPage = components["schemas"]["DependencyPage"];
export type Dependency = components["schemas"]["DependencyResponse"];

async function taskRequest<T>(
  context: string,
  signal: AbortSignal,
  send: () => Promise<{ data?: unknown; error?: unknown; response: Response }>,
  valid: (data: unknown) => data is T,
  status = 200,
): Promise<T> {
  try {
    const { data, error, response } = await send();
    const parsedData = parseJsonBody(data);
    if (response.ok) {
      if (response.status === status && valid(parsedData)) return parsedData;
      throw contractError(context);
    }
    throw responseError(parseJsonBody(error), response, context);
  } catch (error) {
    throw requestError(error, context, signal);
  }
}

export function fetchTask({
  taskId,
  projectId,
  signal,
}: {
  taskId: string;
  projectId: string;
  signal: AbortSignal;
}): Promise<Task> {
  return taskRequest(
    "GET task",
    signal,
    () =>
      projectsClient().GET("/api/v1/tasks/{task_id}", {
        params: { path: { task_id: taskId } },
        signal,
      }),
    (data): data is Task =>
      matchesComponentSchema("TaskResponse", data) &&
      data.id === taskId &&
      data.projectId === projectId,
  );
}

export function createTask({
  projectId,
  body,
  csrfToken,
  signal,
}: {
  projectId: string;
  body: TaskCreate;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<Task> {
  return taskRequest(
    "POST task",
    signal,
    () =>
      projectsClient().POST("/api/v1/projects/{project_id}/tasks", {
        params: {
          path: { project_id: projectId },
          header: { "X-CSRF-Token": csrfToken },
        },
        body,
        signal,
      }),
    (data): data is Task =>
      matchesComponentSchema("TaskResponse", data) &&
      data.projectId === projectId,
    201,
  );
}

export function updateTask({
  taskId,
  projectId,
  body,
  csrfToken,
  signal,
}: {
  taskId: string;
  projectId: string;
  body: TaskUpdate;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<Task> {
  return taskRequest(
    "PATCH task",
    signal,
    () =>
      projectsClient().PATCH("/api/v1/tasks/{task_id}", {
        params: {
          path: { task_id: taskId },
          header: { "X-CSRF-Token": csrfToken },
        },
        body,
        signal,
      }),
    (data): data is Task =>
      matchesComponentSchema("TaskResponse", data) &&
      data.id === taskId &&
      data.projectId === projectId,
  );
}

export function fetchAssignees({
  projectId,
  cursor,
  signal,
}: {
  projectId: string;
  cursor: string | null;
  signal: AbortSignal;
}): Promise<AssigneePage> {
  return taskRequest(
    "GET assignees",
    signal,
    () =>
      projectsClient().GET("/api/v1/projects/{project_id}/assignees", {
        params: {
          path: { project_id: projectId },
          query: cursor === null ? {} : { cursor },
        },
        signal,
      }),
    (data): data is AssigneePage =>
      matchesComponentSchema("AssigneePage", data),
  );
}

export function fetchDependencies({
  taskId,
  cursor,
  signal,
}: {
  taskId: string;
  cursor: string | null;
  signal: AbortSignal;
}): Promise<DependencyPage> {
  return taskRequest(
    "GET dependencies",
    signal,
    () =>
      projectsClient().GET("/api/v1/tasks/{task_id}/dependencies", {
        params: {
          path: { task_id: taskId },
          query: cursor === null ? {} : { cursor },
        },
        signal,
      }),
    (data): data is DependencyPage =>
      matchesComponentSchema("DependencyPage", data) &&
      data.items.every((edge) => edge.successorTaskId === taskId),
  );
}

export function addTaskDependency({
  taskId,
  predecessorTaskId,
  expectedRevision,
  csrfToken,
  signal,
}: {
  taskId: string;
  predecessorTaskId: string;
  expectedRevision: number;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<Dependency> {
  return taskRequest(
    "POST dependency",
    signal,
    () =>
      projectsClient().POST("/api/v1/tasks/{task_id}/dependencies", {
        params: {
          path: { task_id: taskId },
          header: { "X-CSRF-Token": csrfToken },
        },
        body: { predecessorTaskId, expectedRevision },
        signal,
      }),
    (data): data is Dependency =>
      matchesComponentSchema("DependencyResponse", data) &&
      data.successorTaskId === taskId &&
      data.predecessorTaskId === predecessorTaskId,
    201,
  );
}

export async function deleteTaskDependency({
  taskId,
  dependencyId,
  expectedRevision,
  csrfToken,
  signal,
}: {
  taskId: string;
  dependencyId: string;
  expectedRevision: number;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<void> {
  try {
    const { error, response } = await projectsClient().DELETE(
      "/api/v1/tasks/{task_id}/dependencies/{dependency_id}",
      {
        params: {
          path: { task_id: taskId, dependency_id: dependencyId },
          query: { expectedRevision },
          header: { "X-CSRF-Token": csrfToken },
        },
        signal,
      },
    );
    if (response.status !== 204)
      throw responseError(error, response, "DELETE dependency");
  } catch (error) {
    throw requestError(error, "DELETE dependency", signal);
  }
}

export type Stage = components["schemas"]["StageResponse"];
export type StagePage = components["schemas"]["StagePage"];
export type StageCreate = components["schemas"]["StageCreateRequest"];
export type StageUpdate = components["schemas"]["StageUpdateRequest"];
export function fetchStages({
  projectId,
  cursor,
  signal
}: {
  projectId: string;
  cursor: string | null;
  signal: AbortSignal;
}): Promise<StagePage> {
  return taskRequest("GET stages", signal, () => projectsClient().GET("/api/v1/projects/{project_id}/stages", {
    params: {
      path: {
        project_id: projectId
      },
      query: cursor === null ? {} : {
        cursor
      }
    },
    signal,
    parseAs: "text"
  }), (data): data is StagePage => matchesComponentSchema("StagePage", data) && data.items.every(item => item.projectId === projectId));
}
export function createStage({
  projectId,
  body,
  csrfToken,
  signal
}: {
  projectId: string;
  body: StageCreate;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<Stage> {
  return taskRequest("POST stages", signal, () => projectsClient().POST("/api/v1/projects/{project_id}/stages", {
    params: {
      path: {
        project_id: projectId
      },
      header: {
        "X-CSRF-Token": csrfToken
      }
    },
    body,
    signal,
    parseAs: "text"
  }), (data): data is Stage => matchesComponentSchema("StageResponse", data) && data.projectId === projectId, 201);
}
export function updateStage({
  projectId,
  objectId,
  body,
  csrfToken,
  signal
}: {
  projectId: string;
  objectId: string;
  body: StageUpdate;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<Stage> {
  return taskRequest("PATCH stages", signal, () => projectsClient().PATCH("/api/v1/projects/{project_id}/stages/{stage_id}", {
    params: {
      path: {
        project_id: projectId,
        stage_id: objectId
      },
      header: {
        "X-CSRF-Token": csrfToken
      }
    },
    body,
    signal,
    parseAs: "text"
  }), (data): data is Stage => matchesComponentSchema("StageResponse", data) && data.projectId === projectId && data.id === objectId);
}
export type Milestone = components["schemas"]["MilestoneResponse"];
export type MilestonePage = components["schemas"]["MilestonePage"];
export type MilestoneCreate = components["schemas"]["MilestoneCreateRequest"];
export type MilestoneUpdate = components["schemas"]["MilestoneUpdateRequest"];
export function fetchMilestones({
  projectId,
  cursor,
  signal
}: {
  projectId: string;
  cursor: string | null;
  signal: AbortSignal;
}): Promise<MilestonePage> {
  return taskRequest("GET milestones", signal, () => projectsClient().GET("/api/v1/projects/{project_id}/milestones", {
    params: {
      path: {
        project_id: projectId
      },
      query: cursor === null ? {} : {
        cursor
      }
    },
    signal,
    parseAs: "text"
  }), (data): data is MilestonePage => matchesComponentSchema("MilestonePage", data) && data.items.every(item => item.projectId === projectId));
}
export function createMilestone({
  projectId,
  body,
  csrfToken,
  signal
}: {
  projectId: string;
  body: MilestoneCreate;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<Milestone> {
  return taskRequest("POST milestones", signal, () => projectsClient().POST("/api/v1/projects/{project_id}/milestones", {
    params: {
      path: {
        project_id: projectId
      },
      header: {
        "X-CSRF-Token": csrfToken
      }
    },
    body,
    signal,
    parseAs: "text"
  }), (data): data is Milestone => matchesComponentSchema("MilestoneResponse", data) && data.projectId === projectId, 201);
}
export function updateMilestone({
  projectId,
  objectId,
  body,
  csrfToken,
  signal
}: {
  projectId: string;
  objectId: string;
  body: MilestoneUpdate;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<Milestone> {
  return taskRequest("PATCH milestones", signal, () => projectsClient().PATCH("/api/v1/projects/{project_id}/milestones/{milestone_id}", {
    params: {
      path: {
        project_id: projectId,
        milestone_id: objectId
      },
      header: {
        "X-CSRF-Token": csrfToken
      }
    },
    body,
    signal,
    parseAs: "text"
  }), (data): data is Milestone => matchesComponentSchema("MilestoneResponse", data) && data.projectId === projectId && data.id === objectId);
}
