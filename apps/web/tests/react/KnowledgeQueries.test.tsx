import {
  focusManager,
  onlineManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";

import type { KnowledgeBatchDetail } from "../../src/api/knowledgeUploads.ts";
import { createAppQueryClient } from "../../src/app/queryClient.ts";
import {
  isKnowledgeBatchTerminal,
  knowledgeKeys,
  shouldPollKnowledgeBatch,
  useKnowledgeBatchQuery,
  useKnowledgeChunkContextQuery,
  useKnowledgeSearchQuery,
} from "../../src/queries/knowledge.ts";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const RESOURCE_ID = "00000000-0000-4000-8000-000000005001";
const RESOURCE_VERSION_ID = "00000000-0000-4000-8000-000000006001";
const CHUNK_ID = "00000000-0000-4000-8000-000000007001";
const BATCH_ID = "00000000-0000-4000-8000-000000008001";
const OTHER_BATCH_ID = "00000000-0000-4000-8000-000000008002";
const ITEM_ID = "00000000-0000-4000-8000-000000009001";
const validContext = {
  resourceId: RESOURCE_ID,
  resourceVersionId: RESOURCE_VERSION_ID,
  before: null,
  hit: {
    id: CHUNK_ID,
    ordinal: 1,
    text: "命中原文",
    locator: { type: "pdf", page: 2 },
  },
  after: null,
} as const;
const processingBatch = {
  id: BATCH_ID,
  status: "processing",
  itemCount: 1,
  readyCount: 0,
  failedCount: 0,
  createdAt: "2026-09-03T09:00:00Z",
  completedAt: null,
  items: [{
    id: ITEM_ID,
    parentItemId: null,
    normalizedPath: "design.pdf",
    mediaType: "application/pdf",
    sizeBytes: 12,
    status: "processing",
    resourceId: null,
    resourceVersionId: null,
    errorCode: null,
    errorDetail: null,
    createdAt: "2026-09-03T09:00:00Z",
    completedAt: null,
  }],
} satisfies KnowledgeBatchDetail;

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper(client: QueryClient) {
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((next, fail) => {
    resolve = next;
    reject = fail;
  });
  return { promise, resolve, reject };
}

afterEach(() => {
  focusManager.setFocused(undefined);
  onlineManager.setOnline(true);
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("the polling deadline begins when the batch query first becomes enabled", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let monotonicNow = 0;
  vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
  const fetchSpy = vi.fn(async () => Response.json(processingBatch));
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(({ enabled }) => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled,
    sessionSignal: session.signal,
  }), {
    initialProps: { enabled: false },
    wrapper: wrapper(client),
  });
  monotonicNow = 299_000;
  rendered.rerender({ enabled: true });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  monotonicNow = 300_001;
  await act(async () => vi.advanceTimersByTimeAsync(2_000));

  expect(fetchSpy).toHaveBeenCalledTimes(2);
  expect(rendered.result.current.automaticPollingStopped).toBe(false);
});

test("a pending first batch request cannot postpone the five-minute stopped state", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const firstResponse = deferred<Response>();
  let requestSignal: AbortSignal | undefined;
  const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
    requestSignal = (input as Request).signal;
    return firstResponse.promise;
  });
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  await act(async () => vi.advanceTimersByTimeAsync(300_000));

  expect(rendered.result.current.automaticPollingStopped).toBe(true);
  expect(rendered.result.current.fetchStatus).toBe("fetching");
  expect(requestSignal?.aborted).toBe(false);
  let manualRefresh!: Promise<unknown>;
  act(() => { manualRefresh = rendered.result.current.refetch({ cancelRefetch: false }); });
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  firstResponse.resolve(Response.json(processingBatch));
  await act(async () => manualRefresh);
  expect(rendered.result.current.automaticPollingStopped).toBe(true);
});

test("a pending automatic batch request cannot postpone the deadline or start another poll", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const automaticResponse = deferred<Response>();
  let automaticSignal: AbortSignal | undefined;
  const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
    if (fetchSpy.mock.calls.length === 1) return Response.json(processingBatch);
    automaticSignal = (input as Request).signal;
    return automaticResponse.promise;
  });
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
  await act(async () => vi.advanceTimersByTimeAsync(2_000));
  expect(fetchSpy).toHaveBeenCalledTimes(2);

  await act(async () => vi.advanceTimersByTimeAsync(298_000));

  expect(rendered.result.current.automaticPollingStopped).toBe(true);
  expect(rendered.result.current.data?.status).toBe("processing");
  expect(rendered.result.current.fetchStatus).toBe("fetching");
  expect(automaticSignal?.aborted).toBe(false);
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  expect(fetchSpy).toHaveBeenCalledTimes(2);
  automaticResponse.resolve(Response.json(processingBatch));
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(fetchSpy).toHaveBeenCalledTimes(2);
});

test.each(["http", "network"] as const)(
  "a late automatic %s failure cannot retry after the polling deadline",
  async (failureKind) => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const automaticResponse = deferred<Response>();
    const fetchSpy = vi.fn(async () => {
      if (fetchSpy.mock.calls.length === 1) return Response.json(processingBatch);
      return automaticResponse.promise;
    });
    vi.stubGlobal("fetch", fetchSpy);
    const client = createAppQueryClient();
    const session = new AbortController();
    const rendered = renderHook(() => useKnowledgeBatchQuery({
      organizationId: "org-a",
      projectId: PROJECT_ID,
      batchId: BATCH_ID,
      enabled: true,
      sessionSignal: session.signal,
    }), { wrapper: wrapper(client) });
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    await act(async () => vi.advanceTimersByTimeAsync(298_000));
    expect(rendered.result.current.automaticPollingStopped).toBe(true);

    if (failureKind === "http") {
      automaticResponse.resolve(Response.json({
        message: "数据库暂时不可用",
        code: "database_unavailable",
        traceId: "trace-late-retry",
      }, { status: 503, headers: { "X-Request-ID": "trace-late-retry" } }));
    } else {
      automaticResponse.reject(new TypeError("Failed to fetch"));
    }
    await act(async () => vi.advanceTimersByTimeAsync(2_000));

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(rendered.result.current.automaticPollingStopped).toBe(true);
  },
);

test("a retry delay that crosses the deadline is cancelled without replacing cached batch truth", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const automaticResponse = deferred<Response>();
  const fetchSpy = vi.fn(async () => {
    if (fetchSpy.mock.calls.length === 1) return Response.json(processingBatch);
    return automaticResponse.promise;
  });
  vi.stubGlobal("fetch", fetchSpy);
  const client = createAppQueryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
  await act(async () => vi.advanceTimersByTimeAsync(2_000));
  await act(async () => vi.advanceTimersByTimeAsync(297_500));
  automaticResponse.resolve(Response.json({
    message: "数据库暂时不可用",
    code: "database_unavailable",
    traceId: "trace-delayed-retry",
  }, { status: 503, headers: { "X-Request-ID": "trace-delayed-retry" } }));
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(rendered.result.current.failureCount).toBe(1);

  await act(async () => vi.advanceTimersByTimeAsync(2_500));

  expect(fetchSpy).toHaveBeenCalledTimes(2);
  expect(rendered.result.current.automaticPollingStopped).toBe(true);
  expect(rendered.result.current.data?.status).toBe("processing");
  expect(rendered.result.current.error).toBeNull();
  expect(rendered.result.current.fetchStatus).toBe("idle");
});

test("a first-request retry delay crossing the deadline stops without publishing a batch error", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const firstResponse = deferred<Response>();
  const fetchSpy = vi.fn(async () => firstResponse.promise);
  vi.stubGlobal("fetch", fetchSpy);
  const client = createAppQueryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(299_500));
  firstResponse.resolve(Response.json({
    message: "数据库暂时不可用",
    code: "database_unavailable",
    traceId: "trace-first-delayed-retry",
  }, { status: 503, headers: { "X-Request-ID": "trace-first-delayed-retry" } }));
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(rendered.result.current.failureCount).toBe(1);

  await act(async () => vi.advanceTimersByTimeAsync(2_500));

  expect(fetchSpy).toHaveBeenCalledTimes(1);
  expect(rendered.result.current.automaticPollingStopped).toBe(true);
  expect(rendered.result.current.data).toBeUndefined();
  expect(rendered.result.current.error).toBeNull();
  expect(rendered.result.current.fetchStatus).toBe("idle");
});

test("a suspended first-request retry checks expiry before the deadline notifier runs", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let monotonicNow = 0;
  vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
  const requestTimes: number[] = [];
  vi.stubGlobal("fetch", vi.fn(async () => {
    requestTimes.push(performance.now());
    if (requestTimes.length <= 2) {
      return Response.json({
        message: "数据库暂时不可用",
        code: "database_unavailable",
        traceId: "trace-suspended-retry",
      }, { status: 503, headers: { "X-Request-ID": "trace-suspended-retry" } });
    }
    return Response.json(processingBatch);
  }));
  const client = createAppQueryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(result.current.failureCount).toBe(1));

  // Suspension advances elapsed time while the already-due retry drains before
  // the much later deadline timer. Keep the two clocks independent.
  monotonicNow = 300_001;
  await act(async () => vi.advanceTimersByTimeAsync(1_000));

  expect(requestTimes).toEqual([0]);
  expect(result.current.automaticPollingStopped).toBe(true);
  expect(result.current.data).toBeUndefined();
  expect(result.current.error).toBeNull();
  expect(result.current.fetchStatus).toBe("idle");
  expect(client.isFetching()).toBe(0);

  let manualRefresh!: Promise<unknown>;
  act(() => { manualRefresh = result.current.refetch({ cancelRefetch: false }); });
  await act(async () => vi.advanceTimersByTimeAsync(1_000));
  await act(async () => manualRefresh);

  expect(requestTimes).toEqual([0, 300_001, 300_001]);
  await vi.waitFor(() => expect(result.current.data?.status).toBe("processing"));
  expect(result.current.error).toBeNull();
  expect(result.current.fetchStatus).toBe("idle");
  expect(result.current.automaticPollingStopped).toBe(true);
});

test.each([
  [false, "natural"],
  [true, "natural"],
  [false, "suspended"],
  [true, "suspended"],
] as const)("offline automatic work expires safely (cached=%s, clock=%s)", async (cached, clock) => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let monotonicNow = 0;
  vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
  onlineManager.setOnline(cached);
  const requests: number[] = [];
  let manualAttempts = 0;
  let manualPhase = false;
  vi.stubGlobal("fetch", vi.fn(async () => {
    requests.push(performance.now());
    if (manualPhase && ++manualAttempts === 1) {
      return Response.json({
        message: "数据库暂时不可用", code: "database_unavailable", traceId: "trace-paused-manual",
      }, { status: 503, headers: { "X-Request-ID": "trace-paused-manual" } });
    }
    return Response.json(processingBatch);
  }));
  const client = createAppQueryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a", projectId: PROJECT_ID, batchId: BATCH_ID,
    enabled: true, sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  if (cached) {
    await vi.waitFor(() => expect(result.current.data?.status).toBe("processing"));
    onlineManager.setOnline(false);
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
  }
  await vi.waitFor(() => expect(result.current.fetchStatus).toBe("paused"));

  monotonicNow = 300_001;
  if (clock === "natural") {
    await act(async () => vi.advanceTimersByTimeAsync(300_001));
    expect(result.current.fetchStatus).toBe("idle");
  }
  onlineManager.setOnline(true);
  await act(async () => vi.advanceTimersByTimeAsync(1_000));

  expect(requests).toEqual(cached ? [0] : []);
  expect(result.current.automaticPollingStopped).toBe(true);
  expect(result.current.data?.status).toBe(cached ? "processing" : undefined);
  expect(result.current.error).toBeNull();
  expect(result.current.fetchStatus).toBe("idle");
  expect(client.isFetching()).toBe(0);

  manualPhase = true;
  let manual!: Promise<unknown>;
  act(() => { manual = result.current.refetch({ cancelRefetch: false }); });
  await act(async () => vi.advanceTimersByTimeAsync(1_000));
  await act(async () => manual);
  await vi.waitFor(() => expect(result.current.data?.status).toBe("processing"));
  expect(manualAttempts).toBe(2);
  expect(result.current.error).toBeNull();
  expect(result.current.fetchStatus).toBe("idle");
});

test.each([false, true])("manual refresh can own an offline attempt before HTTP (cached=%s)", async (cached) => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  onlineManager.setOnline(cached);
  const requests: number[] = [];
  vi.stubGlobal("fetch", vi.fn(async () => {
    requests.push(performance.now());
    if (requests.length === (cached ? 2 : 1)) {
      return Response.json({
        message: "数据库暂时不可用", code: "database_unavailable", traceId: "trace-offline-owner",
      }, { status: 503, headers: { "X-Request-ID": "trace-offline-owner" } });
    }
    return Response.json(processingBatch);
  }));
  const client = createAppQueryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a", projectId: PROJECT_ID, batchId: BATCH_ID,
    enabled: true, sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  if (cached) {
    await vi.waitFor(() => expect(result.current.data?.status).toBe("processing"));
    onlineManager.setOnline(false);
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
  }
  expect(result.current.fetchStatus).toBe("paused");
  let manual!: Promise<unknown>;
  act(() => { manual = result.current.refetch({ cancelRefetch: false }); });
  await act(async () => vi.advanceTimersByTimeAsync(300_001 - performance.now()));
  expect(requests).toEqual(cached ? [0] : []);
  expect(result.current.fetchStatus).toBe("paused");
  expect(result.current.automaticPollingStopped).toBe(true);

  onlineManager.setOnline(true);
  await act(async () => vi.advanceTimersByTimeAsync(1_001));
  await act(async () => manual);
  await vi.waitFor(() => expect(result.current.data?.status).toBe("processing"));
  expect(requests).toEqual(cached ? [0, 300_001, 301_001] : [300_001, 301_001]);
  expect(result.current.error).toBeNull();
});

test.each([false, undefined])("joining an active first GET retains automatic retry limits (cancelRefetch=%s)", async (cancelRefetch) => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const firstResponse = deferred<Response>();
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return firstResponse.promise;
  }));
  const client = createAppQueryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a", projectId: PROJECT_ID, batchId: BATCH_ID,
    enabled: true, sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(300_001));
  let joined!: Promise<unknown>;
  act(() => { joined = result.current.refetch(cancelRefetch === undefined ? undefined : { cancelRefetch }); });
  expect(requests).toHaveLength(1);
  expect(requests[0]!.signal.aborted).toBe(false);
  firstResponse.resolve(Response.json({
    message: "数据库暂时不可用", code: "database_unavailable", traceId: "trace-joined-late-get",
  }, { status: 503, headers: { "X-Request-ID": "trace-joined-late-get" } }));
  await act(async () => vi.advanceTimersByTimeAsync(1_000));
  await act(async () => joined);
  expect(requests).toHaveLength(1);
  expect(result.current.fetchStatus).toBe("idle");
  expect(result.current.automaticPollingStopped).toBe(true);
});

test("an offline initial automatic request resumes normally before the deadline", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  onlineManager.setOnline(false);
  const fetchSpy = vi.fn(async () => Response.json(processingBatch));
  vi.stubGlobal("fetch", fetchSpy);
  const client = createAppQueryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a", projectId: PROJECT_ID, batchId: BATCH_ID,
    enabled: true, sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(5_000));
  expect(result.current.fetchStatus).toBe("paused");
  expect(fetchSpy).not.toHaveBeenCalled();
  onlineManager.setOnline(true);
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(result.current.data?.status).toBe("processing"));
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  expect(result.current.automaticPollingStopped).toBe(false);
});

test("manual refresh after the deadline retains the shared one-retry policy", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let manualPhase = false;
  let manualAttempts = 0;
  const fetchSpy = vi.fn(async () => {
    if (!manualPhase) return Response.json(processingBatch);
    manualAttempts += 1;
    if (manualAttempts === 1) {
      return Response.json({
        message: "数据库暂时不可用",
        code: "database_unavailable",
        traceId: "trace-manual-retry",
      }, { status: 503, headers: { "X-Request-ID": "trace-manual-retry" } });
    }
    return Response.json(processingBatch);
  });
  vi.stubGlobal("fetch", fetchSpy);
  const client = createAppQueryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
  await act(async () => vi.advanceTimersByTimeAsync(300_000));
  expect(rendered.result.current.automaticPollingStopped).toBe(true);
  const automaticRequests = fetchSpy.mock.calls.length;
  manualPhase = true;

  let manualRefresh!: Promise<unknown>;
  act(() => { manualRefresh = rendered.result.current.refetch(); });
  await act(async () => vi.advanceTimersByTimeAsync(1_000));
  await act(async () => manualRefresh);

  expect(fetchSpy).toHaveBeenCalledTimes(automaticRequests + 2);
  expect(rendered.result.current.error).toBeNull();
  expect(rendered.result.current.data?.status).toBe("processing");
});

test("changing the batch identity starts a fresh monotonic polling deadline", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let monotonicNow = 0;
  vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const requestedBatchId = new URL(request.url).pathname.split("/").at(-1);
    return Response.json({
      ...processingBatch,
      id: requestedBatchId,
      items: processingBatch.items.map((item) => ({ ...item })),
    });
  }));
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(({ batchId }) => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId,
    enabled: true,
    sessionSignal: session.signal,
  }), {
    initialProps: { batchId: BATCH_ID },
    wrapper: wrapper(client),
  });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(requests).toHaveLength(1);

  monotonicNow = 299_000;
  rendered.rerender({ batchId: OTHER_BATCH_ID });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(
    requests.filter(({ url }) => url.endsWith(OTHER_BATCH_ID)),
  ).toHaveLength(1));

  monotonicNow = 300_001;
  await act(async () => vi.advanceTimersByTimeAsync(2_000));

  expect(requests.filter(({ url }) => url.endsWith(OTHER_BATCH_ID))).toHaveLength(2);
});

test("knowledge batch keys isolate organization, project, and batch", () => {
  expect(knowledgeKeys.batch("org-a", "project-a", "batch-a")).toEqual([
    "project-knowledge", "org-a", "project-a", "batch", "batch-a",
  ]);
  expect(knowledgeKeys.batch("org-a", "project-a", "batch-a")).not.toEqual(
    knowledgeKeys.batch("org-b", "project-a", "batch-a"),
  );
  expect(knowledgeKeys.batch("org-a", "project-a", "batch-a")).not.toEqual(
    knowledgeKeys.batch("org-a", "project-b", "batch-a"),
  );
  expect(knowledgeKeys.batch("org-a", "project-a", "batch-a")).not.toEqual(
    knowledgeKeys.batch("org-a", "project-a", "batch-b"),
  );
});

test("knowledge batch polling policy recognizes terminal states and the timeout boundary", () => {
  expect(isKnowledgeBatchTerminal("pending")).toBe(false);
  expect(isKnowledgeBatchTerminal("processing")).toBe(false);
  expect(isKnowledgeBatchTerminal("completed")).toBe(true);
  expect(isKnowledgeBatchTerminal("completed_with_errors")).toBe(true);
  expect(isKnowledgeBatchTerminal("failed")).toBe(true);
  expect(shouldPollKnowledgeBatch(processingBatch, 0, 299_999)).toBe(2_000);
  expect(shouldPollKnowledgeBatch(processingBatch, 0, 300_000)).toBe(false);
  expect(shouldPollKnowledgeBatch({
    ...processingBatch,
    status: "completed",
  }, 0, 1)).toBe(false);
});

test("a pending knowledge batch refetches once every two seconds and stops when terminal", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const responses: KnowledgeBatchDetail[] = [
    { ...processingBatch, status: "pending" },
    processingBatch,
    { ...processingBatch, status: "completed", readyCount: 1, completedAt: "2026-09-03T09:01:00Z" },
  ];
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(responses[Math.min(requests.length - 1, responses.length - 1)]);
  }));
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });

  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(requests).toHaveLength(1);
  await act(async () => vi.advanceTimersByTimeAsync(1_999));
  expect(requests).toHaveLength(1);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(requests).toHaveLength(2);
  await act(async () => vi.advanceTimersByTimeAsync(2_000));
  expect(requests).toHaveLength(3);
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("completed"));
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  expect(requests).toHaveLength(3);
  expect(new URL(requests[0]!.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/batches/${BATCH_ID}`,
  );
  expect(client.getQueryData(knowledgeKeys.batch("org-a", PROJECT_ID, BATCH_ID)))
    .toMatchObject({ id: BATCH_ID, status: "completed" });
  onlineManager.setOnline(false);
  onlineManager.setOnline(true);
  await act(async () => vi.advanceTimersByTimeAsync(2_000));
  expect(requests).toHaveLength(3);
  expect(rendered.result.current.automaticPollingStopped).toBe(false);
});

test("automatic polling does not cancel an overlapping manual batch refetch", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (requests.length === 1) return Response.json(processingBatch);
    return await new Promise<Response>((_resolve, reject) => {
      request.signal.addEventListener("abort", () => {
        reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
  }));
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.fetchStatus).toBe("idle"));

  void act(() => { void rendered.result.current.refetch(); });
  await vi.waitFor(() => expect(requests).toHaveLength(2));
  const manualRequestSignal = requests[1]!.signal;
  expect(manualRequestSignal.aborted).toBe(false);

  await act(async () => vi.advanceTimersByTimeAsync(2_000));

  expect(manualRequestSignal.aborted).toBe(false);
  expect(requests).toHaveLength(2);

  act(() => session.abort());
  await vi.waitFor(() => expect(client.isFetching()).toBe(0));
});

test("hidden tabs pause automatic polling without pausing the deadline or manual refresh", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let monotonicNow = 0;
  vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
  const fetchSpy = vi.fn(async () => Response.json(processingBatch));
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  focusManager.setFocused(false);
  monotonicNow = 120_000;
  await act(async () => vi.advanceTimersByTimeAsync(120_000));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  await act(async () => { await rendered.result.current.refetch({ cancelRefetch: false }); });
  expect(fetchSpy).toHaveBeenCalledTimes(2);

  monotonicNow = 300_001;
  await act(async () => vi.advanceTimersByTimeAsync(180_001));
  focusManager.setFocused(true);
  await act(async () => vi.advanceTimersByTimeAsync(0));

  expect(fetchSpy).toHaveBeenCalledTimes(2);
  expect(rendered.result.current.automaticPollingStopped).toBe(true);
});

test("a disabled batch query and a batch without data do not start polling", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const never = deferred<Response>();
  const fetchSpy = vi.fn(async () => never.promise);
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const disabled = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: false,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });

  await act(async () => vi.advanceTimersByTimeAsync(10_000));
  expect(fetchSpy).not.toHaveBeenCalled();
  disabled.unmount();

  const pending = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(10_000));
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  pending.unmount();
  never.resolve(Response.json(processingBatch));
  await act(async () => vi.advanceTimersByTimeAsync(0));
});

test("automatic batch polling stops at five minutes while manual refetch remains available", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const fetchSpy = vi.fn(async () => Response.json(processingBatch));
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  await act(async () => vi.advanceTimersByTimeAsync(298_000));
  expect(fetchSpy).toHaveBeenCalledTimes(150);
  await act(async () => vi.advanceTimersByTimeAsync(2_000));
  expect(fetchSpy).toHaveBeenCalledTimes(150);
  expect(rendered.result.current.automaticPollingStopped).toBe(true);

  await act(async () => { await rendered.result.current.refetch(); });
  expect(fetchSpy).toHaveBeenCalledTimes(151);
  onlineManager.setOnline(false);
  onlineManager.setOnline(true);
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  expect(fetchSpy).toHaveBeenCalledTimes(151);
});

test("a delayed automatic timer rechecks the monotonic deadline before fetching", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let monotonicNow = 0;
  vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
  const fetchSpy = vi.fn(async () => Response.json(processingBatch));
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  monotonicNow = 300_001;
  await act(async () => vi.advanceTimersByTimeAsync(2_000));

  expect(fetchSpy).toHaveBeenCalledTimes(1);
});

test("moving the wall clock backward cannot extend automatic batch polling", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(100_000);
  let monotonicNow = 0;
  vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
  const fetchSpy = vi.fn(async () => Response.json(processingBatch));
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  vi.setSystemTime(-1_000_000);
  monotonicNow = 300_001;
  await act(async () => vi.advanceTimersByTimeAsync(2_000));

  expect(fetchSpy).toHaveBeenCalledTimes(1);
});

test("session abort stops polling after a processing batch has been cached", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const fetchSpy = vi.fn(async () => Response.json(processingBatch));
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(rendered.result.current.data?.status).toBe("processing"));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  act(() => session.abort());
  await act(async () => vi.advanceTimersByTimeAsync(10_000));

  expect(fetchSpy).toHaveBeenCalledTimes(1);
  expect(rendered.result.current.fetchStatus).toBe("idle");
});

test("unmounting aborts a pending knowledge batch request", async () => {
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requestSignal = (input as Request).signal;
    return await new Promise<Response>((_resolve, reject) => {
      requestSignal?.addEventListener(
        "abort",
        () => reject(requestSignal?.reason ?? new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    });
  }));
  const client = queryClient();
  const session = new AbortController();
  const rendered = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await waitFor(() => expect(requestSignal).toBeDefined());

  rendered.unmount();

  await waitFor(() => expect(requestSignal?.aborted).toBe(true));
  await vi.waitFor(() => expect(client.isFetching()).toBe(0));
});

test("session abort cancels a pending knowledge batch request", async () => {
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requestSignal = (input as Request).signal;
    return await new Promise<Response>((_resolve, reject) => {
      requestSignal?.addEventListener(
        "abort",
        () => reject(requestSignal?.reason ?? new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    });
  }));
  const client = queryClient();
  const session = new AbortController();
  renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await waitFor(() => expect(requestSignal).toBeDefined());

  act(() => session.abort());

  await waitFor(() => expect(requestSignal?.aborted).toBe(true));
  await vi.waitFor(() => expect(client.isFetching()).toBe(0));
});

test("a batch query inherits the global one-retry policy", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let attempts = 0;
  vi.stubGlobal("fetch", vi.fn(async () => {
    attempts += 1;
    if (attempts === 1) {
      return Response.json({
        code: "temporarily_unavailable",
        message: "暂时不可用",
        traceId: "trace-batch-retry",
      }, { status: 503, headers: { "X-Request-ID": "trace-batch-retry" } });
    }
    return Response.json({ ...processingBatch, status: "completed", readyCount: 1 });
  }));
  const client = createAppQueryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeBatchQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    enabled: true,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });

  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(result.current.failureCount).toBe(1));
  await act(async () => vi.advanceTimersByTimeAsync(1_000));
  await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(attempts).toBe(2);
  expect(result.current.error).toBeNull();
  expect(result.current.data?.status).toBe("completed");
});

test("knowledge resource caches stay isolated across organizations", () => {
  const queryClient = new QueryClient();
  const projectId = "00000000-0000-4000-8000-000000004001";
  const organizationA = "00000000-0000-4000-8000-000000002001";
  const organizationB = "00000000-0000-4000-8000-000000002002";

  queryClient.setQueryData(
    knowledgeKeys.resources(organizationA, projectId),
    { pages: [{ items: [{ title: "组织 A 私有资料" }] }] },
  );

  expect(queryClient.getQueryData(
    knowledgeKeys.resources(organizationB, projectId),
  )).toBeUndefined();
});

test("knowledge search keys isolate tenant and search inputs", () => {
  const maybeSearchKey = Reflect.get(knowledgeKeys, "search");
  expect(maybeSearchKey).toBeTypeOf("function");
  const searchKey = maybeSearchKey as (
    organizationId: string,
    projectId: string,
    query: string,
    limit: number,
  ) => readonly unknown[];
  const projectId = "00000000-0000-4000-8000-000000004001";

  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-b", projectId, "租约", 8),
  );
  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-a", projectId, "索引", 8),
  );
  expect(searchKey("org-a", projectId, "租约", 8)).not.toEqual(
    searchKey("org-a", projectId, "租约", 20),
  );
});

test("citation context keys isolate tenant, project, resource version, and chunk", () => {
  expect(knowledgeKeys.searches("org-a", "project-a")).toEqual([
    "project-knowledge", "org-a", "project-a", "search",
  ]);
  expect(knowledgeKeys.citationContext(
    "org-a", "project-a", "resource-a", "version-a", "chunk-a",
  )).toEqual([
    "project-knowledge",
    "org-a",
    "project-a",
    "citation-context",
    "resource-a",
    "version-a",
    "chunk-a",
  ]);
  expect(knowledgeKeys.citationContext(
    "org-b", "project-a", "resource-a", "version-a", "chunk-a",
  )).not.toEqual(knowledgeKeys.citationContext(
    "org-a", "project-a", "resource-a", "version-a", "chunk-a",
  ));
});

test("the citation hook requests the exact citation and stores it under its full key", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(validContext);
  }));
  const client = queryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeChunkContextQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(requests).toHaveLength(1);
  expect(new URL(requests[0]!.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/resources/${RESOURCE_ID}/chunks/${CHUNK_ID}`,
  );
  expect(client.getQueryData(knowledgeKeys.citationContext(
    "org-a", PROJECT_ID, RESOURCE_ID, RESOURCE_VERSION_ID, CHUNK_ID,
  ))).toEqual(validContext);
});

test("remounting a citation context always reauthorizes", async () => {
  const requests: Request[] = [];
  const refreshedContext = {
    ...validContext,
    hit: { ...validContext.hit, text: "重新授权后的原文" },
  } as const;
  const reauthorization = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return requests.length === 1
      ? Response.json(validContext)
      : reauthorization.promise;
  }));
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, refetchOnMount: false },
    },
  });
  const session = new AbortController();
  const props = {
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  };

  const first = renderHook(() => useKnowledgeChunkContextQuery(props), {
    wrapper: wrapper(client),
  });
  await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
  first.unmount();
  const second = renderHook(() => useKnowledgeChunkContextQuery(props), {
    wrapper: wrapper(client),
  });

  try {
    await waitFor(() => expect(requests).toHaveLength(2));
    act(() => reauthorization.resolve(Response.json(refreshedContext)));
    await waitFor(() => expect(second.result.current.data).toEqual(refreshedContext));
    expect(second.result.current.fetchStatus).toBe("idle");
  } finally {
    reauthorization.resolve(Response.json(refreshedContext));
    second.unmount();
    await vi.waitFor(() => expect(client.isFetching()).toBe(0));
  }
});

test("a successful citation context stays stale despite conflicting client defaults", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(validContext)));
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, refetchOnMount: false },
    },
  });
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeChunkContextQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.isStale).toBe(true);
});

test("session abort cancels a pending citation context request", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    return await new Promise<Response>((_resolve, reject) => {
      request.signal.addEventListener("abort", () => {
        reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
  }));
  const session = new AbortController();
  const client = queryClient();
  renderHook(() => useKnowledgeChunkContextQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await waitFor(() => expect(requests).toHaveLength(1));
  session.abort(new DOMException("Session ended", "AbortError"));
  await waitFor(() => expect(requests[0]!.signal.aborted).toBe(true));
});

test("unmounting a citation context aborts its pending Query request", async () => {
  const requests: Request[] = [];
  const fetchSettled = deferred<void>();
  let resolveFetch: ((response: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    try {
      return await new Promise<Response>((resolve, reject) => {
        resolveFetch = resolve;
        request.signal.addEventListener("abort", () => {
          reject(request.signal.reason ?? new DOMException("Aborted", "AbortError"));
        }, { once: true });
      });
    } finally {
      fetchSettled.resolve();
    }
  }));
  const session = new AbortController();
  const client = queryClient();
  const rendered = renderHook(() => useKnowledgeChunkContextQuery({
    organizationId: "org-a",
    projectId: PROJECT_ID,
    resourceId: RESOURCE_ID,
    resourceVersionId: RESOURCE_VERSION_ID,
    chunkId: CHUNK_ID,
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await waitFor(() => expect(requests).toHaveLength(1));

  try {
    rendered.unmount();
    await waitFor(() => expect(requests[0]!.signal.aborted).toBe(true));
  } finally {
    resolveFetch?.(Response.json(validContext));
    await fetchSettled.promise;
    await vi.waitFor(() => expect(client.isFetching()).toBe(0));
  }
});

test("knowledge search stays idle until a submitted search exists", () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();

  const { result } = renderHook(() => useKnowledgeSearchQuery({
    organizationId: "org-a",
    projectId: "00000000-0000-4000-8000-000000004001",
    search: null,
    csrfToken: "csrf-search",
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });

  expect(result.current.fetchStatus).toBe("idle");
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("knowledge search queries isolate organization, project, query, and limit caches", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json({ retrievalMode: "hybrid", results: [] });
  }));
  const client = queryClient();
  const session = new AbortController();
  const cases = [
    { organizationId: "org-a", projectId: "project-a", query: "租约", limit: 8 },
    { organizationId: "org-b", projectId: "project-a", query: "租约", limit: 8 },
    { organizationId: "org-a", projectId: "project-b", query: "租约", limit: 8 },
    { organizationId: "org-a", projectId: "project-a", query: "索引", limit: 8 },
    { organizationId: "org-a", projectId: "project-a", query: "租约", limit: 20 },
  ];

  for (const searchCase of cases) {
    const rendered = renderHook(() => useKnowledgeSearchQuery({
      organizationId: searchCase.organizationId,
      projectId: searchCase.projectId,
      search: { query: searchCase.query, limit: searchCase.limit },
      csrfToken: "csrf-search",
      sessionSignal: session.signal,
    }), { wrapper: wrapper(client) });
    await waitFor(() => expect(rendered.result.current.isSuccess).toBe(true));
    rendered.unmount();
  }

  expect(requests).toHaveLength(cases.length);
  for (const searchCase of cases) {
    expect(client.getQueryData(knowledgeKeys.search(
      searchCase.organizationId,
      searchCase.projectId,
      searchCase.query,
      searchCase.limit,
    ))).toEqual({ retrievalMode: "hybrid", results: [] });
  }
  expect(new URL(requests[0]?.url ?? "").pathname).toContain("/projects/project-a/knowledge/search");
  expect(requests[0]?.headers.get("X-CSRF-Token")).toBe("csrf-search");
});

test("knowledge search queries preserve session cancellation", async () => {
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requestSignal = (input as Request).signal;
    return await new Promise<Response>((_resolve, reject) => {
      requestSignal?.addEventListener(
        "abort",
        () => reject(requestSignal?.reason ?? new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    });
  }));
  const client = queryClient();
  const session = new AbortController();
  const { result } = renderHook(() => useKnowledgeSearchQuery({
    organizationId: "org-a",
    projectId: "project-a",
    search: { query: "权限撤销", limit: 8 },
    csrfToken: "csrf-search",
    sessionSignal: session.signal,
  }), { wrapper: wrapper(client) });
  await waitFor(() => expect(requestSignal).toBeDefined());

  act(() => session.abort());

  await waitFor(() => expect(result.current.error).toMatchObject({
    kind: "aborted",
    context: "POST /api/v1/projects/{project_id}/knowledge/search",
  }));
});

test("switching submitted search aborts the old Query and observes only the new response", async () => {
  const requests: Request[] = [];
  const queryA = deferred<Response>();
  const lateResponseConsumed = deferred<void>();
  const lateResponse = Response.json({ retrievalMode: "keyword_fallback", results: [] });
  const readLateResponse = lateResponse.text.bind(lateResponse);
  vi.spyOn(lateResponse, "text").mockImplementation(async () => {
    const body = await readLateResponse();
    lateResponseConsumed.resolve();
    return body;
  });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    const body = await request.clone().json() as { query: string };
    return body.query === "查询甲"
      ? queryA.promise
      : Response.json({ retrievalMode: "hybrid", results: [] });
  }));
  const client = queryClient();
  const session = new AbortController();
  const { result, rerender } = renderHook(
    ({ query }) => useKnowledgeSearchQuery({
      organizationId: "org-a",
      projectId: "project-a",
      search: { query, limit: 10 },
      csrfToken: "csrf-search",
      sessionSignal: session.signal,
    }),
    { initialProps: { query: "查询甲" }, wrapper: wrapper(client) },
  );
  await waitFor(() => expect(requests).toHaveLength(1));
  rerender({ query: "查询乙" });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(requests[0]!.signal.aborted).toBe(true);
  await act(async () => {
    queryA.resolve(lateResponse);
    await lateResponseConsumed.promise;
  });
  expect(lateResponse.bodyUsed).toBe(true);
  await waitFor(() => {
    expect(result.current.data).toEqual({ retrievalMode: "hybrid", results: [] });
  });
});
