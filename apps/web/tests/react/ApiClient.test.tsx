import { afterEach, expect, test, vi } from "vitest";

import { request } from "../../src/api/client.ts";

afterEach(() => vi.unstubAllGlobals());

test("HTTP errors preserve code and traceId from the normalized body", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(
        JSON.stringify({
          message: "配额已用完",
          code: "quota_exceeded",
          traceId: "trace-body-123",
        }),
        { status: 429, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );

  await expect(request("/api/v1/probe")).rejects.toMatchObject({
    kind: "http",
    status: 429,
    message: "配额已用完",
    code: "quota_exceeded",
    traceId: "trace-body-123",
  });
});

test("HTTP errors use X-Request-ID when the body has no traceId", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify({ message: "服务器内部错误", code: "internal_error" }), {
        status: 500,
        headers: { "Content-Type": "application/json", "X-Request-ID": "trace-header-456" },
      }),
    ),
  );

  await expect(request("/api/v1/probe")).rejects.toMatchObject({
    code: "internal_error",
    traceId: "trace-header-456",
  });
});
