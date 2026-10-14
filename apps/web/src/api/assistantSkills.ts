import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { ApiError } from "./errors.ts";
import { apiOrigins } from "./config.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";

export type AssistantSettings = components["schemas"]["AssistantSettingsResponse"];
export type AssistantSettingsInput = components["schemas"]["AssistantSettingsRequest"];
export type AssistantCatalog = components["schemas"]["AssistantCatalogResponse"];
export type SkillCatalog = components["schemas"]["KnowledgeSkillCatalogResponse"];
export type SkillPreview = components["schemas"]["KnowledgeSkillPreview"];
export type SkillImportInput = components["schemas"]["SkillImportRequest"];
export type SkillSource = SkillImportInput["source"];
export type ImportedSkill = components["schemas"]["KnowledgeSkillImportResponse"];
type Scope = { projectId: string; signal: AbortSignal };
const client = () => createCairnClient({ baseUrl: apiOrigins.identity });
const parse = (value: unknown): unknown => { try { return typeof value === "string" ? JSON.parse(value) as unknown : value; } catch { return undefined; } };
async function checked<T>(signal: AbortSignal, context: string, operation: () => Promise<{ data?: unknown; error?: unknown; response: Response }>, statuses: number[], valid: (value: unknown) => value is T): Promise<T> {
  try {
    signal.throwIfAborted(); const result = await operation(); signal.throwIfAborted();
    if (!statuses.includes(result.response.status)) throw knowledgeResponseError(parse(result.error), result.response, context);
    const value = parse(result.data); if (!valid(value)) throw knowledgeContractError(context); return value;
  } catch (error) { if (signal.aborted) throw new ApiError("aborted", "请求已取消", { cause: error }); throw knowledgeRequestError(error, context, signal); }
}
export function fetchAssistantSettings({ projectId, signal }: Scope) {
  return checked(signal, "GET assistant settings", () => client().GET("/api/v1/projects/{project_id}/knowledge/assistant-settings", { params: { path: { project_id: projectId } }, signal, parseAs: "text" }), [200], (value): value is AssistantSettings => matchesComponentSchema("AssistantSettingsResponse", value) && new Set(value.enabledSkillIds).size === value.enabledSkillIds.length);
}
export function fetchAssistants({ projectId, signal }: Scope) {
  return checked(signal, "GET assistants", () => client().GET("/api/v1/projects/{project_id}/knowledge/assistants", { params: { path: { project_id: projectId } }, signal, parseAs: "text" }), [200], (value): value is AssistantCatalog => matchesComponentSchema("AssistantCatalogResponse", value) && new Set(value.items.map(item => item.id)).size === value.items.length);
}
export function createAssistant({ projectId, signal, csrfToken, body }: Scope & { csrfToken: string; body: AssistantSettingsInput }) {
  return checked(signal, "POST assistant", () => client().POST("/api/v1/projects/{project_id}/knowledge/assistants", { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, body, signal, parseAs: "text" }), [201], (value): value is AssistantSettings => matchesComponentSchema("AssistantSettingsResponse", value) && typeof value.id === "string" && value.name === body.name.trim() && value.instructions === body.instructions && (value.modelId ?? null) === (body.modelId ?? null) && value.revision === body.expectedRevision + 1 && JSON.stringify(value.enabledSkillIds) === JSON.stringify(body.enabledSkillIds));
}
export function selectAssistant({ projectId, assistantId, expectedRevision, signal, csrfToken }: Scope & { assistantId: string; expectedRevision: number; csrfToken: string }) {
  return checked(signal, "POST select assistant", () => client().POST("/api/v1/projects/{project_id}/knowledge/assistants/{assistant_id}/select", { params: { path: { project_id: projectId, assistant_id: assistantId }, header: { "X-CSRF-Token": csrfToken } }, body: { expectedRevision }, signal, parseAs: "text" }), [200], (value): value is AssistantSettings => matchesComponentSchema("AssistantSettingsResponse", value) && value.id === assistantId && value.revision >= expectedRevision && value.revision <= expectedRevision + 1);
}
export function saveAssistantSettings({ projectId, signal, csrfToken, body }: Scope & { csrfToken: string; body: AssistantSettingsInput }) {
  return checked(signal, "PUT assistant settings", () => client().PUT("/api/v1/projects/{project_id}/knowledge/assistant-settings", { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, body, signal, parseAs: "text" }), [200], (value): value is AssistantSettings => matchesComponentSchema("AssistantSettingsResponse", value) && value.name === body.name.trim() && value.instructions === body.instructions && (value.modelId ?? null) === (body.modelId ?? null) && value.revision >= body.expectedRevision && value.revision <= body.expectedRevision + 1 && JSON.stringify(value.enabledSkillIds) === JSON.stringify(body.enabledSkillIds));
}
export function fetchSkillCatalog({ projectId, signal }: Scope) {
  return checked(signal, "GET skills", () => client().GET("/api/v1/projects/{project_id}/knowledge/skills", { params: { path: { project_id: projectId } }, signal, parseAs: "text" }), [200], (value): value is SkillCatalog => matchesComponentSchema("KnowledgeSkillCatalogResponse", value) && new Set(value.items.map(item => item.id)).size === value.items.length);
}
export function previewSkill({ projectId, signal, csrfToken, source }: Scope & { csrfToken: string; source: SkillSource }) {
  return checked(signal, "POST skill preview", () => client().POST("/api/v1/projects/{project_id}/knowledge/skills/preview", { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, body: { source }, signal, parseAs: "text" }), [200], (value): value is SkillPreview => matchesComponentSchema("KnowledgeSkillPreview", value) && /^[a-f0-9]{64}$/.test(value.digest));
}
export function importSkill({ projectId, signal, csrfToken, body }: Scope & { csrfToken: string; body: SkillImportInput }) {
  return checked(signal, "POST skill import", () => client().POST("/api/v1/projects/{project_id}/knowledge/skills/import", { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, body, signal, parseAs: "text" }), [200, 201], (value): value is ImportedSkill => matchesComponentSchema("KnowledgeSkillImportResponse", value) && value.id === body.id && value.digest === body.expectedDigest);
}
