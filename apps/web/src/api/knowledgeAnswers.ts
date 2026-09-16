import {
  createCairnClient,
  matchesComponentSchema,
  type components,
} from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import {
  knowledgeContractError,
  knowledgeRequestError,
  knowledgeResponseError,
} from "./knowledgeRequest.ts";

export type KnowledgeAnswerResponse = components["schemas"]["KnowledgeAnswerResponse"];
export type KnowledgeAnswerCitation = components["schemas"]["KnowledgeAnswerCitation"];

function client() {
  return createCairnClient({ baseUrl: apiOrigins.identity });
}

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return undefined;
  }
}

function hasValidAnswerInvariants(value: KnowledgeAnswerResponse): boolean {
  if (value.status === "insufficient_evidence") {
    return value.paragraphs.length === 0 && value.citations.length === 0;
  }
  if (value.paragraphs.length === 0 || value.citations.length === 0) return false;
  const ids = value.citations.map((citation) => citation.id);
  if (new Set(ids).size !== ids.length) return false;
  const known = new Set(ids);
  return value.paragraphs.every((paragraph) =>
    paragraph.citationIds.length > 0 &&
    new Set(paragraph.citationIds).size === paragraph.citationIds.length &&
    paragraph.citationIds.every((id) => known.has(id))
  );
}

export async function answerKnowledge({
  projectId,
  question,
  csrfToken,
  signal,
}: {
  projectId: string;
  question: string;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<KnowledgeAnswerResponse> {
  const context = "POST /api/v1/projects/{project_id}/knowledge/answers";
  try {
    const { data, error, response } = await client().POST(
      "/api/v1/projects/{project_id}/knowledge/answers",
      {
        params: {
          path: { project_id: projectId },
          header: { "X-CSRF-Token": csrfToken },
        },
        body: { question },
        parseAs: "text",
        signal,
      },
    );
    const parsedData = parseJson(data);
    if (response.status !== 200) {
      throw knowledgeResponseError(parseJson(error), response, context);
    }
    if (
      matchesComponentSchema("KnowledgeAnswerResponse", parsedData) &&
      hasValidAnswerInvariants(parsedData)
    ) return parsedData;
    throw knowledgeContractError(context);
  } catch (error) {
    if (signal.aborted) {
      throw new ApiError("aborted", "请求已被取消", { context, cause: error });
    }
    throw knowledgeRequestError(error, context, signal);
  }
}
