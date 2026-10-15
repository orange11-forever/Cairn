import { useEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ApiError } from "../api/errors.ts";

import {
  fetchProjects,
  fetchStages,
  fetchMilestones,
  fetchProject,
  fetchProjectTasks,
  transitionTaskStatus,
  fetchTask,
  fetchAssignees,
  fetchDependencies,
  type TaskStatus,
  type Project,
} from "../api/projects.ts";

export const projectKeys = {
  all: ["projects"] as const,
  list: (organizationId: string) => ["projects", organizationId] as const,
  detail: (organizationId: string, projectId: string) =>
    ["projects", organizationId, "detail", projectId] as const,
};

export const structureKeys = {
  scope: (org: string, project: string) => ["project-structure", org, project] as const,
};

export const taskKeys = {
  all: ["project-tasks"] as const,
  list: (organizationId: string, projectId: string) =>
    ["project-tasks", organizationId, projectId] as const,
  detailScope: (org: string, project: string) =>
    ["task-detail", org, project] as const,
  dependencyScope: (org: string, project: string) =>
    ["task-dependencies", org, project] as const,
  detail: (org: string, project: string, task: string) =>
    ["task-detail", org, project, task] as const,
  dependencies: (org: string, project: string, task: string) =>
    ["task-dependencies", org, project, task] as const,
  assignees: (org: string, project: string) =>
    ["task-assignees", org, project] as const,
};

function sessionQuerySignal(
  querySignal: AbortSignal,
  sessionSignal: AbortSignal,
): AbortSignal {
  return AbortSignal.any([querySignal, sessionSignal]);
}

export function useProjectQuery(
  organizationId: string,
  projectId: string,
  sessionSignal: AbortSignal,
) {
  return useQuery({
    queryKey: projectKeys.detail(organizationId, projectId),
    queryFn: ({ signal }) =>
      fetchProject({
        projectId,
        signal: sessionQuerySignal(signal, sessionSignal),
      }),
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
}

export function useProjectsQuery(
  organizationId: string,
  sessionSignal: AbortSignal,
  enabled = true,
) {
  return useInfiniteQuery({
    queryKey: projectKeys.list(organizationId),
    enabled,
    queryFn: ({ pageParam, signal }) =>
      fetchProjects({
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
    queryKey:
      projectId === null
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
  const active = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  type Variables = {
    projectId: string;
    taskId: string;
    status: TaskStatus;
    expectedRevision?: number;
  };
  type Recovery = {
    kind: "conflict" | "refresh_failed";
    projectId: string;
    taskId: string;
    message: string;
  };
  const [recovery, setRecovery] = useState<Recovery | null>(null);
  const [rereading, setRereading] = useState(false);
  const [rereadVersion, setRereadVersion] = useState(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      active.current?.abort();
    };
  }, []);
  function current() {
    return (
      mounted.current &&
      !sessionSignal.aborted &&
      !active.current?.signal.aborted
    );
  }
  async function refresh(projectId: string) {
    await Promise.all([
      refreshProjectStructure(queryClient, organizationId, projectId),
      queryClient.invalidateQueries(
        {
          queryKey: taskKeys.detailScope(organizationId, projectId),
          refetchType: "active",
        },
        { throwOnError: true },
      ),
      queryClient.invalidateQueries(
        {
          queryKey: taskKeys.dependencyScope(organizationId, projectId),
          refetchType: "active",
        },
        { throwOnError: true },
      ),
      queryClient.invalidateQueries(
        {
          queryKey: taskKeys.list(organizationId, projectId),
          exact: true,
          refetchType: "all",
        },
        { throwOnError: true },
      ),
    ]);
  }
  const mutation = useMutation({
    mutationFn: ({ taskId, status, expectedRevision }: Variables) => {
      active.current?.abort();
      active.current = new AbortController();
      return transitionTaskStatus({
        taskId,
        status,
        expectedRevision,
        csrfToken,
        signal: AbortSignal.any([sessionSignal, active.current.signal]),
      });
    },
    onError: (error, variables) => {
      if (
        current() &&
        error instanceof ApiError &&
        error.code === "revision_conflict"
      ) {
        setRecovery({
          kind: "conflict",
          projectId: variables.projectId,
          taskId: variables.taskId,
          message: error.message,
        });
      }
    },
    onSuccess: async (task, variables) => {
      if (!current()) return;
      try {
        await refresh(variables.projectId);
        if (!current()) return;
        const fresh = queryClient.getQueryData<
          import("../api/projects.ts").Task
        >(
          taskKeys.detail(
            organizationId,
            variables.projectId,
            variables.taskId,
          ),
        );
        const observed = queryClient
          .getQueryCache()
          .find({
            queryKey: taskKeys.detail(
              organizationId,
              variables.projectId,
              variables.taskId,
            ),
            exact: true,
          })
          ?.isActive();
        if (observed && fresh && fresh.revision !== task.revision) {
          setRecovery({
            kind: "conflict",
            projectId: variables.projectId,
            taskId: variables.taskId,
            message: "状态更新已提交，但任务已有其他更新，请重新读取最新版本。",
          });
        }
      } catch (error) {
        if (current())
          setRecovery({
            kind: "refresh_failed",
            projectId: variables.projectId,
            taskId: variables.taskId,
            message: error instanceof Error ? error.message : "任务刷新失败",
          });
      }
    },
  });
  async function reread() {
    if (!recovery || rereading || !current()) return;
    setRereading(true);
    try {
      await refresh(recovery.projectId);
      if (current()) {
        setRecovery(null);
        setRereadVersion((value) => value + 1);
        mutation.reset();
      }
    } catch (error) {
      if (current())
        setRecovery(
          (previous) =>
            previous && {
              ...previous,
              message: error instanceof Error ? error.message : "重新读取失败",
            },
        );
    } finally {
      if (current()) setRereading(false);
    }
  }
  return { ...mutation, recovery, rereading, rereadVersion, reread };
}

export function useTaskQuery(
  org: string,
  projectId: string,
  taskId: string,
  sessionSignal: AbortSignal,
) {
  return useQuery({
    queryKey: taskKeys.detail(org, projectId, taskId),
    queryFn: ({ signal }) =>
      fetchTask({
        taskId,
        projectId,
        signal: sessionQuerySignal(signal, sessionSignal),
      }),
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useAssigneesQuery(
  org: string,
  projectId: string,
  sessionSignal: AbortSignal,
) {
  return useInfiniteQuery({
    queryKey: taskKeys.assignees(org, projectId),
    queryFn: ({ pageParam, signal }) =>
      fetchAssignees({
        projectId,
        cursor: pageParam,
        signal: sessionQuerySignal(signal, sessionSignal),
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
    retry: false,
  });
}

export function useDependenciesQuery(
  org: string,
  projectId: string,
  taskId: string,
  sessionSignal: AbortSignal,
) {
  return useInfiniteQuery({
    queryKey: taskKeys.dependencies(org, projectId, taskId),
    queryFn: ({ pageParam, signal }) =>
      fetchDependencies({
        taskId,
        cursor: pageParam,
        signal: sessionQuerySignal(signal, sessionSignal),
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
    retry: false,
  });
}

export function useStagesQuery(org: string, projectId: string, sessionSignal: AbortSignal) {
  return useInfiniteQuery({
    queryKey: [...structureKeys.scope(org, projectId), "stages"],
    queryFn: ({
      pageParam,
      signal
    }) => fetchStages({
      projectId,
      cursor: pageParam,
      signal: sessionQuerySignal(signal, sessionSignal)
    }),
    initialPageParam: null as string | null,
    getNextPageParam: page => page.nextCursor ?? undefined,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false
  });
}
export function useMilestonesQuery(org: string, projectId: string, sessionSignal: AbortSignal) {
  return useInfiniteQuery({
    queryKey: [...structureKeys.scope(org, projectId), "milestones"],
    queryFn: ({
      pageParam,
      signal
    }) => fetchMilestones({
      projectId,
      cursor: pageParam,
      signal: sessionQuerySignal(signal, sessionSignal)
    }),
    initialPageParam: null as string | null,
    getNextPageParam: page => page.nextCursor ?? undefined,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false
  });
}
export async function refreshProjectStructure(client: ReturnType<typeof useQueryClient>, org: string, project: string) {
  await Promise.all([client.invalidateQueries({
    queryKey: projectKeys.detail(org, project),
    exact: true,
    refetchType: "active"
  }, {
    throwOnError: true
  }), client.invalidateQueries({
    queryKey: structureKeys.scope(org, project),
    refetchType: "active"
  }, {
    throwOnError: true
  })]);
  if (!client.getQueryData<Project>(projectKeys.detail(org, project))?.revision) throw new Error("项目版本缺失，请重新读取。");
}
