import { CancelledError, useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../api/errors.ts";
import {
  fetchFeishuSync, fetchFeishuSyncs, fetchKnowledgeSources,
  type KnowledgeSourceSync,
} from "../api/knowledgeSources.ts";
import { knowledgeKeys } from "./knowledge.ts";

export const sourceKeys = {
  list: (organizationId: string, projectId: string) =>
    [...knowledgeKeys.project(organizationId, projectId), "sources"] as const,
  history: (organizationId: string, projectId: string, sourceId: string) =>
    [...knowledgeKeys.project(organizationId, projectId), "source-syncs", sourceId] as const,
  sync: (organizationId: string, projectId: string, sourceId: string, syncId: string) =>
    [...knowledgeKeys.project(organizationId, projectId), "source-sync", sourceId, syncId] as const,
};

export function usePrivatePageActive(sessionSignal: AbortSignal): boolean {
  const [active, setActive] = useState(() =>
    !sessionSignal.aborted && document.visibilityState === "visible" && navigator.onLine);
  useEffect(() => {
    const update = () => setActive(!sessionSignal.aborted &&
      document.visibilityState === "visible" && navigator.onLine);
    document.addEventListener("visibilitychange", update);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    sessionSignal.addEventListener("abort", update);
    update();
    return () => {
      document.removeEventListener("visibilitychange", update);
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
      sessionSignal.removeEventListener("abort", update);
    };
  }, [sessionSignal]);
  return active;
}

export async function clearProjectKnowledge(queryClient: ReturnType<typeof useQueryClient>,
  organizationId: string, projectId: string): Promise<void> {
  const queryKey = knowledgeKeys.project(organizationId, projectId);
  await queryClient.cancelQueries({ queryKey });
  queryClient.removeQueries({ queryKey });
}

export async function clearProjectKnowledgeContent(queryClient: ReturnType<typeof useQueryClient>,
  organizationId: string, projectId: string): Promise<void> {
  const filter = { predicate: ({ queryKey }: { queryKey: readonly unknown[] }) =>
    queryKey[0] === "project-knowledge" && queryKey[1] === organizationId &&
    queryKey[2] === projectId && !["sources", "source-syncs", "source-sync"].includes(String(queryKey[3])) };
  await queryClient.cancelQueries(filter);
  queryClient.removeQueries(filter);
}

function privateReadSignal(querySignal: AbortSignal, sessionSignal: AbortSignal): AbortSignal {
  const signal = AbortSignal.any([querySignal, sessionSignal]);
  if (signal.aborted || document.visibilityState !== "visible" || !navigator.onLine) {
    throw new CancelledError({ revert: true, silent: true });
  }
  return signal;
}

export function useFeishuSources(organizationId: string, projectId: string,
  sessionSignal: AbortSignal, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: sourceKeys.list(organizationId, projectId),
    enabled,
    queryFn: ({ pageParam, signal }) => fetchKnowledgeSources({
      projectId, cursor: pageParam, signal: privateReadSignal(signal, sessionSignal),
    }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    retry: false,
    refetchOnMount: "always",
    refetchOnReconnect: false,
    networkMode: "always",
  });
}

export function useFeishuHistory(organizationId: string, projectId: string, sourceId: string | null,
  sessionSignal: AbortSignal, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: sourceKeys.history(organizationId, projectId, sourceId ?? "none"),
    enabled: enabled && sourceId !== null,
    queryFn: ({ pageParam, signal }) => {
      if (sourceId === null) throw new ApiError("aborted", "未选择来源");
      return fetchFeishuSyncs({ projectId, sourceId, cursor: pageParam,
        signal: privateReadSignal(signal, sessionSignal) });
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    retry: false,
    refetchOnMount: "always",
    refetchOnReconnect: false,
    networkMode: "always",
  });
}

export function shouldPollFeishuSync(sync: KnowledgeSourceSync | undefined,
  startedAt: number, now: number): boolean {
  if (sync === undefined || now - startedAt >= 300_000) return false;
  return sync.status === "queued" || sync.status === "running" ||
    (sync.status === "completed" &&
      (sync.resourceStatus === "queued" || sync.resourceStatus === "processing"));
}

export function useFeishuSync(organizationId: string, projectId: string, sourceId: string | null,
  syncId: string | null, sessionSignal: AbortSignal, enabled: boolean) {
  const queryClient = useQueryClient();
  const identity = `${organizationId}:${projectId}:${sourceId}:${syncId}`;
  const polling = useRef({ identity, startedAt: performance.now() });
  const manual = useRef(false);
  if (polling.current.identity !== identity) {
    polling.current = { identity, startedAt: performance.now() };
    manual.current = false;
  }
  const [deadline, setDeadline] = useState(0);
  const key = useMemo(() => sourceKeys.sync(organizationId, projectId, sourceId ?? "none", syncId ?? "none"),
    [organizationId, projectId, sourceId, syncId]);
  const query = useQuery({
    queryKey: key,
    enabled: enabled && sourceId !== null && syncId !== null,
    queryFn: ({ signal }) => {
      if (sourceId === null || syncId === null) throw new ApiError("aborted", "未选择同步记录");
      if (sessionSignal.aborted || document.visibilityState !== "visible" || !navigator.onLine ||
        (!manual.current && performance.now() - polling.current.startedAt >= 300_000)) {
        throw new CancelledError({ revert: true, silent: true });
      }
      return fetchFeishuSync({ projectId, sourceId, syncId, signal: AbortSignal.any([signal, sessionSignal]) });
    },
    retry: false,
    refetchOnMount: "always",
    refetchOnReconnect: false,
    networkMode: "always",
    refetchInterval: (current) => enabled && shouldPollFeishuSync(current.state.data, polling.current.startedAt, performance.now())
      ? 2_000 : false,
  });
  const active = shouldPollFeishuSync(query.data, polling.current.startedAt, performance.now());
  useEffect(() => {
    if (!enabled || !active || sourceId === null || syncId === null) return;
    const remaining = 300_000 - (performance.now() - polling.current.startedAt);
    const timer = window.setTimeout(() => {
      setDeadline((value) => value + 1);
      void queryClient.cancelQueries({ queryKey: key, exact: true });
    }, Math.max(0, remaining));
    return () => window.clearTimeout(timer);
  }, [active, enabled, key, queryClient, sourceId, syncId, deadline]);
  const refresh = useCallback(async () => {
    manual.current = true;
    try { return await query.refetch(); } finally { manual.current = false; }
  }, [query.refetch]);
  return { ...query, refresh, automaticPollingStopped: query.data !== undefined &&
    !shouldPollFeishuSync(query.data, polling.current.startedAt, performance.now()) &&
    (query.data.status === "queued" || query.data.status === "running" ||
      (query.data.status === "completed" &&
        (query.data.resourceStatus === "queued" || query.data.resourceStatus === "processing"))) };
}
