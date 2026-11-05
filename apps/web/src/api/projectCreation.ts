import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";
import type { ProjectOperation } from "./projectOperations.ts";

export type CreationPreview = components["schemas"]["ProjectCreationPreviewResponse"];
export type CreationRequest = components["schemas"]["ProjectCreationApplyRequest"];

function json(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value) as unknown; } catch { return undefined; }
}

export async function previewProjectCreation({ organizationId, intent, csrfToken, signal }: {
  organizationId: string; intent: string; csrfToken: string; signal: AbortSignal;
}): Promise<CreationPreview> {
  const context = "POST /api/v1/project-creations/preview";
  try {
    const { data, error, response } = await createCairnClient({ baseUrl: apiOrigins.identity }).POST("/api/v1/project-creations/preview", {
      params: { header: { "X-CSRF-Token": csrfToken } }, body: { intent }, parseAs: "text", signal,
    });
    if (response.status !== 200) throw knowledgeResponseError(json(error), response, context);
    const value = json(data);
    if (!matchesComponentSchema("ProjectCreationPreviewResponse", value) || value.organizationId !== organizationId || value.intent !== intent
      || (value.suggestion.action !== null && value.suggestion.action.type !== "create_project")) throw knowledgeContractError(context);
    return value;
  } catch (error) { throw knowledgeRequestError(error, context, signal); }
}

export async function applyProjectCreation({ payload, csrfToken, signal }: {
  payload: CreationRequest; csrfToken: string; signal: AbortSignal;
}): Promise<ProjectOperation> {
  const context = "POST /api/v1/project-creations";
  try {
    const { data, error, response } = await createCairnClient({ baseUrl: apiOrigins.identity }).POST("/api/v1/project-creations", {
      params: { header: { "X-CSRF-Token": csrfToken } }, body: payload, parseAs: "text", signal,
    });
    if (response.status !== 200 && response.status !== 201) throw knowledgeResponseError(json(error), response, context);
    const value = json(data);
    if (!matchesComponentSchema("ProjectOperationResponse", value) || value.operationId !== payload.operationId
      || value.action.type !== "create_project" || value.result.id !== value.projectId) throw knowledgeContractError(context);
    return value;
  } catch (error) { throw knowledgeRequestError(error, context, signal); }
}

export async function fetchProjectCreation({ operationId, signal }: { operationId: string; signal: AbortSignal }): Promise<ProjectOperation> {
  const context = "GET /api/v1/project-creations/{operation_id}";
  try {
    const { data, error, response } = await createCairnClient({ baseUrl: apiOrigins.identity }).GET("/api/v1/project-creations/{operation_id}", {
      params: { path: { operation_id: operationId } }, parseAs: "text", signal,
    });
    if (response.status !== 200) throw knowledgeResponseError(json(error), response, context);
    const value = json(data);
    if (!matchesComponentSchema("ProjectOperationResponse", value) || value.operationId !== operationId
      || value.action.type !== "create_project" || value.result.id !== value.projectId) throw knowledgeContractError(context);
    return value;
  } catch (error) { throw knowledgeRequestError(error, context, signal); }
}
