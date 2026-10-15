import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { consumeConversationStream, type StreamParagraph } from "./conversationStreaming.ts";
import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { hasValidAnswerInvariants } from "./knowledgeAnswers.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";

export type KnowledgeConversation = components["schemas"]["KnowledgeConversationResponse"];
export type KnowledgeConversationSummary = components["schemas"]["KnowledgeConversationSummary"];
export type KnowledgeConversationPage = components["schemas"]["KnowledgeConversationPage"];
export type KnowledgeAnswerModelStatus = components["schemas"]["KnowledgeAnswerModelStatus"];
type Scope = { projectId: string; signal: AbortSignal };
type DetailRequest = Scope & { conversationId: string };
type CreateRequest = Scope & { id: string; csrfToken: string };
type TurnRequest = DetailRequest & { id: string; expectedRevision: number; question: string; csrfToken: string; assistantRevision?: number; skillId?: string | null };
const client = () => createCairnClient({ baseUrl: apiOrigins.identity });
export const isConversationId = (value: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
function parse(value: unknown): unknown { try { return typeof value === "string" ? JSON.parse(value) as unknown : value; } catch { return undefined; } }

function validDetail(value: KnowledgeConversation): boolean {
  return isConversationId(value.id) && value.revision === value.turns.length + 1 &&
    new Set(value.turns.map(turn => turn.id)).size === value.turns.length &&
    value.turns.every((turn, index) => isConversationId(turn.id) && turn.sequence === index + 1 &&
      turn.answerUnavailable === (turn.answer === null) &&
      (turn.answer === null || hasValidAnswerInvariants(turn.answer)));
}
async function request<T>(signal: AbortSignal, context: string, operation: () => Promise<{ data?: unknown; error?: unknown; response: Response }>, statuses: number[], validate: (value: unknown) => value is T): Promise<T> {
  try {
    signal.throwIfAborted();
    const { data, error, response } = await operation();
    signal.throwIfAborted();
    if (!statuses.includes(response.status)) throw knowledgeResponseError(parse(error), response, context);
    const value = parse(data);
    if (!validate(value)) throw knowledgeContractError(context);
    return value;
  } catch (error) {
    if (signal.aborted) throw new ApiError("aborted", "请求已被取消", { context, cause: error });
    throw knowledgeRequestError(error, context, signal);
  }
}
const detailValidator = (id: string) => (value: unknown): value is KnowledgeConversation =>
  matchesComponentSchema("KnowledgeConversationResponse", value) && value.id === id && validDetail(value);

export function fetchKnowledgeConversation({ projectId, conversationId, signal }: DetailRequest) {
  return request(signal, "GET conversation", () => client().GET("/api/v1/projects/{project_id}/knowledge/conversations/{conversation_id}", { params: { path: { project_id: projectId, conversation_id: conversationId } }, signal, parseAs: "text" }), [200], detailValidator(conversationId));
}
export function createKnowledgeConversation({ projectId, id, csrfToken, signal }: CreateRequest) {
  return request(signal, "POST conversation", () => client().POST("/api/v1/projects/{project_id}/knowledge/conversations", { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, body: { id }, signal, parseAs: "text" }), [200, 201], detailValidator(id));
}
export function appendKnowledgeConversationTurn({ projectId, conversationId, id, expectedRevision, question, csrfToken, signal, assistantRevision = 0, skillId = null }: TurnRequest) {
  return request(signal, "POST conversation turn", () => client().POST("/api/v1/projects/{project_id}/knowledge/conversations/{conversation_id}/turns", { params: { path: { project_id: projectId, conversation_id: conversationId }, header: { "X-CSRF-Token": csrfToken } }, body: { id, expectedRevision, question, assistantRevision, skillId }, signal, parseAs: "text" }), [200], (value): value is KnowledgeConversation => detailValidator(conversationId)(value) && value.turns.some(turn => turn.id === id && turn.question === question && (turn.assistantRevision ?? 0) === assistantRevision && (turn.skillId ?? null) === skillId));
}
export function fetchKnowledgeConversations({ projectId, cursor, signal }: Scope & { cursor: string | null }) {
  return request(signal, "GET conversations", () => client().GET("/api/v1/projects/{project_id}/knowledge/conversations", { params: { path: { project_id: projectId }, query: { limit: 20, ...(cursor === null ? {} : { cursor }) } }, signal, parseAs: "text" }), [200], (value): value is KnowledgeConversationPage => matchesComponentSchema("KnowledgeConversationPage", value) && value.items.every(item => isConversationId(item.id)) && new Set(value.items.map(item => item.id)).size === value.items.length);
}
export function fetchKnowledgeAnswerModel({ projectId, signal }: Scope) {
  return request(signal, "GET answer model", () => client().GET("/api/v1/projects/{project_id}/knowledge/answer-model", { params: { path: { project_id: projectId } }, signal, parseAs: "text" }), [200], (value): value is KnowledgeAnswerModelStatus => matchesComponentSchema("KnowledgeAnswerModelStatus", value));
}


export async function streamKnowledgeConversationTurn({ projectId, conversationId, id, expectedRevision, question, csrfToken, signal, assistantRevision = 0, skillId = null, onParagraph }: TurnRequest & { onParagraph(paragraph: StreamParagraph): void }): Promise<KnowledgeConversation> {
  const context = "POST conversation stream";
  try {
    signal.throwIfAborted();
    const response = await fetch(new Request(`${apiOrigins.identity}/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/conversations/${encodeURIComponent(conversationId)}/turns/stream`, {
      method: "POST", credentials: "include", signal,
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ id, expectedRevision, question, assistantRevision, skillId }),
    }));
    signal.throwIfAborted();
    if (response.status !== 200) {
      const text = await response.text();
      signal.throwIfAborted();
      throw knowledgeResponseError(parse(text), response, context);
    }
    return await consumeConversationStream(response, { conversationId, turnId: id, signal, onParagraph,
      validateComplete: value => detailValidator(conversationId)(value) && value.turns.some(turn => turn.id === id && turn.question === question && (turn.assistantRevision ?? 0) === assistantRevision && (turn.skillId ?? null) === skillId),
    });
  } catch (error) {
    if (signal.aborted) throw new ApiError("aborted", "请求已被取消", { context, cause: error });
    throw knowledgeRequestError(error, context, signal);
  }
}
