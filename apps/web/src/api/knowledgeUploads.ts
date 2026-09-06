import {
  createCairnClient,
  matchesComponentSchema,
  type components,
} from "@cairn/sdk";

import type { PreparedKnowledgeFile } from "../lib/knowledgeUpload.ts";
import { apiOrigins } from "./config.ts";
import { ApiError } from "./errors.ts";
import {
  knowledgeContractError,
  knowledgeRequestError,
  knowledgeResponseError,
} from "./knowledgeRequest.ts";

export type KnowledgeUploadBatch = components["schemas"]["UploadBatchCreateResponse"];
export type KnowledgeUploadInstruction = components["schemas"]["UploadInstruction"];
export type KnowledgeUploadCompletion = components["schemas"]["UploadCompleteResponse"];
export type KnowledgeBatchDetail = components["schemas"]["BatchDetailResponse"];
export interface KnowledgeUploadProgress {
  loaded: number;
  total: number;
  percent: number;
}

export function putKnowledgeObject({
  instruction,
  file,
  signal,
  onProgress,
  xhrFactory = () => new XMLHttpRequest(),
}: {
  instruction: KnowledgeUploadInstruction;
  file: File;
  signal: AbortSignal;
  onProgress: (progress: KnowledgeUploadProgress) => void;
  xhrFactory?: () => XMLHttpRequest;
}): Promise<void> {
  return new Promise((resolve, reject) => {
    const abortError = () => new ApiError("aborted", "请求已被取消");
    const networkError = () => new ApiError("network", "文件直传失败，请重试");

    if (signal.aborted) {
      reject(abortError());
      return;
    }

    try {
      const instructionOrigin = new URL(instruction.url, window.location.href).origin;
      if (instructionOrigin === window.location.origin) {
        reject(networkError());
        return;
      }
    } catch {
      reject(networkError());
      return;
    }

    let xhr: XMLHttpRequest;
    try {
      xhr = xhrFactory();
    } catch {
      reject(networkError());
      return;
    }

    let settled = false;

    function cleanup(): void {
      signal.removeEventListener("abort", handleSignalAbort);
      xhr.onload = null;
      xhr.onerror = null;
      xhr.onabort = null;
      xhr.upload.onprogress = null;
    }

    function finish(action: () => void): void {
      if (settled) return;
      settled = true;
      cleanup();
      action();
    }

    function failAsAborted(): void {
      finish(() => reject(abortError()));
    }

    function failAsNetwork(): void {
      finish(() => reject(networkError()));
    }

    function failProgressAsNetwork(): void {
      if (settled) return;
      failAsNetwork();
      try {
        xhr.abort();
      } catch {
        // The fixed progress failure has already settled and cleaned up the upload.
      }
    }

    function handleSignalAbort(): void {
      if (settled) return;
      try {
        xhr.abort();
      } catch {
        // Cancellation still wins when an XHR implementation throws from abort().
      }
      failAsAborted();
    }

    xhr.onload = () => {
      try {
        if (xhr.status >= 200 && xhr.status < 300) finish(resolve);
        else failAsNetwork();
      } catch {
        failAsNetwork();
      }
    };
    xhr.onerror = failAsNetwork;
    xhr.onabort = failAsAborted;
    xhr.upload.onprogress = (event) => {
      if (settled) return;
      try {
        const { loaded, total, lengthComputable } = event;
        const reportedTotal = lengthComputable ? total : file.size;
        const ratio = reportedTotal > 0 ? loaded / reportedTotal : 0;
        const percent = Number.isFinite(ratio)
          ? Math.min(100, Math.max(0, Math.round(ratio * 100)))
          : 0;
        onProgress({ loaded, total: reportedTotal, percent });
      } catch {
        failProgressAsNetwork();
      }
    };

    signal.addEventListener("abort", handleSignalAbort, { once: true });
    if (signal.aborted) {
      handleSignalAbort();
      return;
    }

    try {
      xhr.open("PUT", instruction.url, true);
      if (settled) return;
      xhr.withCredentials = false;
      if (settled) return;
      for (const [name, value] of Object.entries(instruction.headers)) {
        xhr.setRequestHeader(name, value);
        if (settled) return;
      }
      xhr.send(file);
    } catch {
      if (signal.aborted) failAsAborted();
      else failAsNetwork();
    }
  });
}

function knowledgeUploadsClient() {
  return createCairnClient({ baseUrl: apiOrigins.identity });
}

function parseExpectedJsonResponse(
  data: unknown,
  response: Response,
  expectedStatus: number,
  context: string,
): unknown {
  if (response.status !== expectedStatus || typeof data !== "string" || data.length === 0) {
    throw knowledgeContractError(context);
  }
  try {
    return JSON.parse(data) as unknown;
  } catch {
    throw knowledgeContractError(context);
  }
}

export async function createKnowledgeUploadBatch({
  projectId,
  csrfToken,
  intents,
  signal,
}: {
  projectId: string;
  csrfToken: string;
  intents: readonly PreparedKnowledgeFile["intent"][];
  signal: AbortSignal;
}): Promise<KnowledgeUploadBatch> {
  const context = "POST /api/v1/projects/{project_id}/knowledge/uploads";
  try {
    const { data, error, response } = await knowledgeUploadsClient().POST(
      "/api/v1/projects/{project_id}/knowledge/uploads",
      {
        params: {
          path: { project_id: projectId },
          header: { "X-CSRF-Token": csrfToken },
        },
        body: { files: [...intents] },
        parseAs: "text",
        signal,
      },
    );
    if (!response.ok) throw knowledgeResponseError(error, response, context);
    const parsed = parseExpectedJsonResponse(data, response, 201, context);
    if (!matchesComponentSchema("UploadBatchCreateResponse", parsed)) {
      throw knowledgeContractError(context);
    }
    if (
      parsed.uploads.length !== intents.length ||
      new Set(parsed.uploads.map(({ uploadId }) => uploadId)).size !== parsed.uploads.length ||
      new Set(parsed.uploads.map(({ itemId }) => itemId)).size !== parsed.uploads.length ||
      parsed.uploads.some(({ method }) => method !== "PUT")
    ) {
      throw knowledgeContractError(context);
    }
    return parsed;
  } catch (error) {
    throw knowledgeRequestError(error, context, signal);
  }
}

export async function completeKnowledgeUpload({
  projectId,
  uploadId,
  batchId,
  itemId,
  csrfToken,
  signal,
}: {
  projectId: string;
  uploadId: string;
  batchId: string;
  itemId: string;
  csrfToken: string;
  signal: AbortSignal;
}): Promise<KnowledgeUploadCompletion> {
  const context =
    "POST /api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete";
  try {
    const { data, error, response } = await knowledgeUploadsClient().POST(
      "/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
      {
        params: {
          path: { project_id: projectId, upload_id: uploadId },
          header: { "X-CSRF-Token": csrfToken },
        },
        parseAs: "text",
        signal,
      },
    );
    if (!response.ok) throw knowledgeResponseError(error, response, context);
    const parsed = parseExpectedJsonResponse(data, response, 200, context);
    if (!matchesComponentSchema("UploadCompleteResponse", parsed)) {
      throw knowledgeContractError(context);
    }
    if (
      parsed.uploadId !== uploadId ||
      parsed.batchId !== batchId ||
      parsed.itemId !== itemId
    ) {
      throw knowledgeContractError(context);
    }
    return parsed;
  } catch (error) {
    throw knowledgeRequestError(error, context, signal);
  }
}

export async function fetchKnowledgeBatch({
  projectId,
  batchId,
  signal,
}: {
  projectId: string;
  batchId: string;
  signal: AbortSignal;
}): Promise<KnowledgeBatchDetail> {
  const context = "GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}";
  try {
    const { data, error, response } = await knowledgeUploadsClient().GET(
      "/api/v1/projects/{project_id}/knowledge/batches/{batch_id}",
      {
        params: { path: { project_id: projectId, batch_id: batchId } },
        parseAs: "text",
        signal,
      },
    );
    if (!response.ok) throw knowledgeResponseError(error, response, context);
    const parsed = parseExpectedJsonResponse(data, response, 200, context);
    if (!matchesComponentSchema("BatchDetailResponse", parsed) || parsed.id !== batchId) {
      throw knowledgeContractError(context);
    }
    return parsed;
  } catch (error) {
    throw knowledgeRequestError(error, context, signal);
  }
}
