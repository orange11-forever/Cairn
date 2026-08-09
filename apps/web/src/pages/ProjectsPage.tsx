import { CalendarDays, ClipboardCheck, Flag, FolderKanban, ListChecks } from "lucide-react";
import { useState } from "react";

import type { Project, Task, TaskStatus } from "../api/projects.ts";
import {
  useProjectsQuery,
  useProjectTasksQuery,
  useTaskTransition,
} from "../queries/projects.ts";
import { useSession } from "../session/SessionContext.tsx";

const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  backlog: "待规划",
  todo: "待处理",
  in_progress: "进行中",
  blocked: "已阻塞",
  done: "已完成",
  cancelled: "已取消",
};

const TASK_PRIORITY_LABELS: Record<Task["priority"], string> = {
  low: "低优先级",
  medium: "中优先级",
  high: "高优先级",
  critical: "紧急",
};

const TASK_TRANSITIONS: Record<
  TaskStatus,
  ReadonlyArray<{ status: TaskStatus; label: string }>
> = {
  backlog: [{ status: "todo", label: "移至待处理" }],
  todo: [{ status: "in_progress", label: "开始任务" }],
  in_progress: [
    { status: "done", label: "完成任务" },
    { status: "blocked", label: "标记阻塞" },
    { status: "cancelled", label: "取消任务" },
  ],
  blocked: [{ status: "in_progress", label: "继续任务" }],
  done: [],
  cancelled: [],
};

const DUE_DATE_FORMAT = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "long",
  day: "numeric",
});

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

export function ProjectsPage() {
  const { session } = useSession();
  if (session === null) return null;

  return (
    <ProjectsWorkspace
      csrfToken={session.identity.csrfToken}
      organizationId={session.identity.organization.id}
      signal={session.signal}
    />
  );
}

function ProjectsWorkspace({
  csrfToken,
  organizationId,
  signal,
}: {
  csrfToken: string;
  organizationId: string;
  signal: AbortSignal;
}) {
  const projects = useProjectsQuery(organizationId, signal);
  const [requestedProjectId, setRequestedProjectId] = useState<string | null>(null);

  if (projects.isPending) {
    return (
      <section className="projects-page" aria-busy="true" aria-label="项目工作区">
        <PageHeading />
        <div className="project-workbench project-workbench-skeleton">
          <div className="project-skeleton project-skeleton-rail">
            <span>正在加载项目</span>
          </div>
          <div className="project-skeleton project-skeleton-tasks" aria-hidden="true" />
        </div>
      </section>
    );
  }

  if (projects.isError && projects.data === undefined) {
    return (
      <section className="projects-page" aria-label="项目工作区">
        <PageHeading />
        <div className="project-state project-state-error">
          <p role="alert">
            {errorMessage(projects.error, "项目暂时无法加载，请重试")}
          </p>
          <button type="button" onClick={() => void projects.refetch()}>
            重新加载项目
          </button>
        </div>
      </section>
    );
  }

  const projectItems = projects.data.pages.flatMap((page) => page.items);
  const firstProject = projectItems[0];
  const projectRefreshError = projects.isRefetchError && !projects.isFetchNextPageError ? (
    <RefreshError
      className="project-refresh-error"
      context="项目列表可能不是最新。"
      error={projects.error}
      errorFallback="项目列表刷新失败，请重试"
      idleLabel="重试刷新项目"
      loadingLabel="正在刷新项目"
      pending={projects.isRefetching}
      onRetry={() => void projects.refetch()}
    />
  ) : null;

  if (firstProject === undefined) {
    return (
      <section className="projects-page" aria-label="项目工作区">
        <PageHeading />
        {projectRefreshError}
        <div className="project-state project-state-empty">
          <FolderKanban aria-hidden="true" size={28} strokeWidth={1.8} />
          <div>
            <h2>还没有项目</h2>
            <p>项目创建后会显示在这里。</p>
          </div>
        </div>
      </section>
    );
  }

  const selectedProject =
    projectItems.find((project) => project.id === requestedProjectId) ?? firstProject;

  return (
    <section className="projects-page" aria-label="项目工作区">
      <PageHeading />
      {projectRefreshError}
      <div className="project-mobile-switcher">
        <label htmlFor="project-switcher">切换项目</label>
        <select
          id="project-switcher"
          value={selectedProject.id}
          onChange={(event) => setRequestedProjectId(event.target.value)}
        >
          {projectItems.map((project) => (
            <option key={project.id} value={project.id}>{project.name}</option>
          ))}
        </select>
      </div>
      <div className="project-workbench">
        <aside className="project-rail" aria-label="项目列表">
          <div className="project-rail-heading">
            <h2>项目</h2>
            <span>已加载 {projectItems.length} 个</span>
          </div>
          <ul>
            {projectItems.map((project) => (
              <li key={project.id}>
                <button
                  type="button"
                  aria-pressed={project.id === selectedProject.id}
                  onClick={() => setRequestedProjectId(project.id)}
                >
                  <strong>{project.name}</strong>
                  <span>{project.description ?? "暂无项目说明"}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <TaskWorkspace
          key={selectedProject.id}
          csrfToken={csrfToken}
          organizationId={organizationId}
          project={selectedProject}
          signal={signal}
        />
      </div>
      {projects.hasNextPage ? (
        <PaginationAction
          className="project-pagination"
          error={projects.isFetchNextPageError ? projects.error : null}
          errorFallback="更多项目暂时无法加载，请重试"
          idleLabel={projects.isFetchNextPageError ? "重新加载更多项目" : "加载更多项目"}
          loadingLabel="正在加载更多项目"
          pending={projects.isFetchingNextPage}
          onLoadMore={() => void projects.fetchNextPage()}
        />
      ) : null}
    </section>
  );
}

function PageHeading() {
  return (
    <header className="projects-heading">
      <div>
        <h1>项目任务</h1>
        <p>选择项目，查看任务并更新进度。</p>
      </div>
    </header>
  );
}

function TaskWorkspace({
  csrfToken,
  organizationId,
  project,
  signal,
}: {
  csrfToken: string;
  organizationId: string;
  project: Project;
  signal: AbortSignal;
}) {
  const tasks = useProjectTasksQuery(organizationId, project.id, signal);
  const transition = useTaskTransition({
    organizationId,
    csrfToken,
    sessionSignal: signal,
  });
  const taskItems = tasks.data?.pages.flatMap((page) => page.items) ?? [];
  const hasTaskRefetchError = tasks.isRefetchError && !tasks.isFetchNextPageError;
  const transitionRefreshFailed = hasTaskRefetchError
    && transition.isSuccess
    && tasks.dataUpdatedAt <= transition.submittedAt;

  return (
    <div className="task-workspace" aria-label={`${project.name}任务`}>
      <header className="task-workspace-heading">
        <div>
          <h2>{project.name}</h2>
          <p>{project.description ?? "暂无项目说明"}</p>
        </div>
        <ListChecks aria-hidden="true" size={22} strokeWidth={1.8} />
      </header>

      {tasks.isPending ? (
        <div className="task-loading" aria-busy="true">
          <span className="project-skeleton">正在加载任务</span>
          <span className="project-skeleton" aria-hidden="true" />
        </div>
      ) : null}

      {tasks.isError && tasks.data === undefined ? (
        <div className="project-state project-state-error task-state">
          <p role="alert">{errorMessage(tasks.error, "任务暂时无法加载，请重试")}</p>
          <button type="button" onClick={() => void tasks.refetch()}>
            重新加载任务
          </button>
        </div>
      ) : null}

      {hasTaskRefetchError ? (
        <RefreshError
          className="task-state"
          context={transitionRefreshFailed
            ? "任务更新已提交，但列表刷新失败，当前数据可能不是最新。"
            : "任务列表可能不是最新。"}
          error={tasks.error}
          errorFallback="任务列表刷新失败，请重试"
          idleLabel="重试刷新任务"
          loadingLabel="正在刷新任务"
          pending={tasks.isRefetching}
          onRetry={() => void tasks.refetch()}
        />
      ) : null}

      {tasks.data !== undefined && taskItems.length === 0 ? (
        <div className="project-state project-state-empty task-state">
          <ClipboardCheck aria-hidden="true" size={26} strokeWidth={1.8} />
          <div>
            <h2>这个项目还没有任务</h2>
            <p>任务创建后会显示在当前工作区。</p>
          </div>
        </div>
      ) : null}

      {transition.isError ? (
        <p className="task-transition-error" role="alert">
          {errorMessage(transition.error, "任务状态更新失败，请重试")}
        </p>
      ) : null}

      {taskItems.length > 0 ? (
        <div className="task-list" aria-label="任务列表">
          {taskItems.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              actionsDisabled={transition.isPending || hasTaskRefetchError}
              pending={transition.isPending}
              pendingTaskId={transition.variables?.taskId ?? null}
              onTransition={(status) => transition.mutate({
                projectId: project.id,
                taskId: task.id,
                status,
              })}
            />
          ))}
          {tasks.hasNextPage ? (
            <PaginationAction
              className="task-pagination"
              error={tasks.isFetchNextPageError ? tasks.error : null}
              errorFallback="更多任务暂时无法加载，请重试"
              idleLabel={tasks.isFetchNextPageError ? "重新加载更多任务" : "加载更多任务"}
              loadingLabel="正在加载更多任务"
              pending={tasks.isFetchingNextPage}
              onLoadMore={() => void tasks.fetchNextPage()}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PaginationAction({
  className,
  error,
  errorFallback,
  idleLabel,
  loadingLabel,
  pending,
  onLoadMore,
}: {
  className: string;
  error: unknown;
  errorFallback: string;
  idleLabel: string;
  loadingLabel: string;
  pending: boolean;
  onLoadMore(): void;
}) {
  return (
    <div className={className}>
      {error !== null ? <p role="alert">{errorMessage(error, errorFallback)}</p> : null}
      <button type="button" disabled={pending} onClick={onLoadMore}>
        {pending ? loadingLabel : idleLabel}
      </button>
    </div>
  );
}

function RefreshError({
  className,
  context,
  error,
  errorFallback,
  idleLabel,
  loadingLabel,
  pending,
  onRetry,
}: {
  className: string;
  context: string;
  error: unknown;
  errorFallback: string;
  idleLabel: string;
  loadingLabel: string;
  pending: boolean;
  onRetry(): void;
}) {
  return (
    <div className={`project-state project-state-error ${className}`}>
      <p role="alert">
        <strong>{context}</strong>{" "}{errorMessage(error, errorFallback)}
      </p>
      <button type="button" disabled={pending} onClick={onRetry}>
        {pending ? loadingLabel : idleLabel}
      </button>
    </div>
  );
}

function TaskRow({
  task,
  actionsDisabled,
  pending,
  pendingTaskId,
  onTransition,
}: {
  task: Task;
  actionsDisabled: boolean;
  pending: boolean;
  pendingTaskId: string | null;
  onTransition(status: TaskStatus): void;
}) {
  const isCurrentTransition = pending && pendingTaskId === task.id;

  return (
    <article className="task-row" aria-label={task.title} data-status={task.status}>
      <div className="task-row-main">
        <div className="task-title-line">
          <h3>{task.title}</h3>
          <span className="task-status" data-status={task.status}>
            {TASK_STATUS_LABELS[task.status]}
          </span>
        </div>
        <dl className="task-metadata">
          <div>
            <dt><Flag aria-hidden="true" size={15} strokeWidth={1.8} />优先级</dt>
            <dd>{TASK_PRIORITY_LABELS[task.priority]}</dd>
          </div>
          <div>
            <dt><CalendarDays aria-hidden="true" size={15} strokeWidth={1.8} />到期日</dt>
            <dd>{task.dueAt === null ? "未设置" : DUE_DATE_FORMAT.format(new Date(task.dueAt))}</dd>
          </div>
        </dl>
        <div className="task-acceptance">
          <h4>验收标准</h4>
          <p>{task.acceptanceCriteria ?? "未填写"}</p>
        </div>
      </div>
      {TASK_TRANSITIONS[task.status].length > 0 ? (
        <div className="task-actions" aria-label="状态操作">
          {TASK_TRANSITIONS[task.status].map((action) => (
            <button
              key={action.status}
              type="button"
              disabled={actionsDisabled}
              onClick={() => onTransition(action.status)}
            >
              {isCurrentTransition ? "正在更新" : action.label}
            </button>
          ))}
        </div>
      ) : (
        <p className="task-terminal-state">当前状态无需操作</p>
      )}
    </article>
  );
}
