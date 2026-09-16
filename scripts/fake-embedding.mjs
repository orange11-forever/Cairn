import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const MAX_BODY_BYTES = 256 * 1024;

class ProviderRequestError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function invalid(code, message = "invalid embedding request") {
  return new ProviderRequestError(400, code, message);
}

function integer(environment, name, fallback, { minimum = 1, maximum = 65_535 } = {}) {
  const raw = environment[name] ?? String(fallback);
  const value = Number(raw);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return value;
}

export function createEmbeddingVector(input, dimensions) {
  if (typeof input !== "string" || input.length === 0) throw new Error("input must be nonempty");
  const normalized = input.normalize("NFKC").toLocaleLowerCase("und");
  const characters = [...normalized];
  const features = new Set([normalized]);
  for (const word of normalized.split(/\s+/u)) if (word) features.add(word);
  for (let index = 0; index < characters.length; index += 1) {
    features.add(characters.slice(index, index + 3).join(""));
  }
  const vector = Array(dimensions).fill(0);
  for (const feature of features) {
    const digest = createHash("sha256").update(feature).digest();
    const bucket = digest.readUInt32BE(0) % dimensions;
    vector[bucket] += (digest[4] & 1) === 0 ? 1 : -1;
  }
  const norm = Math.hypot(...vector) || 1;
  return vector.map((value) => value / norm);
}

export function validateEmbeddingRequest({
  authorization, expectedApiKey, body, expectedModel, expectedDimensions, maximumBatchSize,
}) {
  if (authorization !== `Bearer ${expectedApiKey}`) {
    throw new ProviderRequestError(401, "unauthorized", "invalid authorization");
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    throw invalid("invalid_body");
  }
  if (body.model !== expectedModel) throw invalid("invalid_model", "invalid model");
  if (body.dimensions !== expectedDimensions) throw invalid("invalid_dimensions", "invalid dimensions");
  if (!Array.isArray(body.input) || body.input.length < 1 || body.input.length > maximumBatchSize) {
    throw invalid("invalid_input", "input must be a bounded nonempty array");
  }
  if (body.input.some((value) => typeof value !== "string" || value.length === 0)) {
    throw invalid("invalid_input", "input values must be nonempty strings");
  }
  return body.input;
}

async function readJson(request) {
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > MAX_BODY_BYTES) {
      throw new ProviderRequestError(413, "request_too_large", "request body too large");
    }
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw invalid("invalid_json", "request body is not valid JSON");
  }
}

function json(response, status, body) {
  const payload = Buffer.from(JSON.stringify(body));
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": payload.length,
    "cache-control": "no-store",
  });
  response.end(payload);
}

export function createFakeEmbeddingServer(environment = process.env) {
  const apiKey = environment.EMBEDDING_API_KEY ?? "local-fake-embedding-key";
  const model = environment.EMBEDDING_MODEL ?? "text-embedding-v4";
  const answerApiKey = environment.ANSWER_API_KEY ?? "local-fake-answer-key";
  const answerModel = environment.ANSWER_MODEL ?? "local-fake-answer";
  const dimensions = integer(environment, "EMBEDDING_DIM", 1024, { maximum: 4096 });
  const maximumBatchSize = integer(environment, "EMBEDDING_BATCH_SIZE", 10, { maximum: 10 });
  return createServer(async (request, response) => {
    try {
      if (request.method === "GET" && request.url === "/health") {
        json(response, 200, { status: "ok" });
        return;
      }
      if (request.method !== "POST" || !["/v1/embeddings", "/v1/chat/completions"].includes(request.url)) {
        json(response, 404, { error: { message: "not found" } });
        return;
      }
      if ((request.headers["content-type"] ?? "").split(";", 1)[0].trim().toLowerCase()
          !== "application/json") {
        throw new ProviderRequestError(415, "unsupported_media_type", "content type must be application/json");
      }
      const body = await readJson(request);
      if (request.url === "/v1/chat/completions") {
        if (request.headers.authorization !== `Bearer ${answerApiKey}`) {
          throw new ProviderRequestError(401, "unauthorized", "invalid authorization");
        }
        if (
          body === null || typeof body !== "object" || Array.isArray(body) ||
          body.model !== answerModel || body.stream !== false ||
          body.response_format?.type !== "json_object" || body.max_tokens !== 2048 ||
          body.tools !== undefined || !Array.isArray(body.messages) || body.messages.length !== 2
        ) throw invalid("invalid_answer_request", "invalid answer request");
        let prompt;
        try { prompt = JSON.parse(body.messages[1]?.content); } catch { throw invalid("invalid_answer_prompt"); }
        const evidence = Array.isArray(prompt?.evidence) ? prompt.evidence : [];
        const first = evidence.find((item) =>
          item !== null && typeof item === "object" && /^S[1-6]$/.test(item.id) &&
          typeof item.text === "string" && item.text.length > 0
        );
        const generated = first === undefined
          ? { status: "insufficient_evidence", paragraphs: [] }
          : { status: "answered", paragraphs: [{ text: first.text, citationIds: [first.id] }] };
        json(response, 200, {
          choices: [{ finish_reason: "stop", message: {
            role: "assistant", content: JSON.stringify(generated),
          } }],
        });
        return;
      }
      const inputs = validateEmbeddingRequest({
        authorization: request.headers.authorization,
        expectedApiKey: apiKey,
        body,
        expectedModel: model,
        expectedDimensions: dimensions,
        maximumBatchSize,
      });
      json(response, 200, {
        object: "list",
        model,
        data: inputs.map((input, index) => ({
          object: "embedding", index, embedding: createEmbeddingVector(input, dimensions),
        })),
      });
    } catch (error) {
      const expected = error instanceof ProviderRequestError;
      json(response, expected ? error.status : 400, {
        error: {
          code: expected ? error.code : "invalid_request",
          message: expected ? error.message : "invalid embedding request",
        },
      });
    }
  });
}

const entryPath = process.argv[1];
const isMain = entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url);
if (isMain) {
  const port = integer(process.env, "CAIRN_EMBEDDING_PORT", 58081);
  const server = createFakeEmbeddingServer();
  server.listen(port, "127.0.0.1", () => {
    console.log(`Fake Embedding listening on http://127.0.0.1:${port}`);
  });
  const stop = () => server.close(() => { process.exitCode = 0; });
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
}
