import { createCairnClient, matchesComponentSchema } from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import type { KnowledgeResource } from "./knowledge.ts";
import {
  knowledgeContractError,
  knowledgeRequestError,
  knowledgeResponseError,
} from "./knowledgeRequest.ts";

function client() {
  return createCairnClient({ baseUrl: apiOrigins.identity });
}

function parseJsonBody(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return undefined;
  }
}

function validateResource(
  value: unknown,
  resourceId: string,
  context: string,
): KnowledgeResource {
  if (
    !matchesComponentSchema("KnowledgeResourceResponse", value) ||
    value.id !== resourceId
  ) throw knowledgeContractError(context);
  return value;
}

function operationRequestError(
  error: unknown,
  context: string,
  signal: AbortSignal,
): ApiError {
  if (signal.aborted) {
    return new ApiError("aborted", "请求已被取消", { context, cause: error });
  }
  return knowledgeRequestError(error, context, signal);
}

export async function fetchKnowledgeResource({ projectId, resourceId, signal }: {
  projectId: string;
  resourceId: string;
  signal: AbortSignal;
}): Promise<KnowledgeResource> {
  const context = "GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}";
  try {
    const { data, error, response } = await client().GET(
      "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
      {
        params: { path: { project_id: projectId, resource_id: resourceId } },
        parseAs: "text",
        signal,
      },
    );
    const parsedData = parseJsonBody(data);
    const parsedError = parseJsonBody(error);
    if (response.status !== 200) {
      if (response.status >= 200 && response.status < 300) throw knowledgeContractError(context);
      throw knowledgeResponseError(parsedError, response, context);
    }
    return validateResource(parsedData, resourceId, context);
  } catch (error) {
    throw knowledgeRequestError(error, context, signal);
  }
}

export async function retryKnowledgeResourceVersion({
  projectId,
  resourceId,
  versionId,
  csrfToken,
  signal,
}: {
  projectId: string;
  resourceId: string;
  versionId: string;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<KnowledgeResource> {
  const context =
    "POST /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/{version_id}/retry";
  try {
    const { data, error, response } = await client().POST(
      "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/{version_id}/retry",
      {
        params: {
          path: {
            project_id: projectId,
            resource_id: resourceId,
            version_id: versionId,
          },
          header: { "X-CSRF-Token": csrfToken },
        },
        parseAs: "text",
        signal,
      },
    );
    const parsedData = parseJsonBody(data);
    const parsedError = parseJsonBody(error);
    if (response.status !== 200) {
      if (response.status >= 200 && response.status < 300) {
        throw knowledgeContractError(context);
      }
      throw knowledgeResponseError(parsedError, response, context);
    }
    const resource = validateResource(parsedData, resourceId, context);
    if (resource.latestVersion?.id !== versionId) throw knowledgeContractError(context);
    return resource;
  } catch (error) {
    throw operationRequestError(error, context, signal);
  }
}

export async function deleteKnowledgeResource({
  projectId,
  resourceId,
  csrfToken,
  signal,
}: {
  projectId: string;
  resourceId: string;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<void> {
  const context = "DELETE /api/v1/projects/{project_id}/knowledge/resources/{resource_id}";
  try {
    const { error, response } = await client().DELETE(
      "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
      {
        params: {
          path: { project_id: projectId, resource_id: resourceId },
          header: { "X-CSRF-Token": csrfToken },
        },
        parseAs: "text",
        signal,
      },
    );
    if (response.status === 204) return;
    if (response.status >= 200 && response.status < 300) {
      throw knowledgeContractError(context);
    }
    throw knowledgeResponseError(parseJsonBody(error), response, context);
  } catch (error) {
    throw operationRequestError(error, context, signal);
  }
}
