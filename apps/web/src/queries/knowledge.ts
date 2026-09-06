import {
  CancelledError,
  focusManager,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import {
  fetchKnowledgeChunkContext,
  fetchKnowledgeResources,
  searchKnowledge,
} from "../api/knowledge.ts";
import { fetchKnowledgeResource } from "../api/knowledgeResources.ts";
import {
  fetchKnowledgeBatch,
  type KnowledgeBatchDetail,
} from "../api/knowledgeUploads.ts";
import { shouldRetry } from "../app/queryClient.ts";

export interface SubmittedKnowledgeSearch {
  query: string;
  limit: number;
}

export const knowledgeKeys = {
  all: ["project-knowledge"] as const,
  project: (organizationId: string, projectId: string) =>
    ["project-knowledge", organizationId, projectId] as const,
  resources: (organizationId: string, projectId: string) =>
    ["project-knowledge", organizationId, projectId, "resources"] as const,
  resource: (organizationId: string, projectId: string, resourceId: string) =>
    ["project-knowledge", organizationId, projectId, "resource", resourceId] as const,
  batch: (organizationId: string, projectId: string, batchId: string) =>
    ["project-knowledge", organizationId, projectId, "batch", batchId] as const,
  searches: (organizationId: string, projectId: string) =>
    ["project-knowledge", organizationId, projectId, "search"] as const,
  search: (organizationId: string, projectId: string, query: string, limit: number) =>
    [...knowledgeKeys.searches(organizationId, projectId), query, limit] as const,
  citationContext: (
    organizationId: string,
    projectId: string,
    resourceId: string,
    resourceVersionId: string,
    chunkId: string,
  ) => [
    ...knowledgeKeys.project(organizationId, projectId),
    "citation-context",
    resourceId,
    resourceVersionId,
    chunkId,
  ] as const,
};

function sessionQuerySignal(querySignal: AbortSignal, sessionSignal: AbortSignal): AbortSignal {
  return AbortSignal.any([querySignal, sessionSignal]);
}

export function isKnowledgeBatchTerminal(status: KnowledgeBatchDetail["status"]): boolean {
  return status === "completed" || status === "completed_with_errors" || status === "failed";
}

export function shouldPollKnowledgeBatch(
  batch: KnowledgeBatchDetail,
  startedAt: number,
  now: number,
): 2_000 | false {
  if (isKnowledgeBatchTerminal(batch.status) || now - startedAt >= 300_000) return false;
  return 2_000;
}

function useAbortSignalState(signal: AbortSignal): boolean {
  const subscribe = useCallback((onStoreChange: () => void) => {
    signal.addEventListener("abort", onStoreChange, { once: true });
    return () => signal.removeEventListener("abort", onStoreChange);
  }, [signal]);
  const getSnapshot = useCallback(() => signal.aborted, [signal]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function useKnowledgeBatchQuery({
  organizationId,
  projectId,
  batchId,
  enabled,
  sessionSignal,
}: {
  organizationId: string;
  projectId: string;
  batchId: string;
  enabled: boolean;
  sessionSignal: AbortSignal;
}) {
  const queryClient = useQueryClient();
  const polling = useRef<{
    organizationId: string;
    projectId: string;
    batchId: string;
    startedAt: number | null;
  }>({ organizationId, projectId, batchId, startedAt: null });
  const batchIdentityChanged =
    polling.current.organizationId !== organizationId ||
    polling.current.projectId !== projectId ||
    polling.current.batchId !== batchId;
  if (batchIdentityChanged) {
    polling.current = { organizationId, projectId, batchId, startedAt: null };
  }
  const sessionAborted = useAbortSignalState(sessionSignal);
  const queryEnabled = enabled && !sessionAborted;
  if (queryEnabled && polling.current.startedAt === null) {
    polling.current.startedAt = performance.now();
  }
  const startedAt = polling.current.startedAt;
  const identityKey = `${organizationId}\u0000${projectId}\u0000${batchId}`;
  const [deadlineState, setDeadlineState] = useState({ identityKey, stopped: false });
  const markDeadlineStopped = useCallback(() => {
    setDeadlineState((current) =>
      current.identityKey === identityKey && current.stopped
        ? current
        : { identityKey, stopped: true }
    );
  }, [identityKey]);
  const batchData = useRef<KnowledgeBatchDetail | undefined>(undefined);
  const fetchContext = useMemo(() => ({
    manualFetchDepth: 0,
    requestInFlight: false,
  }), [identityKey, sessionSignal]);
  if (batchIdentityChanged) {
    batchData.current = undefined;
  }

  const canAutomaticallyFetch = useCallback((batch: KnowledgeBatchDetail | undefined) => (
    queryEnabled &&
    startedAt !== null &&
    !sessionSignal.aborted &&
    performance.now() - startedAt < 300_000 &&
    (batch === undefined || !isKnowledgeBatchTerminal(batch.status))
  ), [queryEnabled, sessionSignal, startedAt]);
  const canAutomaticallyRefetch = useCallback((batch: KnowledgeBatchDetail | undefined) => (
    batch !== undefined && canAutomaticallyFetch(batch)
  ), [canAutomaticallyFetch]);

  const batchQuery = useQuery({
    queryKey: knowledgeKeys.batch(organizationId, projectId, batchId),
    queryFn: async ({ signal }) => {
      // Every attempt is automatic unless an explicit refresh owns this fetch,
      // including an initial/refetch attempt that TanStack paused while offline.
      if (fetchContext.manualFetchDepth === 0 && !canAutomaticallyFetch(batchData.current)) {
        if (
          startedAt !== null && performance.now() - startedAt >= 300_000 &&
          (batchData.current === undefined || !isKnowledgeBatchTerminal(batchData.current.status))
        ) {
          markDeadlineStopped();
        }
        // Cancel the Query itself so TanStack reverts its fetch state even when
        // the first response has no cached data. Throwing alone cannot do that.
        void queryClient.cancelQueries(
          { queryKey: knowledgeKeys.batch(organizationId, projectId, batchId), exact: true },
          { revert: true, silent: true },
        );
        throw new CancelledError({ revert: true, silent: true });
      }
      fetchContext.requestInFlight = true;
      try {
        return await fetchKnowledgeBatch({
          projectId,
          batchId,
          signal: sessionQuerySignal(signal, sessionSignal),
        });
      } finally {
        fetchContext.requestInFlight = false;
      }
    },
    enabled: queryEnabled,
    retry: (failureCount, error) => {
      return shouldRetry(failureCount, error) && (
        fetchContext.manualFetchDepth > 0 || canAutomaticallyFetch(batchData.current)
      );
    },
    refetchOnWindowFocus: (query) => canAutomaticallyRefetch(query.state.data),
    refetchOnReconnect: (query) => canAutomaticallyRefetch(query.state.data),
  });
  batchData.current = batchQuery.data;
  const hasBatchData = batchQuery.data !== undefined;

  useEffect(() => {
    if (!queryEnabled || startedAt === null) return;
    const remaining = 300_000 - (performance.now() - startedAt);
    const publishIfStillNonterminal = () => {
      const batch = batchData.current;
      if (batch === undefined || !isKnowledgeBatchTerminal(batch.status)) {
        markDeadlineStopped();
      }
      const fetchStatus = queryClient.getQueryState(
        knowledgeKeys.batch(organizationId, projectId, batchId),
      )?.fetchStatus;
      if (
        fetchStatus !== undefined && fetchStatus !== "idle" &&
        !fetchContext.requestInFlight && fetchContext.manualFetchDepth === 0
      ) {
        void queryClient.cancelQueries(
          { queryKey: knowledgeKeys.batch(organizationId, projectId, batchId), exact: true },
          { revert: true, silent: true },
        );
      }
    };
    if (remaining <= 0) {
      publishIfStillNonterminal();
      return;
    }
    const deadlineTimer = setTimeout(publishIfStillNonterminal, remaining);
    return () => clearTimeout(deadlineTimer);
  }, [
    batchId,
    fetchContext,
    markDeadlineStopped,
    organizationId,
    projectId,
    queryClient,
    queryEnabled,
    startedAt,
  ]);

  useEffect(() => {
    if (!queryEnabled || !hasBatchData || startedAt === null) return;
    const pollingStartedAt = startedAt;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function clearTimer(): void {
      if (timer === undefined) return;
      clearTimeout(timer);
      timer = undefined;
    }

    function schedule(batch = batchData.current): void {
      clearTimer();
      if (batch === undefined) return;
      const now = performance.now();
      const interval = shouldPollKnowledgeBatch(batch, pollingStartedAt, now);
      if (!isKnowledgeBatchTerminal(batch.status) && now - pollingStartedAt >= 300_000) {
        markDeadlineStopped();
      }
      if (
        cancelled ||
        sessionSignal.aborted ||
        interval === false ||
        !focusManager.isFocused()
      ) return;
      const remaining = 300_000 - (now - pollingStartedAt);
      timer = setTimeout(async () => {
        timer = undefined;
        if (cancelled || sessionSignal.aborted) return;
        if (performance.now() - pollingStartedAt >= 300_000) {
          const currentBatch = batchData.current;
          if (currentBatch !== undefined && !isKnowledgeBatchTerminal(currentBatch.status)) {
            markDeadlineStopped();
          }
          return;
        }
        if (!focusManager.isFocused()) return;
        const currentBatch = batchData.current;
        if (currentBatch === undefined || isKnowledgeBatchTerminal(currentBatch.status)) return;
        const result = await batchQuery.refetch({ cancelRefetch: false });
        if (!cancelled && result.data !== undefined) schedule(result.data);
      }, Math.min(interval, remaining));
    }

    const unsubscribeFocus = focusManager.subscribe((focused) => {
      if (focused) schedule();
      else clearTimer();
    });
    schedule();
    return () => {
      cancelled = true;
      unsubscribeFocus();
      clearTimer();
    };
  }, [
    batchQuery.refetch,
    hasBatchData,
    identityKey,
    markDeadlineStopped,
    queryEnabled,
    sessionSignal,
    startedAt,
  ]);

  const automaticPollingStopped =
    deadlineState.identityKey === identityKey &&
    deadlineState.stopped &&
    (batchQuery.data === undefined || !isKnowledgeBatchTerminal(batchQuery.data.status));
  const manualRefetch = useCallback((options?: Parameters<typeof batchQuery.refetch>[0]) => {
    const current = queryClient.getQueryState(
      knowledgeKeys.batch(organizationId, projectId, batchId),
    );
    if (
      current?.fetchStatus === "fetching" &&
      (options?.cancelRefetch === false || current.data === undefined)
    ) {
      // Joining a running fetch preserves its provenance. A paused fetch has
      // not started HTTP and an explicit refresh may take ownership of it.
      return batchQuery.refetch(options);
    }
    fetchContext.manualFetchDepth += 1;
    return batchQuery.refetch(options).finally(() => {
      fetchContext.manualFetchDepth -= 1;
    });
  }, [batchId, batchQuery.refetch, fetchContext, organizationId, projectId, queryClient]);
  return { ...batchQuery, refetch: manualRefetch, automaticPollingStopped };
}

export function useKnowledgeResourcesQuery(
  organizationId: string,
  projectId: string,
  sessionSignal: AbortSignal,
) {
  return useInfiniteQuery({
    queryKey: knowledgeKeys.resources(organizationId, projectId),
    queryFn: ({ pageParam, signal }) => fetchKnowledgeResources({
      projectId,
      cursor: pageParam,
      signal: sessionQuerySignal(signal, sessionSignal),
    }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}

export function useKnowledgeResourceQuery({
  organizationId, projectId, resourceId, sessionSignal,
}: {
  organizationId: string;
  projectId: string;
  resourceId: string;
  sessionSignal: AbortSignal;
}) {
  return useQuery({
    queryKey: knowledgeKeys.resource(organizationId, projectId, resourceId),
    queryFn: ({ signal }) => fetchKnowledgeResource({
      projectId,
      resourceId,
      signal: sessionQuerySignal(signal, sessionSignal),
    }),
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnReconnect: false,
    retry: false,
  });
}

export function useKnowledgeChunkContextQuery({
  organizationId,
  projectId,
  resourceId,
  resourceVersionId,
  chunkId,
  sessionSignal,
}: {
  organizationId: string;
  projectId: string;
  resourceId: string;
  resourceVersionId: string;
  chunkId: string;
  sessionSignal: AbortSignal;
}) {
  return useQuery({
    queryKey: knowledgeKeys.citationContext(
      organizationId,
      projectId,
      resourceId,
      resourceVersionId,
      chunkId,
    ),
    queryFn: ({ signal }) => fetchKnowledgeChunkContext({
      projectId,
      resourceId,
      resourceVersionId,
      chunkId,
      signal: sessionQuerySignal(signal, sessionSignal),
    }),
    staleTime: 0,
    refetchOnMount: "always",
  });
}

export function useKnowledgeSearchQuery({
  organizationId,
  projectId,
  search,
  csrfToken,
  sessionSignal,
}: {
  organizationId: string;
  projectId: string;
  search: SubmittedKnowledgeSearch | null;
  csrfToken: string;
  sessionSignal: AbortSignal;
}) {
  return useQuery({
    queryKey: search === null
      ? [...knowledgeKeys.searches(organizationId, projectId), "idle"]
      : knowledgeKeys.search(organizationId, projectId, search.query, search.limit),
    queryFn: ({ signal }) => {
      if (search === null) throw new Error("必须先提交知识搜索");
      return searchKnowledge({
        projectId,
        query: search.query,
        limit: search.limit,
        csrfToken,
        signal: sessionQuerySignal(signal, sessionSignal),
      });
    },
    enabled: search !== null,
  });
}
