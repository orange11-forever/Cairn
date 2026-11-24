import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";
import type { OperationPage, ProjectOperation } from "./projectOperations.ts";

export type DialogueAgent = components["schemas"]["AgentDialogueContext"];
export type DialoguePreview = components["schemas"]["AgentDialoguePreviewResponse"];
export type DialogueRequest = components["schemas"]["AgentDialogueApplyRequest"];
const client = () => createCairnClient({ baseUrl: apiOrigins.identity });
const json = (value: unknown): unknown => { try { return typeof value === "string" ? JSON.parse(value) as unknown : value; } catch { return undefined; } };
async function checked<T>(signal: AbortSignal, context: string, operation: () => Promise<{data?: unknown; error?: unknown; response: Response}>, statuses: number[], valid: (value: unknown) => value is T): Promise<T> {
  try {
    const { data, error, response } = await operation();
    if (!statuses.includes(response.status)) throw knowledgeResponseError(json(error), response, context);
    const value = json(data);
    if (!valid(value)) throw knowledgeContractError(context);
    return value;
  } catch (error) { throw knowledgeRequestError(error, context, signal); }
}
const query = (agent: DialogueAgent) => ({ origin_project_id: agent.originProjectId, assistant_id: agent.assistantId ?? undefined });
export function previewAgentDialogue({ agent, targetProjectId, intent, history, csrfToken, signal }: {history: {role: "user" | "assistant"; text: string}[]; agent: DialogueAgent; targetProjectId: string; intent: string; csrfToken: string; signal: AbortSignal}) {
  return checked(signal, "POST agent dialogue preview", () => client().POST("/api/v1/agent-dialogue/preview", {
    body: {agent, targetProjectId, intent, history}, params: {header: {"X-CSRF-Token": csrfToken}}, signal, parseAs: "text",
  }), [200], (value): value is DialoguePreview => matchesComponentSchema("AgentDialoguePreviewResponse", value)
    && value.agent.originProjectId === agent.originProjectId && value.agent.assistantId === agent.assistantId
    && value.targetProjectId === targetProjectId && value.preview.intent === intent);
}
export function applyAgentDialogue({payload, csrfToken, signal}: {payload: DialogueRequest; csrfToken: string; signal: AbortSignal}) {
  return checked(signal, "POST agent dialogue operation", () => client().POST("/api/v1/agent-dialogue/operations", {
    body: payload, params: {header: {"X-CSRF-Token": csrfToken}}, signal, parseAs: "text",
  }), [200, 201], (value): value is ProjectOperation => matchesComponentSchema("ProjectOperationResponse", value)
    && value.operationId === payload.operationId && (value.action.type === "create_project" ? value.result.id === value.projectId : value.projectId === payload.preview.targetProjectId));
}
export function fetchAgentDialogueOperation({agent, targetProjectId, operationId, signal}: {agent: DialogueAgent; targetProjectId: string; operationId: string; signal: AbortSignal}) {
  return checked(signal, "GET agent dialogue operation", () => client().GET("/api/v1/agent-dialogue/operations/{operation_id}", {
    params: {path: {operation_id: operationId}, query: {...query(agent), target_project_id: targetProjectId}}, signal, parseAs: "text",
  }), [200], (value): value is ProjectOperation => matchesComponentSchema("ProjectOperationResponse", value) && value.operationId === operationId && (value.action.type === "create_project" || value.projectId === targetProjectId));
}
export function fetchAgentDialogueOperations({agent, targetProjectId, cursor, signal}: {agent: DialogueAgent; targetProjectId: string; cursor: string | null; signal: AbortSignal}) {
  return checked(signal, "GET agent dialogue operations", () => client().GET("/api/v1/agent-dialogue/operations", {
    params: {query: {...query(agent), target_project_id: targetProjectId, cursor: cursor ?? undefined, limit: 10}}, signal, parseAs: "text",
  }), [200], (value): value is OperationPage => matchesComponentSchema("ProjectOperationPage", value) && value.items.every(item => item.projectId === targetProjectId));
}
