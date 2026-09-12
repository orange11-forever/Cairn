import assert from "node:assert/strict";
import test from "node:test";

import { once } from "node:events";

import {
  createEmbeddingVector,
  createFakeEmbeddingServer,
  validateEmbeddingRequest,
} from "../../../../scripts/fake-embedding.mjs";

test("fake embeddings are deterministic normalized 1024-dimensional vectors", () => {
  const first = createEmbeddingVector("跨区域恢复 exact-token", 1024);
  const second = createEmbeddingVector("跨区域恢复 exact-token", 1024);
  assert.deepEqual(first, second);
  assert.equal(first.length, 1024);
  assert.ok(Math.abs(Math.hypot(...first) - 1) < 1e-9);
});

test("fake provider HTTP boundary returns stable safe responses", async () => {
  const server = createFakeEmbeddingServer({
    EMBEDDING_API_KEY: "boundary-key",
    EMBEDDING_MODEL: "boundary-model",
    EMBEDDING_DIM: "1024",
    EMBEDDING_BATCH_SIZE: "10",
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.notEqual(address, null);
  assert.equal(typeof address, "object");
  const origin = `http://127.0.0.1:${address.port}`;
  try {
    const health = await fetch(`${origin}/health`);
    assert.equal(health.status, 200);
    assert.deepEqual(await health.json(), { status: "ok" });

    const success = await fetch(`${origin}/v1/embeddings`, {
      method: "POST",
      headers: { authorization: "Bearer boundary-key", "content-type": "application/json" },
      body: JSON.stringify({ input: ["hello"], model: "boundary-model", dimensions: 1024 }),
    });
    assert.equal(success.status, 200);
    const successBody = await success.json();
    assert.equal(successBody.data[0].embedding.length, 1024);

    for (const boundary of [
      { headers: { "content-type": "application/json" }, body: "{}", status: 401, code: "unauthorized" },
      { headers: { authorization: "Bearer boundary-key", "content-type": "application/json" }, body: '{"private":"LEAK-ME"', status: 400, code: "invalid_json" },
      { headers: { authorization: "Bearer boundary-key", "content-type": "text/plain" }, body: "LEAK-ME", status: 415, code: "unsupported_media_type" },
      { headers: { authorization: "Bearer boundary-key", "content-type": "application/json" }, body: JSON.stringify({ padding: "x".repeat(257 * 1024) }), status: 413, code: "request_too_large" },
    ]) {
      const response = await fetch(`${origin}/v1/embeddings`, {
        method: "POST", headers: boundary.headers, body: boundary.body,
      });
      assert.equal(response.status, boundary.status);
      assert.match(response.headers.get("content-type") ?? "", /^application\/json/);
      assert.equal(response.headers.get("cache-control"), "no-store");
      const body = await response.json();
      assert.equal(body.error.code, boundary.code);
      assert.doesNotMatch(body.error.message, /LEAK-ME/);
    }
  } finally {
    server.close();
    await once(server, "close");
  }
});

test("fake provider validates auth, model, dimensions, and bounded input", () => {
  assert.deepEqual(validateEmbeddingRequest({
    authorization: "Bearer local-key",
    expectedApiKey: "local-key",
    body: { input: ["one", "two"], model: "model-a", dimensions: 1024 },
    expectedModel: "model-a",
    expectedDimensions: 1024,
    maximumBatchSize: 10,
  }), ["one", "two"]);
  assert.throws(() => validateEmbeddingRequest({
    authorization: "Bearer wrong",
    expectedApiKey: "local-key",
    body: { input: ["one"], model: "model-a", dimensions: 1024 },
    expectedModel: "model-a",
    expectedDimensions: 1024,
    maximumBatchSize: 10,
  }), /authorization/);
  assert.throws(() => validateEmbeddingRequest({
    authorization: "Bearer local-key",
    expectedApiKey: "local-key",
    body: { input: [], model: "model-a", dimensions: 1024 },
    expectedModel: "model-a",
    expectedDimensions: 1024,
    maximumBatchSize: 10,
  }), /input/);
});
