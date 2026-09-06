import {
  createCairnClient,
  matchesComponentSchema,
  type components,
} from "@cairn/sdk";

import { apiOrigins } from "./config.ts";
import {
  knowledgeContractError,
  knowledgeRequestError,
  knowledgeResponseError,
} from "./knowledgeRequest.ts";

export type KnowledgeCapabilities = components["schemas"]["KnowledgeCapabilities"];
export type KnowledgeCitation = components["schemas"]["KnowledgeCitation"];
export type KnowledgeChunkContext = components["schemas"]["ChunkContextResponse"];
export type KnowledgeLocator = KnowledgeCitation["locator"];
export type KnowledgeResource = components["schemas"]["KnowledgeResourceResponse"];
export type KnowledgeResourcePage = components["schemas"]["KnowledgeResourcePage"];
export type KnowledgeSearchResponse = components["schemas"]["KnowledgeSearchResponse"];

function knowledgeClient() {
  return createCairnClient({ baseUrl: apiOrigins.identity });
}

export async function fetchKnowledgeChunkContext({
  projectId,
  resourceId,
  resourceVersionId,
  chunkId,
  signal,
}: {
  projectId: string;
  resourceId: string;
  resourceVersionId: string;
  chunkId: string;
  signal: AbortSignal;
}): Promise<KnowledgeChunkContext> {
  const context =
    "GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}";
  try {
    const { data, error, response } = await knowledgeClient().GET(
      "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}",
      {
        params: {
          path: {
            project_id: projectId,
            resource_id: resourceId,
            chunk_id: chunkId,
          },
        },
        signal,
      },
    );
    if (data === undefined) throw knowledgeResponseError(error, response, context);
    if (!matchesComponentSchema("ChunkContextResponse", data)) {
      throw knowledgeContractError(context);
    }
    if (
      data.resourceId !== resourceId ||
      data.resourceVersionId !== resourceVersionId ||
      data.hit.id !== chunkId
    ) {
      throw knowledgeContractError(context);
    }
    return data;
  } catch (error) {
    throw knowledgeRequestError(error, context, signal);
  }
}

export function buildKnowledgeDownloadUrl(projectId: string, resourceId: string): string {
  const base = apiOrigins.identity.endsWith("/")
    ? apiOrigins.identity
    : `${apiOrigins.identity}/`;
  const path = [
    "api",
    "v1",
    "projects",
    encodeURIComponent(projectId),
    "knowledge",
    "resources",
    encodeURIComponent(resourceId),
    "download",
  ].join("/");
  return new URL(path, base).toString();
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
    if (data === undefined) throw knowledgeResponseError(error, response, context);
    if (matchesComponentSchema("KnowledgeResourcePage", data)) return data;
    throw knowledgeContractError(context);
  } catch (error) {
    throw knowledgeRequestError(error, context, signal);
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
    if (data === undefined) throw knowledgeResponseError(error, response, context);
    if (matchesComponentSchema("KnowledgeSearchResponse", data)) return data;
    throw knowledgeContractError(context);
  } catch (error) {
    throw knowledgeRequestError(error, context, signal);
  }
}
