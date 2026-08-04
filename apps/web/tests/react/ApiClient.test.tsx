import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
  vi.resetModules();
});

const IDENTITY = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
  csrfToken: "csrf-test-token",
};

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

  const { request } = await import("../../src/api/client.ts");

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

  const { request } = await import("../../src/api/client.ts");

  await expect(request("/api/v1/probe")).rejects.toMatchObject({
    code: "internal_error",
    traceId: "trace-header-456",
  });
});

test("identity requests use the identity origin with credentials", async () => {
  vi.stubEnv("VITE_IDENTITY_API_URL", "http://identity.test");
  const { login } = await import("../../src/api/auth.ts");
  const requests: Request[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(IDENTITY);
  });
  vi.stubGlobal("fetch", fetchMock);

  await login({ email: "demo@cairn.dev", password: "cairn-demo-2026" }, new AbortController().signal);

  const request = requests[0];
  expect(request).toBeDefined();
  if (request === undefined) return;
  expect(new URL(request.url).origin).toBe("http://identity.test");
  expect(request.credentials).toBe("include");
});

test("identity requests abort at the client deadline", async () => {
  vi.useFakeTimers();
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      requestSignal = (input as Request).signal;
      return await new Promise<Response>((_resolve, reject) => {
        requestSignal?.addEventListener(
          "abort",
          () => reject(requestSignal?.reason ?? new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    }),
  );

  const { restoreSession } = await import("../../src/api/auth.ts");
  const parent = new AbortController();
  const pending = restoreSession(parent.signal);
  const rejected = expect(pending).rejects.toMatchObject({ kind: "timeout" });

  try {
    await vi.advanceTimersByTimeAsync(3_000);
    expect(requestSignal?.aborted).toBe(true);
    await rejected;
  } finally {
    parent.abort();
    await pending.catch(() => undefined);
  }
});

test("identity requests reject malformed successful responses", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ user: null })));
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  const { restoreSession } = await import("../../src/api/auth.ts");

  await expect(restoreSession(new AbortController().signal)).rejects.toMatchObject({
    kind: "contract",
    context: "GET /api/v1/session",
  });
});

test("mock requests use the mock origin without credentials", async () => {
  vi.stubEnv("VITE_MOCK_API_URL", "http://mock.test");
  const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    calls.push([input, options]);
    return Response.json({ ok: true });
  });
  vi.stubGlobal("fetch", fetchMock);

  const { request } = await import("../../src/api/client.ts");

  await request("/api/v1/probe");

  const [url, options] = calls[0] ?? [];
  expect(url).toBeDefined();
  if (url === undefined) return;
  expect(new URL(String(url)).origin).toBe("http://mock.test");
  expect(options?.credentials).toBeUndefined();
});

test("mock requests retain the legacy VITE_API_URL fallback", async () => {
  vi.stubEnv("VITE_API_URL", "http://legacy-mock.test");
  const calls: Array<RequestInfo | URL> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(input);
      return Response.json({ ok: true });
    }),
  );

  const { request } = await import("../../src/api/client.ts");
  await request("/api/v1/probe");

  expect(new URL(String(calls[0])).origin).toBe("http://legacy-mock.test");
});
