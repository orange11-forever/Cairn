import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchProjects,
  fetchProject,
  fetchProjectTasks,
  transitionTaskStatus,
  type TaskStatus,
} from "../api/projects.ts";

export const projectKeys = {
  all: ["projects"] as const,
  list: (organizationId: string) => ["projects", organizationId] as const,
  detail: (organizationId: string, projectId: string) =>
    ["projects", organizationId, "detail", projectId] as const,
};

export const taskKeys = {
  all: ["project-tasks"] as const,
  list: (organizationId: string, projectId: string) =>
    ["project-tasks", organizationId, projectId] as const,
};

function sessionQuerySignal(querySignal: AbortSignal, sessionSignal: AbortSignal): AbortSignal {
  return AbortSignal.any([querySignal, sessionSignal]);
}

export function useProjectQuery(
  organizationId: string,
  projectId: string,
  sessionSignal: AbortSignal,
) {
  return useQuery({
    queryKey: projectKeys.detail(organizationId, projectId),
    queryFn: ({ signal }) => fetchProject({
      projectId,
      signal: sessionQuerySignal(signal, sessionSignal),
    }),
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
}

export function useProjectsQuery(organizationId: string, sessionSignal: AbortSignal) {
  return useInfiniteQuery({
    queryKey: projectKeys.list(organizationId),
    queryFn: ({ pageParam, signal }) => fetchProjects({
      cursor: pageParam,
      signal: sessionQuerySignal(signal, sessionSignal),
    }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}

export function useProjectTasksQuery(
  organizationId: string,
  projectId: string | null,
  sessionSignal: AbortSignal,
) {
  return useInfiniteQuery({
    queryKey: projectId === null
      ? [...taskKeys.all, organizationId, "none"]
      : taskKeys.list(organizationId, projectId),
    queryFn: ({ pageParam, signal }) => {
      if (projectId === null) throw new Error("必须先选择项目");
      return fetchProjectTasks({
        projectId,
        cursor: pageParam,
        signal: sessionQuerySignal(signal, sessionSignal),
      });
    },
    enabled: projectId !== null,
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}

export function useTaskTransition({
  organizationId,
  csrfToken,
  sessionSignal,
}: {
  organizationId: string;
  csrfToken: string;
  sessionSignal: AbortSignal;
}) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskId, status }: {
      projectId: string;
      taskId: string;
      status: TaskStatus;
    }) =>
      transitionTaskStatus({ taskId, status, csrfToken, signal: sessionSignal }),
    onSuccess: async (_task, variables) => {
      await queryClient.invalidateQueries({
        queryKey: taskKeys.list(organizationId, variables.projectId),
        exact: true,
        refetchType: "all",
      });
    },
  });
}
