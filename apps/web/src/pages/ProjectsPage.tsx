import {
  CalendarDays,
  ClipboardCheck,
  Flag,
  ListChecks,
  ChevronDown,
  Waypoints,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { TaskEditor } from "../components/projects/TaskEditor.tsx";
import { TaskDetails } from "../components/projects/TaskDetails.tsx";
import { ProjectStructure } from "../components/projects/ProjectStructure.tsx";
import { ProjectAnalysis } from "../components/projects/ProjectAnalysis.tsx";
import { ProjectSchedule } from "../components/projects/ProjectSchedule.tsx";
import { ProjectTaskGraph } from "../components/projects/ProjectTaskGraph.tsx";
import { ProjectCreator } from "../components/projects/ProjectCreator.tsx";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import type { Project, Task, TaskStatus } from "../api/projects.ts";
import { ApiError } from "../api/errors.ts";
import { clearLastProject, readLastProject, writeLastProject } from "../app/lastProject.ts";
import { projectPath } from "../app/projectRoutes.ts";
import { useToast } from "../components/toast/ToastContext.tsx";
import { CairnLoader, CairnStack } from "../components/trail/CairnLoader.tsx";
import { EmptyState } from "../components/trail/EmptyState.tsx";
import { StatusStone } from "../components/trail/Stone.tsx";
import { ProgressCairn } from "../components/trail/ProgressCairn.tsx";
import { TrailBreadcrumb } from "../components/trail/TrailBreadcrumb.tsx";
import { formatCalendarDate } from "../lib/dateTime.ts";
import { PRIORITY_CODES, PRIORITY_LABELS } from "../lib/priority.ts";
import {
  taskKeys,
  refreshProjectStructure,
  useStagesQuery,
  useMilestonesQuery,
  useProjectsQuery,
  useProjectTasksQuery,
  useProjectQuery,
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

const ACTION_CLASS: Partial<Record<TaskStatus, string>> = { done: "btn-primary", cancelled: "btn-danger" };

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
  return error instanceof Error && error.message.trim()
    ? error.message
    : fallback;
}

function taskWorkspaceId(projectId: string): string {
  return `project-task-workspace-${projectId}`;
}

const CREATE_ROLES = ["owner", "admin", "member"];

function ProjectsLoading() {
  return (
    <section aria-busy="true" aria-label="项目工作区" className="projects-page">
      <CairnLoader label="正在加载项目" />
    </section>
  );
}

export function ProjectsPage() {
  const { session } = useSession();
  if (session === null) return null;
  return (
    <ProjectsIndex
      key={session.identity.organization.id}
      membershipRole={session.identity.membership.role}
      organizationId={session.identity.organization.id}
      signal={session.signal}
    />
  );
}

function ProjectsIndex({ organizationId, membershipRole, signal }: {
  organizationId: string; membershipRole: string; signal: AbortSignal;
}) {
  const [remembered] = useState(() => readLastProject(window.localStorage, organizationId));
  const rememberedProject = useProjectQuery(organizationId, remembered ?? "", signal, remembered !== null);
  const projects = useProjectsQuery(organizationId, signal);
  const rememberedUnavailable = rememberedProject.error instanceof ApiError
    && (rememberedProject.error.status === 403 || rememberedProject.error.status === 404);
  useEffect(() => {
    if (rememberedUnavailable) clearLastProject(window.localStorage, organizationId);
  }, [rememberedUnavailable, organizationId]);

  if (remembered !== null) {
    if (rememberedProject.isSuccess) return <Navigate replace to={projectPath(remembered, "tasks")} />;
    if (rememberedProject.isPending) return <ProjectsLoading />;
    if (!rememberedUnavailable) return (
      <section aria-label="项目工作区" className="projects-page">
        <div className="project-state project-state-error">
          <p role="alert">{errorMessage(rememberedProject.error, "上次打开的项目暂时无法读取，请重试")}</p>
          <button type="button" onClick={() => void rememberedProject.refetch()}>重新读取项目</button>
        </div>
      </section>
    );
  }
  if (projects.isPending) return <ProjectsLoading />;
  if (projects.isError && projects.data === undefined) return (
    <section aria-label="项目工作区" className="projects-page">
      <div className="project-state project-state-error">
        <p role="alert">{errorMessage(projects.error, "项目暂时无法加载，请重试")}</p>
        <button type="button" onClick={() => void projects.refetch()}>重新加载项目</button>
      </div>
    </section>
  );
  const first = projects.data.pages[0]?.items[0];
  if (first !== undefined) return <Navigate replace to={projectPath(first.id, "tasks")} />;
  return (
    <section aria-label="项目工作区" className="projects-page">
      {projects.isRefetchError ? (
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
      ) : null}
      <EmptyState
        action={CREATE_ROLES.includes(membershipRole)
          ? <Link className="btn-primary project-first-create" to="/projects/new">创建第一个项目</Link>
          : undefined}
        description="项目创建后会显示在这里。"
        drawKey="projects-empty"
        title="还没有项目"
      />
    </section>
  );
}

export function ProjectCreatePage() {
  const { session } = useSession();
  if (session === null) return null;
  if (!CREATE_ROLES.includes(session.identity.membership.role)) return <Navigate replace to="/projects" />;
  return (
    <ProjectCreate
      csrfToken={session.identity.csrfToken}
      key={session.identity.organization.id}
      organizationId={session.identity.organization.id}
      signal={session.signal}
    />
  );
}

function ProjectCreate({ csrfToken, organizationId, signal }: {
  csrfToken: string; organizationId: string; signal: AbortSignal;
}) {
  const projects = useProjectsQuery(organizationId, signal);
  const navigate = useNavigate();
  const { notify } = useToast();

  async function rereadProjects(targetId?: string) {
    let result = await projects.refetch();
    if (result.isError) throw result.error;
    while (!signal.aborted && result.data?.pages.at(-1)?.nextCursor != null
      && (!targetId || !result.data?.pages.some(page => page.items.some(project => project.id === targetId)))) {
      result = await projects.fetchNextPage({ cancelRefetch: false });
      if (result.isError) throw result.error;
    }
    if (signal.aborted) return [];
    if (targetId && !result.data?.pages.some(page => page.items.some(project => project.id === targetId)))
      throw new Error("完整列表中仍未找到已创建的项目，请重新读取项目；无需再次创建。");
    return result.data!.pages.flatMap(page => page.items);
  }

  async function enterCreatedProject(project: Project) {
    await rereadProjects(project.id);
    if (signal.aborted) return;
    notify({ title: "项目已创建", detail: project.name });
    navigate(projectPath(project.id, "tasks"));
  }

  return (
    <section aria-label="新建项目" className="projects-page">
      <TrailBreadcrumb items={[{ label: "项目", to: "/projects" }, { label: "新建项目" }]} />
      <h1 className="projects-create-title">新建项目</h1>
      <ProjectCreator
        csrfToken={csrfToken}
        onCancel={() => navigate("/projects")}
        onCreated={enterCreatedProject}
        onInspect={() => rereadProjects()}
        signal={signal}
      />
    </section>
  );
}

export function ProjectTasksPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { session } = useSession();
  if (projectId === undefined) return <Navigate replace to="/projects" />;
  if (session === null) return null;
  return (
    <ProjectTasks
      csrfToken={session.identity.csrfToken}
      key={`${session.identity.organization.id}:${projectId}`}
      membershipRole={session.identity.membership.role}
      organizationId={session.identity.organization.id}
      projectId={projectId}
      signal={session.signal}
    />
  );
}

function ProjectTasks({ csrfToken, membershipRole, organizationId, projectId, signal }: {
  csrfToken: string; membershipRole: string; organizationId: string; projectId: string; signal: AbortSignal;
}) {
  const projects = useProjectsQuery(organizationId, signal);
  const items = projects.data?.pages.flatMap((page) => page.items) ?? [];
  const project = items.find((item) => item.id === projectId);
  const searching = project === undefined && projects.hasNextPage && !projects.isFetchNextPageError;
  useEffect(() => {
    if (searching && !projects.isFetchingNextPage) void projects.fetchNextPage();
  }, [searching, projects.isFetchingNextPage]);
  useEffect(() => {
    if (project !== undefined) writeLastProject(window.localStorage, organizationId, project.id);
  }, [project?.id, organizationId]);

  if (projects.isPending || searching) return <ProjectsLoading />;
  if (projects.isError && projects.data === undefined) return (
    <section aria-label="项目工作区" className="projects-page">
      <div className="project-state project-state-error">
        <p role="alert">{errorMessage(projects.error, "项目暂时无法加载，请重试")}</p>
        <button type="button" onClick={() => void projects.refetch()}>重新加载项目</button>
      </div>
    </section>
  );
  if (project === undefined) {
    const first = items[0];
    return (
      <section aria-label="项目工作区" className="projects-page">
        <div className="project-state project-state-error">
          <p role="alert">{projects.isFetchNextPageError
            ? errorMessage(projects.error, "更多项目暂时无法加载，请重试")
            : "项目不存在或你没有访问权限。"}</p>
          {projects.isFetchNextPageError
            ? <button type="button" onClick={() => void projects.fetchNextPage()}>重新加载更多项目</button>
            : first !== undefined ? <Link to={projectPath(first.id, "tasks")}>回到我的第一个项目</Link> : null}
        </div>
      </section>
    );
  }
  return (
    <section aria-label="项目工作区" className="projects-page">
      {projects.isRefetchError && !projects.isFetchNextPageError ? (
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
      ) : null}
      <TaskWorkspace
        csrfToken={csrfToken}
        key={project.id}
        membershipRole={membershipRole}
        organizationId={organizationId}
        project={project}
        signal={signal}
        workspaceId={taskWorkspaceId(project.id)}
      />
    </section>
  );
}

function TaskWorkspace({
  csrfToken,
  membershipRole,
  organizationId,
  project,
  signal,
  workspaceId,
}: {
  csrfToken: string;
  membershipRole: string;
  organizationId: string;
  project: Project;
  signal: AbortSignal;
  workspaceId: string;
}) {
  const scopeSignal = signal;
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [creating, setCreating] = useState(false);
  const [taskView, setTaskView] = useState<"list" | "graph">("list");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const taskDetailsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selectedTaskId === null) return;
    taskDetailsRef.current?.scrollIntoView?.({block:"start"});
    taskDetailsRef.current?.focus({preventScroll:true});
  }, [selectedTaskId]);
  const [editorBusy, setEditorBusy] = useState(false);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [structureBusy, setStructureBusy] = useState(false);
  const [createRecovery, setCreateRecovery] = useState<"conflict" | "refresh_failed" | null>(null);
  const [createRereading, setCreateRereading] = useState(false);
  const [createGeneration, setCreateGeneration] = useState(0);
  const [createRecoveryError, setCreateRecoveryError] = useState("");
  const mounted = useRef(true);
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  const current = () => mounted.current && !scopeSignal.aborted;
  const createBlocked = createRecovery !== null || createRereading;
  const stages = useStagesQuery(organizationId, project.id, scopeSignal);
  const milestones = useMilestonesQuery(organizationId, project.id, scopeSignal);
  const tasks = useProjectTasksQuery(organizationId, project.id, scopeSignal);
  const transition = useTaskTransition({
    organizationId,
    csrfToken,
    sessionSignal: scopeSignal,
  });
  const canTransition =
    membershipRole === "owner" ||
    membershipRole === "admin" ||
    membershipRole === "member";
  const taskItems = tasks.data?.pages.flatMap((page) => page.items) ?? [];
  const hasTaskRefetchError =
    tasks.isRefetchError && !tasks.isFetchNextPageError;
  const transitionRefreshFailed =
    transition.recovery?.kind === "refresh_failed";
  const statusBlocked =
    transition.isPending ||
    transition.rereading ||
    transition.recovery !== null;
  const replacesDraft = selectedTaskId !== null || creating;
  const recoveryLabel = replacesDraft
    ? "重新读取最新版本（替换草稿）"
    : "重新读取最新任务";

  async function refreshCreateData() {
    await Promise.all([
      refreshProjectStructure(queryClient, organizationId, project.id),
      queryClient.refetchQueries({queryKey: taskKeys.list(organizationId, project.id), exact: true}, {throwOnError: true}),
    ]);
  }

  async function reloadCreate() {
    if (!current() || createRereading || createRecovery !== "conflict") return;
    setCreateRereading(true);
    setCreateRecoveryError("");
    try {
      await refreshCreateData();
      if (!current()) return;
      setCreateRecovery(null);
      setCreateGeneration(value => value + 1);
    } catch (error) {
      if (current()) setCreateRecoveryError(errorMessage(error, "最新项目数据读取失败，请重试"));
    } finally {
      if (current()) setCreateRereading(false);
    }
  }

  return (
    <section
      aria-labelledby={`${workspaceId}-heading`}
      className="task-workspace"
      id={workspaceId}
    >
      <header className="task-workspace-heading">
        <div>
          <TrailBreadcrumb items={[{ label: project.name, to: projectPath(project.id, "tasks") }, { label: "任务" }]} />
          <h1 id={`${workspaceId}-heading`}>{project.name}</h1>
          <p>{project.description ?? "暂无项目说明"}</p>
        </div>
        <div className="task-workspace-tools">
          {tasks.data && <ProgressCairn tasks={taskItems} hasMore={Boolean(tasks.hasNextPage)} />}
          {canTransition && (
            <button
              className="btn-primary"
              type="button"
              disabled={scheduleBusy || editorBusy || structureBusy || statusBlocked || createBlocked}
              onClick={() => {
                setSelectedTaskId(null);
                setCreating((value) => !value);
              }}
            >
              {creating ? "取消创建" : "创建任务"}
            </button>
          )}
        </div>
      </header>

      {creating && (
        <TaskEditor
          key={`${transition.rereadVersion}:${createGeneration}`}
          disabled={scheduleBusy || statusBlocked || structureBusy || createRereading}
          organizationId={organizationId}
          projectId={project.id}
          csrfToken={csrfToken}
          signal={scopeSignal}
          onBusy={setEditorBusy}
          rereading={createRereading}
          onConflict={(conflict) => {if (current()) setCreateRecovery(conflict ? "conflict" : null);}}
          onReload={() => void reloadCreate()}
          onSaved={async () => {
            if (!current()) return false;
            try {
              await refreshCreateData();
              if (!current()) return false;
              setCreating(false);
              setCreateRecovery(null);
              setCreateRecoveryError("");
              return true;
            } catch {
              if (current()) setCreateRecovery("refresh_failed");
              return false;
            }
          }}
        />
      )}
      {createRecoveryError && <p role="alert">{createRecoveryError}</p>}
      {selectedTaskId && (
        <div ref={taskDetailsRef} tabIndex={-1} className="task-detail-anchor">
        <TaskDetails
          key={selectedTaskId}
          taskId={selectedTaskId}
          projectId={project.id}
          organizationId={organizationId}
          csrfToken={csrfToken}
          signal={scopeSignal}
          canWrite={canTransition}
          statusBaseRevision={transition.variables?.expectedRevision}
          externalBlocked={scheduleBusy || statusBlocked || structureBusy || createBlocked}
          externalRereadVersion={transition.rereadVersion}
          statusRevision={
            transition.isSuccess &&
            transition.variables?.taskId === selectedTaskId &&
            transition.recovery === null
              ? transition.data?.revision
              : undefined
          }
          onBusy={setEditorBusy}
          onClose={() => setSelectedTaskId(null)}
        />
        </div>
      )}
      <div className="task-view-switch" role="group" aria-label="任务显示方式">
        <button type="button" aria-pressed={taskView === "list"} disabled={scheduleBusy || editorBusy || statusBlocked} onClick={()=>setTaskView("list")}><ListChecks size={16} aria-hidden="true" />任务列表</button>
        <button type="button" aria-pressed={taskView === "graph"} disabled={scheduleBusy || editorBusy || statusBlocked} onClick={()=>setTaskView("graph")}><Waypoints size={16} aria-hidden="true" />节点图</button>
        {tasks.data && tasks.hasNextPage ? <span className="task-loaded-count">已加载 {taskItems.length} 项任务</span> : null}
      </div>
      {taskView === "graph" ? <ProjectTaskGraph organizationId={organizationId} projectId={project.id} signal={scopeSignal} selectedTaskId={selectedTaskId} disabled={scheduleBusy || editorBusy || structureBusy || statusBlocked || createBlocked || creating} onOpenTask={setSelectedTaskId}/>
      : <>
      {tasks.isPending ? (
        <div className="task-loading" aria-busy="true">
          <CairnLoader label="正在加载任务" />
        </div>
      ) : null}

      {tasks.isError && tasks.data === undefined ? (
        <div className="project-state project-state-error task-state">
          <p role="alert">
            {errorMessage(tasks.error, "任务暂时无法加载，请重试")}
          </p>
          <button type="button" onClick={() => void tasks.refetch()}>
            重新加载任务
          </button>
        </div>
      ) : null}

      {hasTaskRefetchError ? (
        <RefreshError
          className="task-state"
          context={
            transitionRefreshFailed
              ? "任务更新已提交，但列表刷新失败，当前数据可能不是最新。"
              : "任务列表可能不是最新。"
          }
          error={tasks.error}
          errorFallback="任务列表刷新失败，请重试"
          idleLabel={
            transition.recovery && replacesDraft
              ? recoveryLabel
              : "重试刷新任务"
          }
          loadingLabel="正在刷新任务"
          pending={tasks.isRefetching || transition.rereading}
          onRetry={() =>
            void (transition.recovery ? transition.reread() : tasks.refetch())
          }
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

      {transition.recovery && !hasTaskRefetchError && (
        <div className="project-state project-state-error task-state">
          <p role="alert">
            {transitionRefreshFailed
              ? "任务更新已提交，但刷新失败，当前数据可能不是最新。"
              : transition.recovery.message}{" "}
            {transitionRefreshFailed && transition.recovery.message}
          </p>
          <button
            type="button"
            disabled={transition.rereading || editorBusy}
            onClick={() => void transition.reread()}
          >
            {transition.rereading ? "正在重新读取" : recoveryLabel}
          </button>
        </div>
      )}
      {transition.recovery && replacesDraft && <p>重新读取会替换当前草稿。</p>}
      {transition.isError && !transition.recovery ? (
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
              stageName={task.stageId ? stages.data?.pages.flatMap(page=>page.items).find(row=>row.id===task.stageId)?.name ?? "阶段尚未加载" : "未设置"}
              milestoneName={task.milestoneId ? milestones.data?.pages.flatMap(page=>page.items).find(row=>row.id===task.milestoneId)?.name ?? "里程碑尚未加载" : "未设置"}
              canTransition={canTransition}
              actionsDisabled={
                scheduleBusy || statusBlocked || hasTaskRefetchError || editorBusy || structureBusy || createBlocked
              }
              pending={transition.isPending}
              pendingTaskId={transition.variables?.taskId ?? null}
              pendingStatus={transition.variables?.status ?? null}
              onTransition={(status) =>
                transition.mutate(
                  {
                    projectId: project.id,
                    taskId: task.id,
                    status,
                    expectedRevision: task.revision,
                  },
                  {
                    onSuccess: () => notify(status === "done"
                      ? { title: "路标已放下", detail: `「${task.title}」已完成` }
                      : { title: "任务已更新", detail: `「${task.title}」${TASK_STATUS_LABELS[status]}` }),
                  },
                )
              }
              onOpen={() => {
                setCreating(false);
                setSelectedTaskId(task.id);
              }}
            />
          ))}
          {tasks.hasNextPage ? (
            <PaginationAction
              className="task-pagination"
              error={tasks.isFetchNextPageError ? tasks.error : null}
              errorFallback="更多任务暂时无法加载，请重试"
              idleLabel={
                tasks.isFetchNextPageError ? "重新加载更多任务" : "加载更多任务"
              }
              loadingLabel="正在加载更多任务"
              pending={tasks.isFetchingNextPage}
              onLoadMore={() => void tasks.fetchNextPage()}
            />
          ) : null}
        </div>
      ) : null}
      </>}
      <details className="project-tools-disclosure">
        <summary><Waypoints size={19} aria-hidden="true" /><strong>规划与项目工具</strong><span>项目分析、排期与里程碑</span><ChevronDown size={17} aria-hidden="true" /></summary>
        <div className="project-tools-content">
          <ProjectAnalysis projectId={project.id} csrfToken={csrfToken} signal={scopeSignal} />
          <ProjectSchedule organizationId={organizationId} projectId={project.id} csrfToken={csrfToken} signal={scopeSignal} disabled={editorBusy || structureBusy || statusBlocked || createBlocked || creating} onBusy={setScheduleBusy} onOpenTask={id=>{if(!editorBusy && !creating)setSelectedTaskId(id);}} />
          <ProjectStructure organizationId={organizationId} projectId={project.id} csrfToken={csrfToken} signal={scopeSignal} canWrite={canTransition} lifecycleDisabled={creating || selectedTaskId !== null} disabled={scheduleBusy || editorBusy || statusBlocked || createBlocked} onBusy={setStructureBusy}/>
        </div>
      </details>
    </section>
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
      {error !== null ? (
        <p role="alert">{errorMessage(error, errorFallback)}</p>
      ) : null}
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
        <strong>{context}</strong> {errorMessage(error, errorFallback)}
      </p>
      <button type="button" disabled={pending} onClick={onRetry}>
        {pending ? loadingLabel : idleLabel}
      </button>
    </div>
  );
}

function TaskRow({
  task,
  stageName,
  milestoneName,
  canTransition,
  actionsDisabled,
  pending,
  pendingTaskId,
  pendingStatus,
  onTransition,
  onOpen,
}: {
  task: Task;
  stageName: string;
  milestoneName: string;
  canTransition: boolean;
  actionsDisabled: boolean;
  pending: boolean;
  pendingTaskId: string | null;
  pendingStatus: TaskStatus | null;
  onTransition(status: TaskStatus): void;
  onOpen(): void;
}) {
  return (
    <article
      className="task-row"
      aria-label={task.title}
      data-status={task.status}
    >
      <div className="task-row-main">
        <div className="task-title-line">
          <h3><button
            type="button"
            disabled={actionsDisabled}
            aria-label={`查看任务：${task.title}`}
            onClick={onOpen}
          >
            {task.title}
          </button></h3>
          <span className="task-status" data-status={task.status}>
            <StatusStone label={TASK_STATUS_LABELS[task.status]} status={task.status} />
            <span aria-hidden="true">{TASK_STATUS_LABELS[task.status]}</span>
          </span>
        </div>
        <dl className="task-metadata">
          {task.stageId && <div><dt>阶段</dt><dd>{stageName}</dd></div>}
          {task.milestoneId && <div><dt>里程碑</dt><dd>{milestoneName}</dd></div>}
          <div data-priority={task.priority} title={PRIORITY_LABELS[task.priority]}>
            <dt>
              <Flag aria-hidden="true" size={15} strokeWidth={1.8} />
              优先级
            </dt>
            <dd>
              <span aria-hidden="true" className="mono priority-code">{PRIORITY_CODES[task.priority]}</span>
              <span className="visually-hidden">{PRIORITY_LABELS[task.priority]}</span>
            </dd>
          </div>
          {task.dueAt !== null && <div>
            <dt>
              <CalendarDays aria-hidden="true" size={15} strokeWidth={1.8} />
              到期日
            </dt>
            <dd>
              {formatCalendarDate(task.dueAt, DUE_DATE_FORMAT)}
            </dd>
          </div>}
        </dl>
        {task.acceptanceCriteria && <div className="task-acceptance">
          <h4>验收标准</h4>
          <p>{task.acceptanceCriteria}</p>
        </div>}
      </div>
      {!canTransition ? (
        <p className="task-terminal-state">只读权限</p>
      ) : TASK_TRANSITIONS[task.status].length > 0 ? (
        <div className="task-actions" aria-label="状态操作">
          {TASK_TRANSITIONS[task.status].map((action) => {
            const busy = pending && pendingTaskId === task.id && pendingStatus === action.status;
            return (
              <button
                aria-busy={busy ? "true" : undefined}
                className={ACTION_CLASS[action.status] ?? "btn-secondary"}
                disabled={actionsDisabled}
                key={action.status}
                onClick={() => onTransition(action.status)}
                type="button"
              >
                {busy ? <CairnStack size="sm" /> : null}
                {action.label}
              </button>
            );
          })}
        </div>
      ) : (
        <p className="task-terminal-state">当前状态无需操作</p>
      )}
    </article>
  );
}
