import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef } from "react";

import { ApiError } from "../api/errors.ts";
import {
  completeKnowledgeUpload,
  createKnowledgeUploadBatch,
  putKnowledgeObject,
  type KnowledgeBatchDetail,
  type KnowledgeUploadProgress,
} from "../api/knowledgeUploads.ts";
import {
  prepareKnowledgeFiles,
  validateKnowledgeFiles,
  type KnowledgeFileIssue,
  type PreparedKnowledgeFile,
} from "../lib/knowledgeUpload.ts";
import {
  isKnowledgeBatchTerminal,
  knowledgeKeys,
  useKnowledgeBatchQuery,
} from "../queries/knowledge.ts";

export type KnowledgeUploadFilePhase =
  | "selected"
  | "hashing"
  | "creating"
  | "uploading"
  | "completing"
  | "awaiting_upload"
  | "queued"
  | "processing"
  | "ready"
  | "failed"
  | "cancelled";

export type KnowledgeUploadFailureStage = "hash" | "transfer" | "complete" | "worker";

export interface KnowledgeUploadFileState {
  file: File;
  phase: KnowledgeUploadFilePhase;
  progress: KnowledgeUploadProgress | null;
  error: ApiError | null;
  failureStage: KnowledgeUploadFailureStage | null;
  itemId: string | null;
}

interface KnowledgeUploadLocalState {
  files: KnowledgeUploadFileState[];
  issues: KnowledgeFileIssue[];
  batchId: string | null;
  startedAt: number | null;
  pending: boolean;
  error: ApiError | null;
  batchError: ApiError | null;
  batchTrackingStopped: boolean;
  lastFinalSummary: KnowledgeUploadFinalSummary | null;
}

export interface KnowledgeUploadFinalSummary {
  status: "completed" | "completed_with_errors" | "failed";
  itemCount: number;
  readyCount: number;
  failedCount: number;
}

export interface KnowledgeUploadBatchState extends KnowledgeUploadLocalState {
  batch: KnowledgeBatchDetail | null;
  batchPollingTimedOut: boolean;
}

export interface KnowledgeUploadBatchActions {
  select(files: readonly File[]): void;
  start(): Promise<void>;
  cancel(): void;
  retryFailed(): Promise<void>;
  clear(): void;
  refreshBatch(): Promise<void>;
}

export type KnowledgeUploadBatchController = KnowledgeUploadBatchState &
  KnowledgeUploadBatchActions;

export interface KnowledgeUploadDependencies {
  prepareFiles: typeof prepareKnowledgeFiles;
  createBatch: typeof createKnowledgeUploadBatch;
  putObject: typeof putKnowledgeObject;
  complete: typeof completeKnowledgeUpload;
  now(): number;
}

const productionDependencies: KnowledgeUploadDependencies = {
  prepareFiles: prepareKnowledgeFiles,
  createBatch: createKnowledgeUploadBatch,
  putObject: putKnowledgeObject,
  complete: completeKnowledgeUpload,
  now: () => performance.now(),
};

type KnowledgeUploadAction =
  | { type: "select"; files: readonly File[]; issues: KnowledgeFileIssue[] }
  | { type: "start"; files: readonly File[] }
  | { type: "phase"; index: number; phase: KnowledgeUploadFilePhase }
  | { type: "progress"; index: number; progress: KnowledgeUploadProgress }
  | { type: "failed"; index: number; error: ApiError; stage: KnowledgeUploadFailureStage }
  | { type: "batch"; batchId: string; startedAt: number; itemIds: readonly string[] }
  | { type: "batch-data"; batch: KnowledgeBatchDetail }
  | { type: "operation-error"; error: ApiError }
  | { type: "batch-error"; error: ApiError }
  | { type: "settled" }
  | { type: "cancelled" }
  | { type: "clear" }
  | { type: "identity-clear" };

const initialState: KnowledgeUploadLocalState = {
  files: [],
  issues: [],
  batchId: null,
  startedAt: null,
  pending: false,
  error: null,
  batchError: null,
  batchTrackingStopped: false,
  lastFinalSummary: null,
};

function selectedFile(file: File): KnowledgeUploadFileState {
  return {
    file,
    phase: "selected",
    progress: null,
    error: null,
    failureStage: null,
    itemId: null,
  };
}

function updateFile(
  state: KnowledgeUploadLocalState,
  index: number,
  update: (fileState: KnowledgeUploadFileState) => KnowledgeUploadFileState,
): KnowledgeUploadLocalState {
  if (state.files[index] === undefined) return state;
  const files = [...state.files];
  files[index] = update(files[index]!);
  return { ...state, files };
}

function workerError(item: KnowledgeBatchDetail["items"][number]): ApiError {
  return new ApiError(
    "http",
    item.errorDetail ?? "文件处理失败",
    { code: item.errorCode },
  );
}

function finalSummary(batch: KnowledgeBatchDetail): KnowledgeUploadFinalSummary | null {
  if (
    batch.status !== "completed" &&
    batch.status !== "completed_with_errors" &&
    batch.status !== "failed"
  ) return null;
  return {
    status: batch.status,
    itemCount: batch.itemCount,
    readyCount: batch.readyCount,
    failedCount: batch.failedCount,
  };
}

function reducer(
  state: KnowledgeUploadLocalState,
  action: KnowledgeUploadAction,
): KnowledgeUploadLocalState {
  switch (action.type) {
    case "select":
      return {
        ...initialState,
        files: action.files.map(selectedFile),
        issues: action.issues,
        lastFinalSummary: state.lastFinalSummary,
      };
    case "start":
      return {
        ...initialState,
        files: action.files.map(selectedFile),
        pending: true,
      };
    case "phase":
      return updateFile(state, action.index, (fileState) => ({
        ...fileState,
        phase: action.phase,
      }));
    case "progress":
      return updateFile(state, action.index, (fileState) => ({
        ...fileState,
        progress: action.progress,
      }));
    case "failed":
      return updateFile(state, action.index, (fileState) => ({
        ...fileState,
        phase: "failed",
        error: action.error,
        failureStage: action.stage,
      }));
    case "batch":
      return {
        ...state,
        batchId: action.batchId,
        startedAt: action.startedAt,
        batchError: null,
        files: state.files.map((fileState, index) => ({
          ...fileState,
          itemId: action.itemIds[index] ?? null,
        })),
      };
    case "batch-data": {
      const items = new Map(action.batch.items.map((item) => [item.id, item]));
      const completedSummary = finalSummary(action.batch);
      return {
        ...state,
        batchError: null,
        lastFinalSummary: completedSummary ?? state.lastFinalSummary,
        files: state.files.map((fileState) => {
          if (fileState.itemId === null) return fileState;
          const item = items.get(fileState.itemId);
          if (item === undefined) return fileState;
          if (
            fileState.phase !== "queued" &&
            fileState.phase !== "awaiting_upload" &&
            fileState.phase !== "processing" &&
            fileState.phase !== "ready"
          ) return fileState;
          if (item.status === "failed") {
            return {
              ...fileState,
              phase: "failed",
              error: workerError(item),
              failureStage: "worker",
            };
          }
          return {
            ...fileState,
            phase: item.status,
            error: null,
            failureStage: null,
          };
        }),
      };
    }
    case "operation-error":
      return { ...state, pending: false, error: action.error };
    case "batch-error":
      return { ...state, batchError: action.error };
    case "settled":
      return { ...state, pending: false };
    case "cancelled":
      return {
        ...state,
        pending: false,
        batchTrackingStopped: true,
        files: state.files.map((fileState) =>
          fileState.phase === "ready" ||
            fileState.phase === "failed" ||
            fileState.phase === "queued" ||
            fileState.phase === "processing"
            ? fileState
            : { ...fileState, phase: "cancelled" as const }),
      };
    case "clear":
      return { ...initialState, lastFinalSummary: state.lastFinalSummary };
    case "identity-clear":
      return initialState;
  }
}

interface ActiveOperation {
  controller: AbortController;
  generation: number;
  onAccessUnavailable(error: ApiError): void;
  resourceAccessRecheck: Promise<boolean> | null;
  accessUnavailableDelivered: boolean;
}

function safeError(error: unknown, fallbackMessage: string): ApiError {
  if (error instanceof ApiError) {
    return new ApiError(error.kind, error.message, {
      status: error.status,
      code: error.code,
      traceId: error.traceId,
      retryAfterSeconds: error.retryAfterSeconds,
      context: error.context,
    });
  }
  return new ApiError("network", fallbackMessage);
}

function isNotFound(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 404;
}

export function canRetryKnowledgeUploadFile(fileState: KnowledgeUploadFileState): boolean {
  return fileState.phase === "failed" &&
    (fileState.failureStage === "transfer" || fileState.failureStage === "complete") &&
    fileState.error !== null &&
    fileState.error.kind !== "contract";
}

export function canRetryKnowledgeUploadCreate(
  upload: Pick<
    KnowledgeUploadLocalState,
    "error" | "batchId" | "startedAt" | "files" | "pending" | "issues" | "batchError"
  >,
): boolean {
  return !upload.pending &&
    upload.issues.length === 0 &&
    upload.batchError === null &&
    upload.error !== null &&
    upload.error.kind !== "contract" &&
    upload.batchId === null &&
    upload.startedAt === null &&
    upload.files.length > 0 &&
    upload.files.every((file) =>
      file.phase === "creating" &&
      file.itemId === null &&
      file.error === null &&
      file.failureStage === null
    );
}

function canStartKnowledgeUpload(upload: KnowledgeUploadLocalState): boolean {
  if (canRetryKnowledgeUploadCreate(upload)) return true;
  return !upload.pending &&
    upload.files.length > 0 &&
    upload.issues.length === 0 &&
    upload.error === null &&
    upload.batchError === null &&
    upload.batchId === null &&
    upload.startedAt === null &&
    upload.files.every((file) =>
      file.phase === "selected" &&
      file.itemId === null &&
      file.error === null &&
      file.failureStage === null
    );
}

async function publishMutationError(
  queryClient: QueryClient,
  mutationKey: readonly unknown[],
  error: ApiError,
): Promise<void> {
  const mutationCache = queryClient.getMutationCache();
  const mutation = mutationCache.build<void, ApiError, void, unknown>(queryClient, {
    mutationKey,
    mutationFn: async () => { throw error; },
    retry: false,
  });
  try {
    await mutation.execute(undefined);
  } catch {
    // The caller already owns the safe local error; this execution notifies cache observers.
  } finally {
    mutationCache.remove(mutation);
  }
}

export function useKnowledgeUploadBatch({
  organizationId,
  projectId,
  csrfToken,
  sessionSignal,
  onAccessUnavailable,
  dependencies = productionDependencies,
}: {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  sessionSignal: AbortSignal;
  onAccessUnavailable(error: ApiError): void;
  dependencies?: KnowledgeUploadDependencies;
}): KnowledgeUploadBatchController {
  const queryClient = useQueryClient();
  const [state, baseDispatch] = useReducer(reducer, initialState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const identityRef = useRef({ organizationId, projectId });
  const sessionSignalRef = useRef(sessionSignal);
  const identityChanged =
    identityRef.current.organizationId !== organizationId ||
    identityRef.current.projectId !== projectId ||
    sessionSignalRef.current !== sessionSignal;
  const visibleState = identityChanged ? initialState : state;
  const mounted = useRef(true);
  const generation = useRef(0);
  const active = useRef<ActiveOperation | null>(null);
  const onAccessUnavailableRef = useRef(onAccessUnavailable);
  const terminalRefresh = useRef<string | null>(null);
  const deliveredBatchErrors = useRef(new WeakSet<ApiError>());
  const resourceKey = useMemo(
    () => knowledgeKeys.resources(organizationId, projectId),
    [organizationId, projectId],
  );
  const searchKey = useMemo(
    () => knowledgeKeys.searches(organizationId, projectId),
    [organizationId, projectId],
  );
  const batchQuery = useKnowledgeBatchQuery({
    organizationId,
    projectId,
    batchId: visibleState.batchId ?? "",
    enabled: visibleState.batchId !== null && !visibleState.batchTrackingStopped,
    sessionSignal,
  });

  const isCurrent = useCallback((operation: ActiveOperation) => (
    mounted.current &&
    active.current === operation &&
    generation.current === operation.generation
  ), []);

  const dispatch = useCallback((operation: ActiveOperation, action: KnowledgeUploadAction) => {
    if (isCurrent(operation)) baseDispatch(action);
  }, [isCurrent]);

  const cancel = useCallback(() => {
    generation.current += 1;
    const operation = active.current;
    active.current = null;
    operation?.controller.abort();
    const batchId = stateRef.current.batchId;
    if (batchId !== null) {
      void queryClient.cancelQueries({
        queryKey: knowledgeKeys.batch(organizationId, projectId, batchId),
        exact: true,
      });
    }
    if (mounted.current) baseDispatch({ type: "cancelled" });
  }, [organizationId, projectId, queryClient]);

  const recheckResourceAccess = useCallback(async (): Promise<boolean> => {
    const resourceQuery = queryClient.getQueryCache().find({
      queryKey: resourceKey,
      exact: true,
    });
    if (resourceQuery === undefined || resourceQuery.getObserversCount() === 0) return false;
    await queryClient.invalidateQueries({ queryKey: resourceKey, exact: true });
    if (!mounted.current) return false;
    const resourceError = queryClient.getQueryState(resourceKey)?.error;
    return isNotFound(resourceError);
  }, [queryClient, resourceKey]);

  const recheckOperationResourceAccess = useCallback((operation: ActiveOperation) => {
    if (operation.resourceAccessRecheck === null) {
      const sharedRecheck = recheckResourceAccess().finally(() => {
        if (operation.resourceAccessRecheck === sharedRecheck) {
          operation.resourceAccessRecheck = null;
        }
      });
      operation.resourceAccessRecheck = sharedRecheck;
    }
    return operation.resourceAccessRecheck;
  }, [recheckResourceAccess]);

  const run = useCallback(async (files: readonly File[]): Promise<void> => {
    if (sessionSignal.aborted) return;
    const issues = validateKnowledgeFiles(files);
    if (issues.length > 0) {
      if (mounted.current) baseDispatch({ type: "select", files, issues });
      return;
    }

    const previous = active.current;
    previous?.controller.abort();
    const operation: ActiveOperation = {
      controller: new AbortController(),
      generation: generation.current + 1,
      onAccessUnavailable: onAccessUnavailableRef.current,
      resourceAccessRecheck: null,
      accessUnavailableDelivered: false,
    };
    generation.current = operation.generation;
    active.current = operation;
    baseDispatch({ type: "start", files });
    const signal = AbortSignal.any([operation.controller.signal, sessionSignal]);

    let prepared: PreparedKnowledgeFile[];
    let hashingIndex: number | null = null;
    try {
      prepared = await dependencies.prepareFiles(files, signal, (index) => {
        if (hashingIndex !== null && hashingIndex !== index) {
          dispatch(operation, { type: "phase", index: hashingIndex, phase: "selected" });
        }
        hashingIndex = index;
        dispatch(operation, { type: "phase", index, phase: "hashing" });
      });
    } catch (error) {
      if (signal.aborted || !isCurrent(operation)) return;
      if (hashingIndex !== null) {
        dispatch(operation, {
          type: "failed",
          index: hashingIndex,
          error: safeError(error, "无法准备文件，请重新选择"),
          stage: "hash",
        });
      }
      dispatch(operation, {
        type: "operation-error",
        error: safeError(error, "无法准备文件，请重新选择"),
      });
      active.current = null;
      return;
    }

    if (!isCurrent(operation) || signal.aborted) return;
    for (const index of prepared.keys()) {
      dispatch(operation, { type: "phase", index, phase: "creating" });
    }

    let created: Awaited<ReturnType<KnowledgeUploadDependencies["createBatch"]>>;
    try {
      created = await dependencies.createBatch({
        projectId,
        csrfToken,
        intents: prepared.map(({ intent }) => intent),
        signal,
      });
    } catch (error) {
      if (signal.aborted || !isCurrent(operation)) return;
      const presented = safeError(error, "无法创建上传批次，请重试");
      dispatch(operation, { type: "operation-error", error: presented });
      if (isNotFound(presented)) operation.onAccessUnavailable(presented);
      await publishMutationError(
        queryClient,
        [...knowledgeKeys.project(organizationId, projectId), "upload-create"],
        presented,
      );
      active.current = null;
      return;
    }

    if (!isCurrent(operation) || signal.aborted) return;
    const batchStartedAt = dependencies.now();
    let batchPublished = false;
    let nextIndex = 0;
    const worker = async () => {
      while (true) {
        if (!isCurrent(operation) || signal.aborted) return;
        const index = nextIndex;
        nextIndex += 1;
        if (index >= prepared.length) return;
        const preparedFile = prepared[index]!;
        const upload = created.uploads[index]!;
        let stage: "transfer" | "complete" = "transfer";
        try {
          dispatch(operation, { type: "phase", index, phase: "uploading" });
          await dependencies.putObject({
            instruction: upload,
            file: preparedFile.file,
            signal,
            onProgress: (progress) => dispatch(operation, { type: "progress", index, progress }),
          });
          if (!isCurrent(operation) || signal.aborted) return;
          stage = "complete";
          dispatch(operation, { type: "phase", index, phase: "completing" });
          await dependencies.complete({
            projectId,
            uploadId: upload.uploadId,
            batchId: created.batchId,
            itemId: upload.itemId,
            csrfToken,
            signal,
          });
          if (!isCurrent(operation) || signal.aborted) return;
          if (!batchPublished) {
            batchPublished = true;
            dispatch(operation, {
              type: "batch",
              batchId: created.batchId,
              startedAt: batchStartedAt,
              itemIds: created.uploads.map(({ itemId }) => itemId),
            });
          }
          dispatch(operation, { type: "phase", index, phase: "queued" });
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: resourceKey, exact: true }),
            queryClient.invalidateQueries({ queryKey: searchKey, refetchType: "none" }),
          ]);
        } catch (error) {
          if (signal.aborted || !isCurrent(operation)) return;
          const fallback = stage === "transfer"
            ? "文件上传暂时无法完成，请重试"
            : "无法确认文件上传，请重试";
          const presented = safeError(error, fallback);
          dispatch(operation, { type: "failed", index, error: presented, stage });
          if (stage === "complete") {
            await publishMutationError(
              queryClient,
              [...knowledgeKeys.project(organizationId, projectId), "upload-complete"],
              presented,
            );
          }
          if (stage === "complete" && isNotFound(presented)) {
            const inaccessible = await recheckOperationResourceAccess(operation);
            if (
              inaccessible &&
              isCurrent(operation) &&
              !operation.accessUnavailableDelivered
            ) {
              operation.accessUnavailableDelivered = true;
              operation.onAccessUnavailable(presented);
            }
          }
        }
      }
    };

    await Promise.all([worker(), worker()]);
    if (!isCurrent(operation)) return;
    dispatch(operation, { type: "settled" });
    active.current = null;
  }, [
    csrfToken,
    dependencies,
    dispatch,
    isCurrent,
    organizationId,
    projectId,
    queryClient,
    recheckOperationResourceAccess,
    resourceKey,
    searchKey,
    sessionSignal,
  ]);

  const select = useCallback((files: readonly File[]) => {
    cancel();
    if (mounted.current) {
      baseDispatch({ type: "select", files, issues: validateKnowledgeFiles(files) });
    }
  }, [cancel]);

  const start = useCallback(async () => {
    const current = stateRef.current;
    if (!canStartKnowledgeUpload(current)) return;
    await run(current.files.map(({ file }) => file));
  }, [run]);

  const retryFailed = useCallback(async () => {
    const files = stateRef.current.files
      .filter(canRetryKnowledgeUploadFile)
      .map(({ file }) => file);
    if (files.length > 0) await run(files);
  }, [run]);

  const clear = useCallback(() => {
    cancel();
    if (mounted.current) baseDispatch({ type: "clear" });
  }, [cancel]);

  const refreshBatch = useCallback(async () => {
    if (stateRef.current.batchId === null || sessionSignal.aborted) return;
    await batchQuery.refetch({ cancelRefetch: false });
  }, [batchQuery.refetch, sessionSignal]);

  useLayoutEffect(() => {
    onAccessUnavailableRef.current = onAccessUnavailable;
  }, [onAccessUnavailable]);

  useLayoutEffect(() => {
    const previous = identityRef.current;
    const previousSessionSignal = sessionSignalRef.current;
    if (
      previous.organizationId === organizationId &&
      previous.projectId === projectId &&
      previousSessionSignal === sessionSignal
    ) return;
    identityRef.current = { organizationId, projectId };
    sessionSignalRef.current = sessionSignal;
    generation.current += 1;
    const operation = active.current;
    active.current = null;
    operation?.controller.abort();
    const oldBatchId = stateRef.current.batchId;
    if (oldBatchId !== null) {
      void queryClient.cancelQueries({
        queryKey: knowledgeKeys.batch(
          previous.organizationId,
          previous.projectId,
          oldBatchId,
        ),
        exact: true,
      });
    }
    terminalRefresh.current = null;
    deliveredBatchErrors.current = new WeakSet<ApiError>();
    baseDispatch({ type: "identity-clear" });
  }, [organizationId, projectId, queryClient, sessionSignal]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      const operation = active.current;
      active.current = null;
      operation?.controller.abort();
    };
  }, []);

  useEffect(() => {
    if (sessionSignal.aborted) {
      cancel();
      if (mounted.current) baseDispatch({ type: "identity-clear" });
      return;
    }
    sessionSignal.addEventListener("abort", cancel, { once: true });
    return () => sessionSignal.removeEventListener("abort", cancel);
  }, [cancel, sessionSignal]);

  useEffect(() => {
    // Structural sharing may keep identical data; the success transition still
    // clears a previous refresh error, while an unresolved retry retains it.
    if (!batchQuery.isSuccess || batchQuery.data === undefined || state.batchId !== batchQuery.data.id) return;
    baseDispatch({ type: "batch-data", batch: batchQuery.data });
    if (
      isKnowledgeBatchTerminal(batchQuery.data.status) &&
      terminalRefresh.current !== batchQuery.data.id
    ) {
      terminalRefresh.current = batchQuery.data.id;
      void queryClient.invalidateQueries({ queryKey: resourceKey, exact: true });
    }
  }, [batchQuery.data, batchQuery.isSuccess, queryClient, resourceKey, state.batchId]);

  useEffect(() => {
    const rawError = batchQuery.error;
    if (rawError === null) return;
    const error = safeError(rawError, "无法刷新上传状态，请重试");
    if (error instanceof ApiError && deliveredBatchErrors.current.has(error)) return;
    deliveredBatchErrors.current.add(error);
    baseDispatch({ type: "batch-error", error });
    if (isNotFound(error)) {
      const batchId = stateRef.current.batchId;
      if (batchId !== null) {
        void (async () => {
          const inaccessible = await recheckResourceAccess();
          const currentError = queryClient.getQueryState(
            knowledgeKeys.batch(organizationId, projectId, batchId),
          )?.error;
          if (
            inaccessible &&
            mounted.current &&
            stateRef.current.batchId === batchId &&
            currentError === rawError
          ) {
            onAccessUnavailableRef.current(error);
          }
        })();
      }
    }
  }, [batchQuery.error, organizationId, projectId, queryClient, recheckResourceAccess]);

  return {
    ...visibleState,
    batch: visibleState.batchId !== null && batchQuery.data?.id === visibleState.batchId
      ? batchQuery.data
      : null,
    batchPollingTimedOut: visibleState.batchId !== null && batchQuery.automaticPollingStopped,
    select,
    start,
    cancel,
    retryFailed,
    clear,
    refreshBatch,
  };
}
