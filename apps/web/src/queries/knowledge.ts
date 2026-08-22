import { useInfiniteQuery } from "@tanstack/react-query";

import { fetchKnowledgeResources } from "../api/knowledge.ts";

export const knowledgeKeys = {
  all: ["project-knowledge"] as const,
  project: (organizationId: string, projectId: string) =>
    ["project-knowledge", organizationId, projectId] as const,
  resources: (organizationId: string, projectId: string) =>
    ["project-knowledge", organizationId, projectId, "resources"] as const,
  search: (organizationId: string, projectId: string, query: string, limit: number) =>
    ["project-knowledge", organizationId, projectId, "search", query, limit] as const,
};

function sessionQuerySignal(querySignal: AbortSignal, sessionSignal: AbortSignal): AbortSignal {
  return AbortSignal.any([querySignal, sessionSignal]);
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
