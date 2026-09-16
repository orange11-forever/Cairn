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

test("identity HTTP errors preserve a complete generated ErrorBody", async () => {
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

  const { restoreSession } = await import("../../src/api/auth.ts");

  await expect(restoreSession(new AbortController().signal)).rejects.toMatchObject({
    kind: "http",
    status: 429,
    message: "配额已用完",
    code: "quota_exceeded",
    traceId: "trace-body-123",
  });
});

test("partial identity error bodies use the safe fallback and cannot impersonate session_invalid", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify({ message: "会话失效", code: "session_invalid" }), {
        status: 401,
        headers: { "Content-Type": "application/json", "X-Request-ID": "trace-header-456" },
      }),
    ),
  );

  const { restoreSession } = await import("../../src/api/auth.ts");

  await expect(restoreSession(new AbortController().signal)).rejects.toMatchObject({
    status: 401,
    message: "服务器返回 401",
    code: "http_error",
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
