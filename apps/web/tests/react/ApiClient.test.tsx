import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

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
    return Response.json({
      user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
      organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
      membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
      csrfToken: "csrf-test-token",
    });
  });
  vi.stubGlobal("fetch", fetchMock);

  await login({ email: "demo@cairn.dev", password: "cairn-demo-2026" }, new AbortController().signal);

  const request = requests[0];
  expect(request).toBeDefined();
  if (request === undefined) return;
  expect(new URL(request.url).origin).toBe("http://identity.test");
  expect(request.credentials).toBe("include");
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
