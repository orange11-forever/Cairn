import { createCairnClient, matchesComponentSchema, type components } from "@cairn/sdk";
import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import { knowledgeContractError, knowledgeRequestError, knowledgeResponseError } from "./knowledgeRequest.ts";

export type KnowledgeContent = components["schemas"]["KnowledgeContent"];
export interface KnowledgeContentRequest {
  projectId: string;
  resourceId: string;
  resourceVersionId?: string;
  chunkId?: string;
  signal: AbortSignal;
}

function json(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value) as unknown; } catch { return undefined; }
}

export async function fetchKnowledgeContent(request: KnowledgeContentRequest): Promise<KnowledgeContent> {
  const context = "GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content";
  try {
    if (request.signal.aborted) throw new ApiError("aborted", "请求已被取消", { context });
    const { data, error, response } = await createCairnClient({ baseUrl: apiOrigins.identity }).GET(
      "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content", {
        params: { path: { project_id: request.projectId, resource_id: request.resourceId },
          query: { version_id: request.resourceVersionId, chunk_id: request.chunkId } },
        parseAs: "text", signal: request.signal,
      },
    );
    if (request.signal.aborted) throw new ApiError("aborted", "请求已被取消", { context });
    if (response.status !== 200) {
      if (response.status >= 200 && response.status < 300) throw knowledgeContractError(context);
      throw knowledgeResponseError(json(error), response, context);
    }
    const body = json(data);
    if (!matchesComponentSchema("KnowledgeContent", body) ||
      body.resourceId !== request.resourceId ||
      (request.resourceVersionId !== undefined && body.resourceVersionId !== request.resourceVersionId) ||
      body.lineCount !== body.content.split("\n").length ||
      new TextEncoder().encode(body.content).byteLength > 1024 * 1024 ||
      body.format !== (body.mediaType === "text/markdown" ? "markdown" : "text") ||
      !["text/markdown", "text/plain"].includes(body.mediaType) ||
      (request.chunkId === undefined ? body.highlight !== null : body.highlight?.chunkId !== request.chunkId)
    ) throw knowledgeContractError(context);
    const hit = body.highlight;
    if (hit !== null) {
      if (!Number.isInteger(hit.lineStart) || !Number.isInteger(hit.lineEnd) ||
        hit.lineStart > hit.lineEnd || hit.lineEnd > body.lineCount || !hit.text.trim())
        throw knowledgeContractError(context);
      if (hit.matchType === "exact") {
        const window = body.content.split("\n").slice(hit.lineStart - 1, hit.lineEnd).join("\n");
        const offset = window.indexOf(hit.text);
        if (offset < 0 || window.indexOf(hit.text, offset + 1) >= 0 ||
          window.slice(0, offset).includes("\n") || hit.text.split("\n").length !== hit.lineEnd - hit.lineStart + 1)
          throw knowledgeContractError(context);
      }
    }
    return body;
  } catch (error) { throw knowledgeRequestError(error, context, request.signal); }
}
