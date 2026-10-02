import {
  focusManager,
  onlineManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, render, renderHook, waitFor } from "@testing-library/react";
import { startTransition, Suspense, type ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import type { IdentityContext } from "../../src/api/auth.ts";
import { ApiError } from "../../src/api/errors.ts";
import { createAppQueryClient } from "../../src/app/queryClient.ts";
import type {
  KnowledgeBatchDetail,
  KnowledgeUploadBatch,
  KnowledgeUploadCompletion,
  KnowledgeUploadInstruction,
} from "../../src/api/knowledgeUploads.ts";
import { prepareKnowledgeFiles, type PreparedKnowledgeFile } from "../../src/lib/knowledgeUpload.ts";
import {
  type KnowledgeUploadDependencies,
  useKnowledgeUploadBatch,
} from "../../src/hooks/useKnowledgeUploadBatch.ts";
import { knowledgeKeys, useKnowledgeResourcesQuery } from "../../src/queries/knowledge.ts";
import { SessionProvider, useSession } from "../../src/session/SessionContext.tsx";

const ORGANIZATION_ID = "00000000-0000-4000-8000-000000002001";
const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const BATCH_1 = "00000000-0000-4000-8000-000000008001";
const BATCH_2 = "00000000-0000-4000-8000-000000008002";
const IDENTITY = {
  user: {
    id: "00000000-0000-4000-8000-000000001001",
    email: "demo@cairn.dev",
    displayName: "演示用户",
  },
  organization: { id: ORGANIZATION_ID, slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
  csrfToken: "csrf",
} satisfies IdentityContext;

function file(name: string, contents = name) {
  return new File([contents], name, { type: "application/pdf" });
}

function instruction(index: number, batch = 1): KnowledgeUploadInstruction {
  return {
    uploadId: `00000000-0000-4000-8000-0000000001${batch}${index}`,
    itemId: `00000000-0000-4000-8000-0000000002${batch}${index}`,
    method: "PUT",
    url: `https://objects.example.test/session-${batch}/file-${index}`,
    headers: { "x-upload-token": `signed-${batch}-${index}` },
    expiresAt: "2026-09-04T10:00:00Z",
  };
}

function prepared(files: readonly File[]): PreparedKnowledgeFile[] {
  return files.map((selected, index) => ({
    file: selected,
    intent: {
      fileName: selected.name,
      mediaType: "application/pdf",
      sizeBytes: selected.size,
      sha256: `${index}`.padStart(64, "0"),
    },
  }));
}

function uploadBatch(files: readonly File[], batch = 1): KnowledgeUploadBatch {
  return {
    batchId: batch === 1 ? BATCH_1 : BATCH_2,
    uploads: files.map((_selected, index) => instruction(index, batch)),
  };
}

function batchDetail(
  files: readonly File[],
  status: KnowledgeBatchDetail["status"] = "processing",
  itemStatuses: KnowledgeBatchDetail["items"][number]["status"][] = files.map(() => "queued"),
  batch = 1,
): KnowledgeBatchDetail {
  const items = files.map((selected, index) => ({
    id: instruction(index, batch).itemId,
    parentItemId: null,
    normalizedPath: selected.name,
    mediaType: "application/pdf",
    sizeBytes: selected.size,
    status: itemStatuses[index] ?? "queued",
    resourceId: null,
    resourceVersionId: null,
    errorCode: itemStatuses[index] === "failed" ? "parse_failed" : null,
    errorDetail: itemStatuses[index] === "failed" ? "无法解析 <script>alert(1)</script>" : null,
    createdAt: "2026-09-04T09:00:00Z",
    completedAt: status === "processing" ? null : "2026-09-04T09:01:00Z",
  }));
  return {
    id: batch === 1 ? BATCH_1 : BATCH_2,
    status,
    itemCount: items.length,
    readyCount: items.filter(({ status: itemStatus }) => itemStatus === "ready").length,
    failedCount: items.filter(({ status: itemStatus }) => itemStatus === "failed").length,
    createdAt: "2026-09-04T09:00:00Z",
    completedAt: status === "processing" ? null : "2026-09-04T09:01:00Z",
    items,
  };
}

function defaultDependencies(): KnowledgeUploadDependencies {
  return {
    prepareFiles: vi.fn<KnowledgeUploadDependencies["prepareFiles"]>(async (
      files, _signal, onHashing,
    ) => {
      files.forEach((_selected, index) => onHashing(index));
      return prepared(files);
    }),
    createBatch: vi.fn<KnowledgeUploadDependencies["createBatch"]>(async ({ intents }) => uploadBatch(
      intents.map(({ fileName }) => file(fileName)),
    )),
    putObject: vi.fn<KnowledgeUploadDependencies["putObject"]>(async ({ file: selected, onProgress }) => {
      onProgress({ loaded: selected.size, total: selected.size, percent: 100 });
    }),
    complete: vi.fn<KnowledgeUploadDependencies["complete"]>(async ({ uploadId, itemId, batchId }) => ({
      uploadId,
      itemId,
      batchId,
      status: "queued" as const,
      resourceId: null,
      resourceVersionId: null,
    })),
    now: () => 1234,
  };
}

function queryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper(client: QueryClient, resources?: {
  sessionSignal: AbortSignal;
}) {
  function ResourceObserver() {
    useKnowledgeResourcesQuery(
      ORGANIZATION_ID,
      PROJECT_ID,
      resources!.sessionSignal,
    );
    return null;
  }
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        {resources === undefined ? null : <ResourceObserver />}
        {children}
      </QueryClientProvider>
    );
  };
}

function renderUpload(options: {
  dependencies?: KnowledgeUploadDependencies;
  session?: AbortController;
  client?: QueryClient;
  onAccessUnavailable?: (error: ApiError) => void;
  withResources?: boolean;
} = {}) {
  const session = options.session ?? new AbortController();
  const client = options.client ?? queryClient();
  const onAccessUnavailable = options.onAccessUnavailable ?? vi.fn();
  const dependencies = options.dependencies ?? defaultDependencies();
  const rendered = renderHook(() => useKnowledgeUploadBatch({
    organizationId: ORGANIZATION_ID,
    projectId: PROJECT_ID,
    csrfToken: "csrf",
    sessionSignal: session.signal,
    onAccessUnavailable,
    dependencies,
  }), {
    wrapper: wrapper(client, options.withResources ? { sessionSignal: session.signal } : undefined),
  });
  return { ...rendered, session, client, dependencies, onAccessUnavailable };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function containsFile(value: unknown, seen = new Set<unknown>()): boolean {
  if (value instanceof File) return true;
  if (value === null || typeof value !== "object" || seen.has(value)) return false;
  seen.add(value);
  return Object.values(value).some((child) => containsFile(child, seen));
}

afterEach(() => {
  focusManager.setFocused(undefined);
  onlineManager.setOnline(true);
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test.each([
  ["read", "reselect"],
  ["digest", "reselect"],
  ["read", "session remount"],
  ["digest", "session remount"],
] as const)("native %s stays exclusive across cancelled %s operations", async (stage, replacement) => {
  const nativeGate = deferred<ArrayBuffer>();
  const reads: string[] = [];
  const oldFile = file("old-native.pdf");
  const skippedFile = file("cancelled-queue.pdf");
  const nextFile = file("replacement-native.pdf");
  for (const selected of [oldFile, skippedFile, nextFile]) {
    Object.defineProperty(selected, "arrayBuffer", { configurable: true, value: async () => {
      reads.push(selected.name);
      return selected === oldFile && stage === "read"
        ? nativeGate.promise
        : new Uint8Array([1, 2, 3]).buffer;
    } });
  }
  const realDigest = crypto.subtle.digest.bind(crypto.subtle);
  let digestCalls = 0;
  vi.spyOn(crypto.subtle, "digest").mockImplementation((...args) => {
    digestCalls += 1;
    return stage === "digest" && digestCalls === 1 ? nativeGate.promise : realDigest(...args);
  });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(batchDetail([nextFile]))));
  const oldDependencies = { ...defaultDependencies(), prepareFiles: prepareKnowledgeFiles };
  const original = renderUpload({ dependencies: oldDependencies });
  let current = original;
  const operations: Promise<void>[] = [];
  try {
    act(() => original.result.current.select([oldFile]));
    act(() => { operations.push(original.result.current.start()); });
    await waitFor(() => expect(stage === "read" ? reads.length : digestCalls).toBe(1));
    if (replacement === "session remount") {
      act(() => original.session.abort());
      original.unmount();
      current = renderUpload({ dependencies: {
        ...defaultDependencies(), prepareFiles: prepareKnowledgeFiles,
      } });
    } else {
      act(() => original.result.current.cancel());
    }
    act(() => current.result.current.select([skippedFile]));
    act(() => { operations.push(current.result.current.start()); });
    await act(async () => { await Promise.resolve(); });
    act(() => current.result.current.cancel());
    act(() => current.result.current.select([nextFile]));
    act(() => { operations.push(current.result.current.start()); });
    await act(async () => { await Promise.resolve(); });

    expect(reads).toEqual(["old-native.pdf"]);
    expect(digestCalls).toBe(stage === "read" ? 0 : 1);
    expect(oldDependencies.createBatch).not.toHaveBeenCalled();
    expect(current.dependencies.createBatch).not.toHaveBeenCalled();

    nativeGate.resolve(new ArrayBuffer(stage === "digest" ? 32 : 3));
    await act(async () => { await Promise.all(operations); });
    expect(reads).toEqual(["old-native.pdf", "replacement-native.pdf"]);
    expect(digestCalls).toBe(stage === "read" ? 1 : 2);
    expect(current.dependencies.createBatch).toHaveBeenCalledTimes(1);
    expect(current.result.current.files.map(({ file: selected }) => selected.name))
      .toEqual(["replacement-native.pdf"]);
    expect(current.result.current.error).toBeNull();
    if (replacement === "session remount") expect(oldDependencies.createBatch).not.toHaveBeenCalled();
  } finally {
    nativeGate.resolve(new ArrayBuffer(32));
    await act(async () => { await Promise.all(operations); });
    current.unmount();
  }
});

test.each(["processing", "completed"] as const)(
  "identical %s recovery clears batch error only after the refresh succeeds",
  async (status) => {
    const selected = file("unchanged-recovery.pdf");
    const detail = batchDetail([selected], status, [status === "completed" ? "ready" : "processing"]);
    const recovery = deferred<Response>();
    let attempts = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      attempts += 1;
      if (attempts === 1) return Response.json(detail);
      if (attempts <= 4) {
        return Response.json({
          message: "数据库暂时不可用", code: "database_unavailable", traceId: "trace-stale-batch",
        }, { status: 503, headers: { "X-Request-ID": "trace-stale-batch" } });
      }
      return recovery.promise;
    }));
    const client = createAppQueryClient();
    client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retryDelay: 0 } });
    const { result } = renderUpload({ client });
    act(() => result.current.select([selected]));
    await act(async () => result.current.start());
    await waitFor(() => expect(result.current.batch?.status).toBe(status));
    const originalData = result.current.batch;
    act(() => result.current.cancel());
    await act(async () => result.current.refreshBatch());
    await waitFor(() => expect(result.current.batchError?.traceId).toBe("trace-stale-batch"));
    let refreshing!: Promise<void>;
    try {
      act(() => { refreshing = result.current.refreshBatch(); });
      await waitFor(() => expect(attempts).toBe(5));
      expect(result.current.batchError?.traceId).toBe("trace-stale-batch");
      expect(result.current.batch).toBe(originalData);
      recovery.resolve(Response.json(detail));
      await act(async () => refreshing);
      await waitFor(() => expect(result.current.batchError).toBeNull());
      expect(result.current.batch).toBe(originalData);
      expect(result.current.files[0]?.phase).toBe(status === "completed" ? "ready" : "processing");
    } finally {
      recovery.resolve(Response.json(detail));
      await act(async () => refreshing);
    }
  },
);

test("validation blocks hashing and every external upload API", async () => {
  vi.stubGlobal("fetch", vi.fn());
  const dependencies = defaultDependencies();
  const { result } = renderUpload({ dependencies });

  act(() => result.current.select([]));
  await act(async () => result.current.start());

  expect(result.current.issues).toEqual([{ index: null, error: "一次必须上传 1 至 20 个文件" }]);
  expect(dependencies.prepareFiles).not.toHaveBeenCalled();
  expect(dependencies.createBatch).not.toHaveBeenCalled();
  expect(dependencies.putObject).not.toHaveBeenCalled();
  expect(dependencies.complete).not.toHaveBeenCalled();
});

test("hashes serially before create, maps request order, limits PUT concurrency to two, and completes independently", async () => {
  const files = [file("one.pdf"), file("two.pdf"), file("three.pdf")];
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(batchDetail(files))));
  const hashGates = files.map(() => deferred<void>());
  const putGates = files.map(() => deferred<void>());
  const hashing: number[] = [];
  let activePuts = 0;
  let maxActivePuts = 0;
  const dependencies = defaultDependencies();
  dependencies.prepareFiles = vi.fn(async (selected, signal, onHashing) => {
    const result: PreparedKnowledgeFile[] = [];
    for (const [index, selectedFile] of selected.entries()) {
      if (signal.aborted) throw new ApiError("aborted", "请求已被取消");
      hashing.push(index);
      onHashing(index);
      await hashGates[index]!.promise;
      result.push(prepared([selectedFile])[0]!);
    }
    return result;
  });
  dependencies.createBatch = vi.fn(async () => uploadBatch(files));
  dependencies.putObject = vi.fn(async ({ instruction: current, file: selected, onProgress }) => {
    const index = files.indexOf(selected);
    activePuts += 1;
    maxActivePuts = Math.max(maxActivePuts, activePuts);
    onProgress({ loaded: 2, total: 5, percent: 40 });
    if (index === 1) {
      activePuts -= 1;
      throw new ApiError("network", "文件直传失败，请重试");
    }
    await putGates[index]!.promise;
    expect(current.itemId).toBe(instruction(index).itemId);
    activePuts -= 1;
  });
  dependencies.complete = vi.fn<KnowledgeUploadDependencies["complete"]>(async ({ uploadId, itemId, batchId }) => ({
    uploadId, itemId, batchId, status: "queued" as const, resourceId: null, resourceVersionId: null,
  }));
  const { result } = renderUpload({ dependencies });

  act(() => result.current.select(files));
  let start!: Promise<void>;
  act(() => { start = result.current.start(); });
  await waitFor(() => expect(hashing).toEqual([0]));
  expect(dependencies.createBatch).not.toHaveBeenCalled();
  hashGates[0]!.resolve();
  await waitFor(() => expect(hashing).toEqual([0, 1]));
  expect(dependencies.createBatch).not.toHaveBeenCalled();
  hashGates[1]!.resolve();
  await waitFor(() => expect(hashing).toEqual([0, 1, 2]));
  expect(dependencies.createBatch).not.toHaveBeenCalled();
  hashGates[2]!.resolve();

  await waitFor(() => expect(maxActivePuts).toBe(2));
  expect(result.current.files[0]?.progress).toEqual({ loaded: 2, total: 5, percent: 40 });
  expect(dependencies.complete).not.toHaveBeenCalled();
  putGates[0]!.resolve();
  await waitFor(() => expect(dependencies.complete).toHaveBeenCalledWith(expect.objectContaining({
    projectId: PROJECT_ID,
    batchId: BATCH_1,
    uploadId: instruction(0).uploadId,
    itemId: instruction(0).itemId,
    csrfToken: "csrf",
  })));
  await waitFor(() => expect(dependencies.putObject).toHaveBeenCalledTimes(3));
  expect(maxActivePuts).toBe(2);
  putGates[2]!.resolve();
  await act(async () => start);

  expect(result.current.files.map(({ phase }) => phase)).toEqual(["queued", "failed", "queued"]);
  expect(result.current.files[1]?.failureStage).toBe("transfer");
});

test("does not start the batch query while every PUT is blocked or after every PUT fails", async () => {
  const files = [file("blocked-one.pdf"), file("blocked-two.pdf")];
  const putGates = files.map(() => deferred<void>());
  const fetchSpy = vi.fn(async () => Response.json(batchDetail(files)));
  vi.stubGlobal("fetch", fetchSpy);
  const dependencies = defaultDependencies();
  dependencies.putObject = vi.fn(async ({ file: selected }) => {
    await putGates[files.indexOf(selected)]!.promise;
  });
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select(files));
  let start!: Promise<void>;
  act(() => { start = result.current.start(); });
  await waitFor(() => expect(dependencies.putObject).toHaveBeenCalledTimes(2));

  expect(fetchSpy).not.toHaveBeenCalled();
  putGates.forEach((gate) => gate.reject(new ApiError("network", "直传失败")));
  await act(async () => start);

  expect(fetchSpy).not.toHaveBeenCalled();
  expect(result.current.batchId).toBeNull();
});

test("the first successful complete publishes the batch and enables its Query boundary", async () => {
  const selected = file("first-complete.pdf");
  const completeGate = deferred<KnowledgeUploadCompletion>();
  const fetchSpy = vi.fn(async () => Response.json(batchDetail([selected])));
  vi.stubGlobal("fetch", fetchSpy);
  const dependencies = defaultDependencies();
  dependencies.complete = vi.fn(async () => completeGate.promise);
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select([selected]));
  let start!: Promise<void>;
  act(() => { start = result.current.start(); });
  await waitFor(() => expect(dependencies.complete).toHaveBeenCalledTimes(1));

  expect(fetchSpy).not.toHaveBeenCalled();
  completeGate.resolve({
    uploadId: instruction(0).uploadId,
    itemId: instruction(0).itemId,
    batchId: BATCH_1,
    status: "queued",
    resourceId: null,
    resourceVersionId: null,
  });
  await act(async () => start);
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));

  expect(result.current.batchId).toBe(BATCH_1);
});

test.each(["create", "complete"] as const)(
  "%s session-invalid errors publish through the real Mutation cache error channel",
  async (stage) => {
    const selected = file(`${stage}-session.pdf`);
    const unsafeCause = { body: "SECRET provider response", signedUrl: instruction(0).url };
    const sessionError = new ApiError("http", "会话已过期", {
      status: 401,
      code: "session_invalid",
      traceId: `trace-${stage}-session`,
      retryAfterSeconds: 9,
      cause: unsafeCause,
    });
    const dependencies = defaultDependencies();
    if (stage === "create") {
      dependencies.createBatch = vi.fn(async () => { throw sessionError; });
    } else {
      dependencies.complete = vi.fn(async () => { throw sessionError; });
    }
    vi.stubGlobal("fetch", vi.fn());
    const client = queryClient();
    const mutationErrors: unknown[] = [];
    const unsubscribe = client.getMutationCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "error") {
        mutationErrors.push(event.action.error);
      }
    });
    const { result } = renderUpload({ dependencies, client });
    act(() => result.current.select([selected]));
    await act(async () => result.current.start());

    expect(mutationErrors).toHaveLength(1);
    const published = mutationErrors[0];
    expect(published).toMatchObject({
      kind: "http",
      message: "会话已过期",
      status: 401,
      code: "session_invalid",
      traceId: `trace-${stage}-session`,
      retryAfterSeconds: 9,
    });
    expect(published).not.toBe(sessionError);
    expect((published as ApiError).cause).toBeUndefined();
    const localError = result.current.error ?? result.current.files[0]?.error;
    expect(localError).toMatchObject({ status: 401, code: "session_invalid" });
    expect(localError?.cause).toBeUndefined();
    expect(JSON.stringify({ published, localError })).not.toContain("SECRET provider response");
    expect(JSON.stringify({ published, localError })).not.toContain(instruction(0).url);
    unsubscribe();
  },
);

test("an ordinary create failure remains eligible for an explicit fresh attempt", async () => {
  const selected = file("create-retry.pdf");
  const dependencies = defaultDependencies();
  dependencies.createBatch = vi.fn()
    .mockRejectedValueOnce(new ApiError("network", "无法创建上传批次，请重试"))
    .mockResolvedValueOnce(uploadBatch([selected]));
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(batchDetail([selected]))));
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select([selected]));
  await act(async () => result.current.start());

  await act(async () => result.current.start());

  expect(dependencies.createBatch).toHaveBeenCalledTimes(2);
  expect(dependencies.putObject).toHaveBeenCalledTimes(1);
  expect(result.current.batchId).toBe(BATCH_1);
});

test.each(["success", "failure"] as const)(
  "ordinary upload %s never exposes capabilities or Files through the transient Mutation cache",
  async (resultKind) => {
    const selected = file(`mutation-${resultKind}.pdf`);
    const sensitiveInstruction = instruction(0);
    const dependencies = defaultDependencies();
    dependencies.createBatch = vi.fn(async () => ({
      batchId: BATCH_1,
      uploads: [{
        ...sensitiveInstruction,
        url: `${sensitiveInstruction.url}?signature=private-${resultKind}`,
        headers: { "x-upload-token": `private-header-${resultKind}` },
      }],
    }));
    if (resultKind === "failure") {
      dependencies.complete = vi.fn(async () => {
        throw new ApiError("network", "无法确认文件上传，请重试", {
          cause: {
            signedUrl: `${sensitiveInstruction.url}?signature=private-${resultKind}`,
            headers: { "x-upload-token": `private-header-${resultKind}` },
            file: selected,
          },
        });
      });
    }
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(batchDetail([selected]))));
    const client = queryClient();
    const snapshots: Array<{
      mutationKey: readonly unknown[] | undefined;
      variables: unknown;
      data: unknown;
      error: unknown;
    }> = [];
    const unsubscribe = client.getMutationCache().subscribe((event) => {
      if (!("mutation" in event) || event.mutation === undefined) return;
      snapshots.push({
        mutationKey: event.mutation.options.mutationKey,
        variables: event.mutation.state.variables,
        data: event.mutation.state.data,
        error: event.mutation.state.error,
      });
    });
    const { result } = renderUpload({ dependencies, client });
    act(() => result.current.select([selected]));
    await act(async () => result.current.start());

    expect(client.getMutationCache().getAll()).toHaveLength(0);
    expect(snapshots.every(({ variables, data }) => variables === undefined && data === undefined))
      .toBe(true);
    expect(snapshots.every(({ error }) => !(error instanceof ApiError) || error.cause === undefined))
      .toBe(true);
    expect(snapshots.some(({ mutationKey, variables, data, error }) =>
      containsFile({ mutationKey, variables, data, error })
    )).toBe(false);
    const serializedCacheHistory = JSON.stringify(snapshots);
    expect(serializedCacheHistory).not.toContain("objects.example.test");
    expect(serializedCacheHistory).not.toContain("private-header");
    expect(serializedCacheHistory).not.toContain(selected.name);
    if (resultKind === "success") expect(snapshots).toHaveLength(0);
    else expect(snapshots.length).toBeGreaterThan(0);
    unsubscribe();
  },
);

test("an identity change aborts and generation-disqualifies the old in-flight operation", async () => {
  const oldCreate = deferred<KnowledgeUploadBatch>();
  const old404 = new ApiError("http", "旧项目不可见", { status: 404 });
  let oldSignal: AbortSignal | undefined;
  const dependencies = defaultDependencies();
  dependencies.createBatch = vi.fn(async ({ signal }) => {
    oldSignal = signal;
    return oldCreate.promise;
  });
  const fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  const client = queryClient();
  const session = new AbortController();
  const onAccessUnavailable = vi.fn();
  const rendered = renderHook(
    ({ organizationId, projectId }) => useKnowledgeUploadBatch({
      organizationId,
      projectId,
      csrfToken: "csrf",
      sessionSignal: session.signal,
      onAccessUnavailable,
      dependencies,
    }),
    {
      initialProps: { organizationId: ORGANIZATION_ID, projectId: PROJECT_ID },
      wrapper: wrapper(client),
    },
  );
  act(() => rendered.result.current.select([file("old-project.pdf")]));
  let start!: Promise<void>;
  act(() => { start = rendered.result.current.start(); });
  await waitFor(() => expect(oldSignal).toBeDefined());

  rendered.rerender({
    organizationId: "00000000-0000-4000-8000-000000002002",
    projectId: "00000000-0000-4000-8000-000000004002",
  });

  expect(oldSignal?.aborted).toBe(true);
  expect(rendered.result.current.files).toEqual([]);
  oldCreate.reject(old404);
  await act(async () => start);
  expect(onAccessUnavailable).not.toHaveBeenCalled();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("an uncommitted suspended identity render cannot steal an old operation 404 callback", async () => {
  const oldCreate = deferred<KnowledgeUploadBatch>();
  const suspended = deferred<void>();
  const old404 = new ApiError("http", "旧项目不可见", {
    status: 404,
    traceId: "trace-old-project",
  });
  const dependencies = defaultDependencies();
  dependencies.createBatch = vi.fn(async () => oldCreate.promise);
  vi.stubGlobal("fetch", vi.fn());
  const client = queryClient();
  const session = new AbortController();
  const callbackA = vi.fn();
  const callbackB = vi.fn();
  const renderedB = vi.fn();
  let committedUpload: ReturnType<typeof useKnowledgeUploadBatch> | undefined;

  function Harness({
    organizationId,
    projectId,
    onAccessUnavailable,
    suspend,
  }: {
    organizationId: string;
    projectId: string;
    onAccessUnavailable(error: ApiError): void;
    suspend: boolean;
  }) {
    const upload = useKnowledgeUploadBatch({
      organizationId,
      projectId,
      csrfToken: "csrf",
      sessionSignal: session.signal,
      onAccessUnavailable,
      dependencies,
    });
    if (suspend) {
      renderedB();
      throw suspended.promise;
    }
    committedUpload = upload;
    return null;
  }

  const rendered = render(
    <QueryClientProvider client={client}>
      <Suspense fallback={<div>loading identity</div>}>
        <Harness
          organizationId={ORGANIZATION_ID}
          projectId={PROJECT_ID}
          onAccessUnavailable={callbackA}
          suspend={false}
        />
      </Suspense>
    </QueryClientProvider>,
  );
  act(() => committedUpload?.select([file("old-pending.pdf")]));
  let start!: Promise<void>;
  act(() => { start = committedUpload!.start(); });
  await waitFor(() => expect(dependencies.createBatch).toHaveBeenCalledTimes(1));

  act(() => {
    startTransition(() => rendered.rerender(
      <QueryClientProvider client={client}>
        <Suspense fallback={<div>loading identity</div>}>
          <Harness
            organizationId="00000000-0000-4000-8000-000000002002"
            projectId="00000000-0000-4000-8000-000000004002"
            onAccessUnavailable={callbackB}
            suspend
          />
        </Suspense>
      </QueryClientProvider>,
    ));
  });
  await waitFor(() => expect(renderedB).toHaveBeenCalled());

  oldCreate.reject(old404);
  await act(async () => start);

  expect(callbackB).not.toHaveBeenCalled();
  expect(callbackA).toHaveBeenCalledTimes(1);
  expect(callbackA).toHaveBeenCalledWith(expect.objectContaining({
    status: 404,
    traceId: "trace-old-project",
  }));
});

test("an identity change clears a published batch without querying it under the new project", async () => {
  const selected = file("published-old-project.pdf");
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(batchDetail([selected]));
  }));
  const client = queryClient();
  const session = new AbortController();
  const dependencies = defaultDependencies();
  const rendered = renderHook(
    ({ organizationId, projectId }) => useKnowledgeUploadBatch({
      organizationId,
      projectId,
      csrfToken: "csrf",
      sessionSignal: session.signal,
      onAccessUnavailable: vi.fn(),
      dependencies,
    }),
    {
      initialProps: { organizationId: ORGANIZATION_ID, projectId: PROJECT_ID },
      wrapper: wrapper(client),
    },
  );
  act(() => rendered.result.current.select([selected]));
  await act(async () => rendered.result.current.start());
  await waitFor(() => expect(requests).toHaveLength(1));

  const nextProject = "00000000-0000-4000-8000-000000004002";
  rendered.rerender({
    organizationId: "00000000-0000-4000-8000-000000002002",
    projectId: nextProject,
  });
  await waitFor(() => expect(rendered.result.current.batchId).toBeNull());

  expect(rendered.result.current.files).toEqual([]);
  expect(requests.some(({ url }) => url.includes(`/projects/${nextProject}/`) && url.includes(BATCH_1)))
    .toBe(false);
});

test("cancel preserves confirmed processing truth while cancelling an active transfer", async () => {
  const files = [file("confirmed.pdf"), file("active.pdf")];
  const activePut = deferred<void>();
  const dependencies = defaultDependencies();
  dependencies.putObject = vi.fn(async ({ file: selected }) => {
    if (selected === files[1]) await activePut.promise;
  });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(
    batchDetail(files, "processing", ["processing", "awaiting_upload"]),
  )));
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select(files));
  let start!: Promise<void>;
  act(() => { start = result.current.start(); });
  await waitFor(() => expect(result.current.files[0]?.phase).toBe("processing"));
  expect(result.current.files[1]?.phase).toBe("uploading");

  act(() => result.current.cancel());

  expect(result.current.files.map(({ phase }) => phase)).toEqual(["processing", "cancelled"]);
  activePut.resolve();
  await act(async () => start);
});

test("user cancel durably stops batch polling, preserves server facts, and allows manual refresh", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const selected = file("stop-tracking.pdf");
  const fetchSpy = vi.fn(async () => {
    if (fetchSpy.mock.calls.length === 2) {
      return Response.json({
        message: "数据库暂时不可用",
        code: "database_unavailable",
        traceId: "trace-stopped-manual-retry",
      }, { status: 503, headers: { "X-Request-ID": "trace-stopped-manual-retry" } });
    }
    return Response.json(batchDetail([selected], "processing", ["processing"]));
  });
  vi.stubGlobal("fetch", fetchSpy);
  const { result } = renderUpload({ client: createAppQueryClient() });
  act(() => result.current.select([selected]));
  await act(async () => result.current.start());
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(result.current.files[0]?.phase).toBe("processing"));
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  act(() => result.current.cancel());
  await act(async () => vi.advanceTimersByTimeAsync(10_000));
  focusManager.setFocused(false);
  focusManager.setFocused(true);
  onlineManager.setOnline(false);
  onlineManager.setOnline(true);
  await act(async () => vi.advanceTimersByTimeAsync(2_000));

  expect(result.current.batchTrackingStopped).toBe(true);
  expect(result.current.batchId).toBe(BATCH_1);
  expect(result.current.files[0]?.phase).toBe("processing");
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  let manualRefresh!: Promise<void>;
  act(() => { manualRefresh = result.current.refreshBatch(); });
  await act(async () => vi.advanceTimersByTimeAsync(1_000));
  await act(async () => manualRefresh);
  expect(fetchSpy).toHaveBeenCalledTimes(3);
  expect(result.current.batchError).toBeNull();
});

test("the upload controller exposes five-minute expiry without converting processing to failure", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const selected = file("five-minute-processing.pdf");
  const fetchSpy = vi.fn(async () => Response.json(batchDetail(
    [selected], "processing", ["processing"],
  )));
  vi.stubGlobal("fetch", fetchSpy);
  const { result } = renderUpload();
  act(() => result.current.select([selected]));
  await act(async () => result.current.start());
  await act(async () => vi.advanceTimersByTimeAsync(0));
  await vi.waitFor(() => expect(result.current.files[0]?.phase).toBe("processing"));

  await act(async () => vi.advanceTimersByTimeAsync(300_000));

  expect(result.current.batchPollingTimedOut).toBe(true);
  expect(result.current.files[0]?.phase).toBe("processing");
  expect(result.current.files[0]?.error).toBeNull();
  const automaticRequests = fetchSpy.mock.calls.length;
  await act(async () => result.current.refreshBatch());
  expect(fetchSpy).toHaveBeenCalledTimes(automaticRequests + 1);
});

test("a pending first batch GET exposes controller timeout before its response resolves", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  const selected = file("pending-first-batch.pdf");
  const batchResponse = deferred<Response>();
  let requestSignal: AbortSignal | undefined;
  const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
    requestSignal = (input as Request).signal;
    return batchResponse.promise;
  });
  vi.stubGlobal("fetch", fetchSpy);
  const { result } = renderUpload();
  act(() => result.current.select([selected]));
  await act(async () => result.current.start());
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  expect(result.current.files[0]?.phase).toBe("queued");

  await act(async () => vi.advanceTimersByTimeAsync(300_000));

  expect(result.current.batchPollingTimedOut).toBe(true);
  expect(result.current.files[0]?.phase).toBe("queued");
  expect(result.current.files[0]?.error).toBeNull();
  expect(requestSignal?.aborted).toBe(false);
  let manualRefresh!: Promise<void>;
  act(() => { manualRefresh = result.current.refreshBatch(); });
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  batchResponse.resolve(Response.json(batchDetail([selected], "processing", ["processing"])));
  await act(async () => manualRefresh);
  expect(result.current.batchPollingTimedOut).toBe(true);
  await vi.waitFor(() => expect(result.current.files[0]?.phase).toBe("processing"));
});

test("a suspended first batch retry preserves queued files when automatic tracking expires", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let monotonicNow = 0;
  vi.spyOn(performance, "now").mockImplementation(() => monotonicNow);
  const selected = file("suspended-first-batch.pdf");
  const fetchSpy = vi.fn(async () => {
    if (fetchSpy.mock.calls.length === 1) {
      return Response.json({
        message: "数据库暂时不可用",
        code: "database_unavailable",
        traceId: "trace-suspended-first-batch",
      }, { status: 503, headers: { "X-Request-ID": "trace-suspended-first-batch" } });
    }
    return Response.json(batchDetail([selected], "processing", ["processing"]));
  });
  vi.stubGlobal("fetch", fetchSpy);
  const { result, client } = renderUpload({ client: createAppQueryClient() });
  act(() => result.current.select([selected]));
  await act(async () => result.current.start());
  await act(async () => vi.advanceTimersByTimeAsync(0));
  expect(result.current.files[0]?.phase).toBe("queued");

  monotonicNow = 300_001;
  await act(async () => vi.advanceTimersByTimeAsync(1_000));

  expect(fetchSpy).toHaveBeenCalledTimes(1);
  expect(result.current.batchPollingTimedOut).toBe(true);
  expect(result.current.files[0]?.phase).toBe("queued");
  expect(result.current.files[0]?.error).toBeNull();
  expect(result.current.batchError).toBeNull();
  expect(client.isFetching()).toBe(0);

  await act(async () => result.current.refreshBatch());
  await vi.waitFor(() => expect(result.current.files[0]?.phase).toBe("processing"));
  expect(fetchSpy).toHaveBeenCalledTimes(2);
  expect(result.current.batchError).toBeNull();
});

test("user cancel aborts an in-flight batch query without cancelling confirmed facts", async () => {
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
  const selected = file("abort-batch-query.pdf");
  const { result, client } = renderUpload();
  act(() => result.current.select([selected]));
  await act(async () => result.current.start());
  await waitFor(() => expect(requestSignal).toBeDefined());

  act(() => result.current.cancel());

  expect(requestSignal?.aborted).toBe(true);
  expect(result.current.batchId).toBe(BATCH_1);
  expect(result.current.files[0]?.phase).toBe("queued");
  await vi.waitFor(() => expect(client.isFetching()).toBe(0));
});

test("a later hashing failure marks its exact row and strips an existing ApiError cause", async () => {
  const files = [file("hashed.pdf"), file("read-fails.pdf"), file("unvisited.pdf")];
  const firstHash = deferred<void>();
  const secondHash = deferred<void>();
  const unsafeCause = { body: "SECRET file reader", signedUrl: instruction(0).url };
  const hashError = new ApiError("network", "无法读取文件，请重新选择", {
    status: 503,
    code: "file_read_failed",
    traceId: "trace-file-read",
    retryAfterSeconds: 4,
    cause: unsafeCause,
  });
  const dependencies = defaultDependencies();
  dependencies.prepareFiles = vi.fn(async (_files, _signal, onHashing) => {
    onHashing(0);
    await firstHash.promise;
    onHashing(1);
    await secondHash.promise;
    throw hashError;
  });
  vi.stubGlobal("fetch", vi.fn());
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select(files));
  let start!: Promise<void>;
  act(() => { start = result.current.start(); });
  await waitFor(() => expect(result.current.files[0]?.phase).toBe("hashing"));
  firstHash.resolve();
  await waitFor(() => expect(result.current.files[1]?.phase).toBe("hashing"));
  secondHash.resolve();
  await act(async () => start);

  expect(result.current.files.map(({ phase }) => phase)).toEqual(["selected", "failed", "selected"]);
  expect(result.current.files[1]?.error).toMatchObject({
    kind: "network",
    message: "无法读取文件，请重新选择",
    status: 503,
    code: "file_read_failed",
    traceId: "trace-file-read",
    retryAfterSeconds: 4,
  });
  expect(result.current.files[1]?.error).not.toBe(hashError);
  expect(result.current.files[1]?.error?.cause).toBeUndefined();
  expect(result.current.error?.cause).toBeUndefined();
  expect(JSON.stringify(result.current)).not.toMatch(/SECRET file reader|session-1\/file-0/);
  expect(dependencies.createBatch).not.toHaveBeenCalled();
});

test.each(["create", "complete"] as const)(
  "%s session-invalid errors expire the existing SessionProvider boundary",
  async (stage) => {
    const selected = file(`${stage}-provider-session.pdf`);
    const sessionError = new ApiError("http", "会话已过期", {
      status: 401,
      code: "session_invalid",
    });
    const dependencies = defaultDependencies();
    if (stage === "create") {
      dependencies.createBatch = vi.fn(async () => { throw sessionError; });
    } else {
      dependencies.complete = vi.fn(async () => { throw sessionError; });
    }
    vi.stubGlobal("fetch", vi.fn());
    const client = queryClient();
    client.setQueryData(["private-session-data"], "private");
    const anonymousSignal = AbortSignal.abort();
    function SessionWrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={["/knowledge"]}>
            <SessionProvider restoredIdentity={IDENTITY} sessionApi={{ restore: async () => IDENTITY, logout: async () => undefined }}>{children}</SessionProvider>
          </MemoryRouter>
        </QueryClientProvider>
      );
    }
    const rendered = renderHook(() => {
      const session = useSession();
      const location = useLocation();
      const upload = useKnowledgeUploadBatch({
        organizationId: ORGANIZATION_ID,
        projectId: PROJECT_ID,
        csrfToken: "csrf",
        sessionSignal: session.session?.signal ?? anonymousSignal,
        onAccessUnavailable: vi.fn(),
        dependencies,
      });
      return { status: session.status, signal: session.session?.signal, path: location.pathname, upload };
    }, { wrapper: SessionWrapper });
    const authenticatedSignal = rendered.result.current.signal;
    act(() => rendered.result.current.upload.select([selected]));
    await act(async () => rendered.result.current.upload.start());

    await waitFor(() => expect(rendered.result.current.status).toBe("anonymous"));
    expect(rendered.result.current.path).toBe("/login");
    expect(authenticatedSignal?.aborted).toBe(true);
    expect(client.getQueryData(["private-session-data"])).toBeUndefined();
    expect(client.getMutationCache().getAll()).toHaveLength(0);
  },
);

test("user cancellation aborts the operation and session cancellation uses the same guard", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(batchDetail([file("cancel.pdf")]))));
  for (const mode of ["user", "session"] as const) {
    let operationSignal: AbortSignal | undefined;
    const dependencies = defaultDependencies();
    dependencies.putObject = vi.fn(async ({ signal }) => {
      operationSignal = signal;
      await new Promise<void>((_resolve, reject) => signal.addEventListener("abort", () => {
        reject(new ApiError("aborted", "请求已被取消"));
      }, { once: true }));
    });
    const rendered = renderUpload({ dependencies });
    act(() => rendered.result.current.select([file("cancel.pdf")]));
    let nextStart!: Promise<void>;
    act(() => { nextStart = rendered.result.current.start(); });
    await waitFor(() => expect(operationSignal).toBeDefined());

    act(() => mode === "user" ? rendered.result.current.cancel() : rendered.session.abort());
    await act(async () => nextStart);

    expect(operationSignal?.aborted).toBe(true);
    await waitFor(() => expect(rendered.result.current.pending).toBe(false));
    expect(rendered.result.current.files[0]?.phase).toBe("cancelled");
    rendered.unmount();
  }
});

test("unmount aborts transport and a signal-ignoring late result has no cache or callback effects", async () => {
  const late = deferred<void>();
  let signal: AbortSignal | undefined;
  const dependencies = defaultDependencies();
  dependencies.putObject = vi.fn(async (args) => {
    signal = args.signal;
    await late.promise;
  });
  const onAccessUnavailable = vi.fn();
  const client = queryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(batchDetail([file("late.pdf")]))));
  const rendered = renderUpload({ dependencies, client, onAccessUnavailable });
  act(() => rendered.result.current.select([file("late.pdf")]));
  act(() => { void rendered.result.current.start(); });
  await waitFor(() => expect(signal).toBeDefined());

  rendered.unmount();
  expect(signal?.aborted).toBe(true);
  late.resolve();
  await act(async () => Promise.resolve());

  expect(dependencies.complete).not.toHaveBeenCalled();
  expect(invalidate).not.toHaveBeenCalled();
  expect(onAccessUnavailable).not.toHaveBeenCalled();
});

test("a newer selection and start cannot be overwritten by an older signal-ignoring generation", async () => {
  const firstPut = deferred<void>();
  const dependencies = defaultDependencies();
  dependencies.createBatch = vi.fn<KnowledgeUploadDependencies["createBatch"]>(async ({ intents }) => uploadBatch(
    intents.map(({ fileName }) => file(fileName)),
    intents[0]?.fileName === "new.pdf" ? 2 : 1,
  ));
  dependencies.putObject = vi.fn<KnowledgeUploadDependencies["putObject"]>(async ({ file: selected }) => {
    if (selected.name === "old.pdf") await firstPut.promise;
  });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL((input as Request).url).pathname;
    return Response.json(batchDetail(
      [file("new.pdf")], "processing", ["queued"], pathname.includes(BATCH_2) ? 2 : 1,
    ));
  }));
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select([file("old.pdf")]));
  act(() => { void result.current.start(); });
  await waitFor(() => expect(dependencies.putObject).toHaveBeenCalledTimes(1));

  act(() => result.current.select([file("new.pdf")]));
  await act(async () => result.current.start());
  expect(result.current.files.map(({ file: selected }) => selected.name)).toEqual(["new.pdf"]);
  expect(result.current.batchId).toBe(BATCH_2);
  firstPut.resolve();
  await act(async () => Promise.resolve());

  expect(result.current.files.map(({ file: selected }) => selected.name)).toEqual(["new.pdf"]);
  expect(result.current.batchId).toBe(BATCH_2);
});

test("retryFailed creates a fresh upload session only for transfer or complete failures", async () => {
  const files = [file("ok.pdf"), file("retry.pdf")];
  const dependencies = defaultDependencies();
  dependencies.createBatch = vi.fn()
    .mockResolvedValueOnce(uploadBatch(files, 1))
    .mockResolvedValueOnce(uploadBatch([files[1]!], 2));
  dependencies.putObject = vi.fn()
    .mockResolvedValueOnce(undefined)
    .mockRejectedValueOnce({ responseBody: "SECRET https://objects.example.test/session-1/file-1" })
    .mockResolvedValueOnce(undefined);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const second = request.url.includes(BATCH_2);
    return Response.json(batchDetail(second ? [files[1]!] : files, "processing", undefined, second ? 2 : 1));
  }));
  const { result, client } = renderUpload({ dependencies });
  act(() => result.current.select(files));
  await act(async () => result.current.start());
  const firstInstruction = instruction(1, 1);
  expect(result.current.files[1]?.error?.message).toBe("文件上传暂时无法完成，请重试");
  expect(JSON.stringify(result.current)).not.toContain(firstInstruction.url);
  expect(JSON.stringify(client.getQueryCache().getAll().map(({ state }) => state.data)))
    .not.toContain(firstInstruction.url);

  await act(async () => result.current.retryFailed());

  expect(dependencies.createBatch).toHaveBeenCalledTimes(2);
  const secondCreateOptions = vi.mocked(dependencies.createBatch).mock.calls[1]?.[0];
  expect(secondCreateOptions?.intents).toHaveLength(1);
  const secondInstruction = vi.mocked(dependencies.putObject).mock.calls[2]?.[0].instruction;
  expect(secondInstruction?.url).not.toBe(firstInstruction.url);
  expect(result.current.files).toHaveLength(1);
  expect(result.current.files[0]?.phase).toBe("queued");
});

test("a complete failure retries from prepare/create with a new instruction", async () => {
  const selected = file("complete-retry.pdf");
  const dependencies = defaultDependencies();
  dependencies.createBatch = vi.fn()
    .mockResolvedValueOnce(uploadBatch([selected], 1))
    .mockResolvedValueOnce(uploadBatch([selected], 2));
  dependencies.complete = vi.fn()
    .mockRejectedValueOnce(new ApiError("network", "确认失败"))
    .mockResolvedValueOnce({
      uploadId: instruction(0, 2).uploadId,
      itemId: instruction(0, 2).itemId,
      batchId: BATCH_2,
      status: "queued",
      resourceId: null,
      resourceVersionId: null,
    });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const second = (input as Request).url.includes(BATCH_2);
    return Response.json(batchDetail([selected], "processing", ["queued"], second ? 2 : 1));
  }));
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select([selected]));
  await act(async () => result.current.start());
  expect(result.current.files[0]?.failureStage).toBe("complete");

  await act(async () => result.current.retryFailed());

  expect(dependencies.prepareFiles).toHaveBeenCalledTimes(2);
  expect(dependencies.createBatch).toHaveBeenCalledTimes(2);
  expect(vi.mocked(dependencies.putObject).mock.calls[1]?.[0].instruction.url)
    .toBe(instruction(0, 2).url);
  expect(result.current.files[0]?.phase).toBe("queued");
});

test.each([409, 410])(
  "complete HTTP %s remains eligible for a fresh upload session",
  async (status) => {
    const selected = file(`complete-${status}.pdf`);
    const dependencies = defaultDependencies();
    dependencies.createBatch = vi.fn()
      .mockResolvedValueOnce(uploadBatch([selected], 1))
      .mockResolvedValueOnce(uploadBatch([selected], 2));
    dependencies.complete = vi.fn()
      .mockRejectedValueOnce(new ApiError("http", "上传确认状态已变化", { status }))
      .mockResolvedValueOnce({
        uploadId: instruction(0, 2).uploadId,
        itemId: instruction(0, 2).itemId,
        batchId: BATCH_2,
        status: "queued",
        resourceId: null,
        resourceVersionId: null,
      });
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(
      batchDetail([selected], "processing", ["queued"], 2),
    )));
    const { result } = renderUpload({ dependencies });
    act(() => result.current.select([selected]));
    await act(async () => result.current.start());

    await act(async () => result.current.retryFailed());

    expect(dependencies.createBatch).toHaveBeenCalledTimes(2);
    expect(result.current.batchId).toBe(BATCH_2);
  },
);

test.each(["create", "complete"] as const)(
  "%s contract failures cannot start a fresh upload through hook actions",
  async (stage) => {
    const selected = file(`${stage}-contract.pdf`);
    const dependencies = defaultDependencies();
    const contractError = new ApiError("contract", "上传响应关联无效");
    if (stage === "create") {
      dependencies.createBatch = vi.fn(async () => { throw contractError; });
    } else {
      dependencies.complete = vi.fn(async () => { throw contractError; });
    }
    vi.stubGlobal("fetch", vi.fn());
    const { result } = renderUpload({ dependencies });
    act(() => result.current.select([selected]));
    await act(async () => result.current.start());
    const createCalls = vi.mocked(dependencies.createBatch).mock.calls.length;
    const putCalls = vi.mocked(dependencies.putObject).mock.calls.length;

    await act(async () => result.current.start());
    await act(async () => result.current.retryFailed());

    expect(dependencies.createBatch).toHaveBeenCalledTimes(createCalls);
    expect(dependencies.putObject).toHaveBeenCalledTimes(putCalls);
    expect(result.current.error ?? result.current.files[0]?.error)
      .toMatchObject({ kind: "contract", retryable: false });
  },
);

test("worker-reported failures are safe, terminal, and excluded from transfer retry", async () => {
  const files = [file("worker.pdf")];
  const dependencies = defaultDependencies();
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(
    batchDetail(files, "completed_with_errors", ["failed"]),
  )));
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select(files));
  await act(async () => result.current.start());
  await waitFor(() => expect(result.current.files[0]?.failureStage).toBe("worker"));

  await act(async () => result.current.retryFailed());

  expect(dependencies.createBatch).toHaveBeenCalledTimes(1);
  expect(result.current.files[0]?.error?.message).toBe("无法解析 <script>alert(1)</script>");
});

test("a later worker failure cannot replace an earlier local transfer failure", async () => {
  const selected = file("local-failure.pdf");
  const completed = file("completed.pdf");
  const files = [selected, completed];
  const batchResponse = deferred<Response>();
  const dependencies = defaultDependencies();
  dependencies.putObject = vi.fn(async ({ file: current }) => {
    if (current === selected) throw new ApiError("network", "文件直传失败，请重试");
  });
  vi.stubGlobal("fetch", vi.fn(async () => batchResponse.promise));
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select(files));
  await act(async () => result.current.start());
  expect(result.current.files[0]?.failureStage).toBe("transfer");

  batchResponse.resolve(Response.json(batchDetail(
    files, "completed_with_errors", ["failed", "ready"],
  )));
  await waitFor(() => expect(result.current.batch?.status).toBe("completed_with_errors"));

  expect(result.current.files[0]?.failureStage).toBe("transfer");
  expect(result.current.files[0]?.error?.message).toBe("文件直传失败，请重试");
});

test("complete success invalidates resources and stale searches, and terminal batch refreshes resources once", async () => {
  const files = [file("cache.pdf")];
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(batchDetail(files, "completed", ["ready"]))));
  const client = queryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderUpload({ client });
  act(() => result.current.select(files));
  await act(async () => result.current.start());
  await waitFor(() => expect(result.current.batch?.status).toBe("completed"));

  const resourceKey = knowledgeKeys.resources(ORGANIZATION_ID, PROJECT_ID);
  const searchPrefix = knowledgeKeys.searches(ORGANIZATION_ID, PROJECT_ID);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: resourceKey, exact: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: searchPrefix, refetchType: "none" });
  expect(invalidate.mock.calls.filter(([options]) =>
    JSON.stringify(options?.queryKey) === JSON.stringify(resourceKey)
  )).toHaveLength(2);
});

test("create 404 conceals immediately, while complete 404 first rechecks the active resource boundary", async () => {
  for (const resourceStatus of [200, 404]) {
    const selected = file(`complete-${resourceStatus}.pdf`);
    const session = new AbortController();
    const onAccessUnavailable = vi.fn();
    const dependencies = defaultDependencies();
    dependencies.complete = vi.fn(async () => {
      throw new ApiError("http", "不可见上传", { status: 404, traceId: "trace-complete" });
    });
    let resourceFetches = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL((input as Request).url).pathname;
      if (path.endsWith("/knowledge/resources")) {
        resourceFetches += 1;
        return resourceStatus === 200
          ? Response.json({ capabilities: { canWrite: true }, items: [], nextCursor: null })
          : Response.json({ code: "not_found", message: "不可见项目", traceId: "trace-resource" }, {
            status: 404,
          });
      }
      return Response.json(batchDetail([selected]));
    }));
    const rendered = renderUpload({
      dependencies, session, onAccessUnavailable, withResources: true,
    });
    await waitFor(() => expect(resourceFetches).toBe(1));
    act(() => rendered.result.current.select([selected]));
    await act(async () => rendered.result.current.start());
    await waitFor(() => expect(resourceFetches).toBe(2));

    expect(onAccessUnavailable).toHaveBeenCalledTimes(resourceStatus === 404 ? 1 : 0);
    rendered.unmount();
  }

  const create404 = new ApiError("http", "不可见项目", { status: 404, traceId: "trace-create" });
  const dependencies = defaultDependencies();
  dependencies.createBatch = vi.fn(async () => { throw create404; });
  const onAccessUnavailable = vi.fn();
  const rendered = renderUpload({ dependencies, onAccessUnavailable });
  act(() => rendered.result.current.select([file("create.pdf")]));
  await act(async () => rendered.result.current.start());
  expect(onAccessUnavailable).toHaveBeenCalledWith(create404);
});

test("a complete-404 resource recheck cannot conceal after a newer selection wins", async () => {
  const oldFile = file("old-404.pdf");
  const resourceRecheck = deferred<Response>();
  const dependencies = defaultDependencies();
  dependencies.complete = vi.fn(async () => {
    throw new ApiError("http", "不可见上传", { status: 404 });
  });
  const onAccessUnavailable = vi.fn();
  let resourceFetches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL((input as Request).url).pathname;
    if (path.endsWith("/knowledge/resources")) {
      resourceFetches += 1;
      if (resourceFetches === 1) {
        return Response.json({ capabilities: { canWrite: true }, items: [], nextCursor: null });
      }
      return resourceRecheck.promise;
    }
    return Response.json(batchDetail([oldFile]));
  }));
  const rendered = renderUpload({ dependencies, onAccessUnavailable, withResources: true });
  await waitFor(() => expect(resourceFetches).toBe(1));
  act(() => rendered.result.current.select([oldFile]));
  let start!: Promise<void>;
  act(() => { start = rendered.result.current.start(); });
  await waitFor(() => expect(resourceFetches).toBe(2));

  act(() => rendered.result.current.select([file("new.pdf")]));
  resourceRecheck.resolve(Response.json({
    code: "not_found", message: "不可见项目", traceId: "trace-resource",
  }, { status: 404 }));
  await act(async () => start);

  expect(onAccessUnavailable).not.toHaveBeenCalled();
  expect(rendered.result.current.files[0]?.file.name).toBe("new.pdf");
});

test("concurrent complete 404s share one resource recheck and conceal only once", async () => {
  const files = [file("first-404.pdf"), file("second-404.pdf")];
  const resourceRecheck = deferred<boolean>();
  const dependencies = defaultDependencies();
  dependencies.complete = vi.fn(async () => {
    throw new ApiError("http", "不可见上传", { status: 404, traceId: "trace-complete" });
  });
  const onAccessUnavailable = vi.fn();
  let resourceFetches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL((input as Request).url).pathname;
    if (path.endsWith("/knowledge/resources")) {
      resourceFetches += 1;
      if (resourceFetches === 1) {
        return Response.json({ capabilities: { canWrite: true }, items: [], nextCursor: null });
      }
      await resourceRecheck.promise;
      return Response.json({
        code: "not_found", message: "不可见项目", traceId: "trace-resource",
      }, { status: 404 });
    }
    return Response.json(batchDetail(files));
  }));
  const rendered = renderUpload({ dependencies, onAccessUnavailable, withResources: true });
  await waitFor(() => expect(resourceFetches).toBe(1));
  act(() => rendered.result.current.select(files));
  let start!: Promise<void>;
  act(() => { start = rendered.result.current.start(); });
  await waitFor(() => expect(dependencies.complete).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(resourceFetches).toBeGreaterThan(1));

  resourceRecheck.resolve(true);
  await act(async () => start);

  expect(resourceFetches).toBe(2);
  expect(onAccessUnavailable).toHaveBeenCalledTimes(1);
});

test("batch 404 follows the same resource-boundary concealment rule and refreshBatch refetches", async () => {
  const selected = file("batch.pdf");
  const session = new AbortController();
  const onAccessUnavailable = vi.fn();
  let batchFetches = 0;
  let resourceFetches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL((input as Request).url).pathname;
    if (path.endsWith("/knowledge/resources")) {
      resourceFetches += 1;
      return Response.json({ code: "not_found", message: "不可见项目", traceId: "trace-resource" }, {
        status: 404,
      });
    }
    batchFetches += 1;
    return Response.json({ code: "not_found", message: "不可见批次", traceId: "trace-batch" }, {
      status: 404,
    });
  }));
  const rendered = renderUpload({ session, onAccessUnavailable, withResources: true });
  await waitFor(() => expect(resourceFetches).toBe(1));
  act(() => rendered.result.current.select([selected]));
  await act(async () => rendered.result.current.start());
  await waitFor(() => expect(onAccessUnavailable).toHaveBeenCalledTimes(1));
  // Initial resource load, complete-success refresh, then the batch-404 authorization recheck.
  expect(resourceFetches).toBe(3);
  expect(rendered.result.current.batchError?.status).toBe(404);

  await act(async () => rendered.result.current.refreshBatch());
  expect(batchFetches).toBeGreaterThanOrEqual(2);
});

test("batch 404 remains local when the resource boundary still succeeds", async () => {
  const selected = file("local-batch-404.pdf");
  const onAccessUnavailable = vi.fn();
  let resourceFetches = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL((input as Request).url).pathname;
    if (path.endsWith("/knowledge/resources")) {
      resourceFetches += 1;
      return Response.json({ capabilities: { canWrite: true }, items: [], nextCursor: null });
    }
    return Response.json({ code: "not_found", message: "不可见批次", traceId: "trace-batch" }, {
      status: 404,
    });
  }));
  const rendered = renderUpload({ onAccessUnavailable, withResources: true });
  await waitFor(() => expect(resourceFetches).toBe(1));
  act(() => rendered.result.current.select([selected]));
  await act(async () => rendered.result.current.start());
  await waitFor(() => expect(rendered.result.current.batchError?.status).toBe(404));

  expect(resourceFetches).toBeGreaterThanOrEqual(2);
  expect(onAccessUnavailable).not.toHaveBeenCalled();
});

test("unexpected thrown values are converted to fixed safe state messages", async () => {
  const dependencies = defaultDependencies();
  dependencies.prepareFiles = vi.fn(async () => {
    throw { message: "SECRET https://objects.example.test/signed", responseBody: "private XML" };
  });
  vi.stubGlobal("fetch", vi.fn());
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select([file("unsafe.pdf")]));
  await act(async () => result.current.start());

  expect(result.current.error?.message).toBe("无法准备文件，请重新选择");
  expect(result.current.error?.cause).toBeUndefined();
  expect(JSON.stringify(result.current)).not.toMatch(/SECRET|objects\.example|private XML/);
});

test("clear cancels active work and releases selected files and batch state", async () => {
  const pending = deferred<void>();
  let signal: AbortSignal | undefined;
  const dependencies = defaultDependencies();
  dependencies.putObject = vi.fn(async (args) => {
    signal = args.signal;
    await pending.promise;
  });
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(batchDetail([file("clear.pdf")]))));
  const { result } = renderUpload({ dependencies });
  act(() => result.current.select([file("clear.pdf")]));
  act(() => { void result.current.start(); });
  await waitFor(() => expect(signal).toBeDefined());

  act(() => result.current.clear());

  expect(signal?.aborted).toBe(true);
  expect(result.current.files).toEqual([]);
  expect(result.current.batchId).toBeNull();
  expect(result.current.batch).toBeNull();
  expect(result.current.error).toBeNull();
});

test.each([
  ["completed", ["ready"], 1, 0],
  ["completed_with_errors", ["failed"], 0, 1],
] as const)(
  "retains a safe %s summary through clear and selection until the next valid upload starts",
  async (status, itemStatuses, readyCount, failedCount) => {
    const selected = file(`${status}.pdf`);
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(
      batchDetail([selected], status, [...itemStatuses]),
    )));
    const dependencies = defaultDependencies();
    const rendered = renderUpload({ dependencies });
    act(() => rendered.result.current.select([selected]));
    await act(async () => rendered.result.current.start());
    await waitFor(() => expect(rendered.result.current.batch?.status).toBe(status));
    expect(rendered.result.current.lastFinalSummary).toEqual({
      status,
      itemCount: 1,
      readyCount,
      failedCount,
    });

    act(() => rendered.result.current.clear());
    expect(rendered.result.current.files).toEqual([]);
    expect(rendered.result.current.batchId).toBeNull();
    expect(rendered.result.current.lastFinalSummary?.status).toBe(status);

    const next = file(`next-${status}.pdf`);
    act(() => rendered.result.current.select([next]));
    expect(rendered.result.current.lastFinalSummary?.status).toBe(status);
    const prepareGate = deferred<void>();
    dependencies.prepareFiles = vi.fn(async (files) => {
      await prepareGate.promise;
      return prepared(files);
    });
    let nextStart!: Promise<void>;
    act(() => { nextStart = rendered.result.current.start(); });
    await waitFor(() => expect(rendered.result.current.pending).toBe(true));
    expect(rendered.result.current.lastFinalSummary).toBeNull();
    act(() => rendered.result.current.cancel());
    prepareGate.resolve();
    await act(async () => nextStart);
  },
);

test("project and session identity changes clear the retained final summary", async () => {
  const selected = file("identity-summary.pdf");
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(
    batchDetail([selected], "completed", ["ready"]),
  )));
  const dependencies = defaultDependencies();
  const client = queryClient();
  const sessionA = new AbortController();
  const rendered = renderHook(
    ({ organizationId, projectId, sessionSignal }) => useKnowledgeUploadBatch({
      organizationId,
      projectId,
      csrfToken: "csrf",
      sessionSignal,
      onAccessUnavailable: vi.fn(),
      dependencies,
    }),
    {
      initialProps: {
        organizationId: ORGANIZATION_ID,
        projectId: PROJECT_ID,
        sessionSignal: sessionA.signal,
      },
      wrapper: wrapper(client),
    },
  );
  act(() => rendered.result.current.select([selected]));
  await act(async () => rendered.result.current.start());
  await waitFor(() => expect(rendered.result.current.lastFinalSummary).not.toBeNull());

  rendered.rerender({
    organizationId: ORGANIZATION_ID,
    projectId: PROJECT_ID,
    sessionSignal: new AbortController().signal,
  });
  await waitFor(() => expect(rendered.result.current.lastFinalSummary).toBeNull());

  act(() => rendered.result.current.select([selected]));
  await act(async () => rendered.result.current.start());
  await waitFor(() => expect(rendered.result.current.lastFinalSummary).not.toBeNull());
  rendered.rerender({
    organizationId: "00000000-0000-4000-8000-000000002002",
    projectId: "00000000-0000-4000-8000-000000004002",
    sessionSignal: new AbortController().signal,
  });
  await waitFor(() => expect(rendered.result.current.lastFinalSummary).toBeNull());
});
