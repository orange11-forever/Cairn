import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";

export type ProjectAnalysisResponse = components["schemas"]["ProjectAnalysisResponse"];

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value) as unknown; } catch { return undefined; }
}

export async function analyzeProject({ projectId, csrfToken, signal }: {
  projectId: string; csrfToken: string; signal: AbortSignal;
}): Promise<ProjectAnalysisResponse> {
  const context = "POST /api/v1/projects/{project_id}/analysis";
  try {
    const { data, error, response } = await createCairnClient({ baseUrl: apiOrigins.identity }).POST(
      "/api/v1/projects/{project_id}/analysis",
      { params: { path: { project_id: projectId }, header: { "X-CSRF-Token": csrfToken } }, parseAs: "text", signal },
    );
    if (response.status !== 200) throw knowledgeResponseError(parseJson(error), response, context);
    const parsed = parseJson(data);
    if (!matchesComponentSchema("ProjectAnalysisResponse", parsed)) throw knowledgeContractError(context);
    const ids = parsed.citations.map(citation => citation.id);
    const known = new Set(["S1", ...ids]);
    if (
      parsed.projectId.toLowerCase() !== projectId.toLowerCase() ||
      parsed.snapshot.project.id.toLowerCase() !== projectId.toLowerCase() ||
      [...parsed.snapshot.tasks, ...parsed.snapshot.stages, ...parsed.snapshot.milestones]
        .some(item => item.projectId.toLowerCase() !== projectId.toLowerCase()) ||
      ids.includes("S1") || new Set(ids).size !== ids.length ||
      (parsed.status === "answered" ? parsed.paragraphs.length === 0 : parsed.paragraphs.length !== 0) ||
      parsed.paragraphs.some(paragraph =>
        new Set(paragraph.citationIds).size !== paragraph.citationIds.length ||
        paragraph.citationIds.some(id => !known.has(id)))
    ) throw knowledgeContractError(context);
    return parsed;
  } catch (error) {
    throw knowledgeRequestError(error, context, signal);
  }
}
