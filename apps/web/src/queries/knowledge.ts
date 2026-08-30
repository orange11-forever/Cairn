import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  fetchKnowledgeChunkContext,
  fetchKnowledgeResources,
  searchKnowledge,
} from "../api/knowledge.ts";

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
