import { useEffect, useId, useState } from "react";
import {
  createTask,
  updateTask,
  type Task,
  type TaskCreate,
  type TaskUpdate,
} from "../../api/projects.ts";
import { matchesComponentSchema } from "@cairn/sdk";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";
import { ApiError } from "../../api/errors.ts";
import { useAssigneesQuery, useProjectQuery, useStagesQuery, useMilestonesQuery } from "../../queries/projects.ts";

function localDate(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

export function TaskEditor({
  task,
  organizationId,
  projectId,
  csrfToken,
  signal,
  disabled = false,
  onSaved,
  onBusy,
  onReload,
  onConflict,
  revisionOverride,
  rereading = false,
}: {
  task?: Task;
  organizationId: string;
  projectId: string;
  csrfToken: string;
  signal: AbortSignal;
  disabled?: boolean;
  onSaved(task: Task): Promise<boolean>;
  onBusy?(busy: boolean): void;
  onReload?(): void;
  onConflict?(conflict: boolean): void;
  revisionOverride?: { from: number; to: number };
  rereading?: boolean;
}) {
  const id = useId();
  const assignees = useAssigneesQuery(organizationId, projectId, signal);
  const project = useProjectQuery(organizationId, projectId, signal);
  const stages = useStagesQuery(organizationId, projectId, signal);
  const milestones = useMilestonesQuery(organizationId, projectId, signal);
  const [stage, setStage] = useState(task?.stageId ?? "");
  const [milestone, setMilestone] = useState(task?.milestoneId ?? "");
  const allStageItems = stages.data?.pages.flatMap(page => page.items) ?? [];
  const allMilestoneItems = milestones.data?.pages.flatMap(page => page.items) ?? [];
  const stageItems = allStageItems.filter(row => !row.archived);
  const milestoneItems = allMilestoneItems.filter(row => !row.archived);
  const archivedGrouping = allStageItems.some(row => row.id === stage && row.archived) || allMilestoneItems.some(row => row.id === milestone && row.archived);
  const selectedMilestone = milestoneItems.find(row => row.id === milestone);
  const incompatible = selectedMilestone && (selectedMilestone.stageId ?? "") !== stage;
  const groupingBlocked = project.isError || !project.data?.revision || Boolean(incompatible) || archivedGrouping;
  const [title, setTitle] = useState(task?.title ?? "");
  const [description, setDescription] = useState(task?.description ?? "");
  const [acceptance, setAcceptance] = useState(task?.acceptanceCriteria ?? "");
  const [priority, setPriority] = useState<Task["priority"]>(
    task?.priority ?? "medium",
  );
  const [due, setDue] = useState(localDate(task?.dueAt ?? null));
  const [assignee, setAssignee] = useState(task?.assigneeUserId ?? "");
  const [baseline, setBaseline] = useState(task);
  const [lineageConflict, setLineageConflict] = useState(false);
  const [revision, setRevision] = useState(task?.revision ?? 1);
  const [notice, setNotice] = useState("");
  const [committed, setCommitted] = useState<Task | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const save = useAbortableAction(
    async (body: TaskCreate | TaskUpdate, actionSignal: AbortSignal) => {
      try {
        return await (!("expectedRevision" in body)
          ? createTask({ projectId, body, csrfToken, signal: actionSignal })
          : updateTask({
              taskId: task!.id,
              projectId,
              body,
              csrfToken,
              signal: actionSignal,
            }));
      } catch (error) {
        if (
          !actionSignal.aborted &&
          error instanceof ApiError &&
          error.code === "revision_conflict"
        )
          onConflict?.(true);
        throw error;
      }
    },
    signal,
  );
  const conflict =
    lineageConflict ||
    (save.state.phase === "error" &&
      save.state.error.code === "revision_conflict");
  useEffect(() => {
    // Query notifications can still carry the prior owned save's hint while
    // this editor has already confirmed a newer successful write.
    if (
      !revisionOverride ||
      task?.revision !== revisionOverride.to ||
      revision >= revisionOverride.to
    )
      return;
    if (
      revision !== revisionOverride.from ||
      revisionOverride.to !== revisionOverride.from + 1
    ) {
      setLineageConflict(true);
      onConflict?.(true);
      return;
    }
    setRevision(revisionOverride.to);
    setBaseline(
      (previous) => previous && { ...previous, revision: revisionOverride.to },
    );
  }, [
    revisionOverride?.from,
    revisionOverride?.to,
    task?.revision,
    revision,
    onConflict,
  ]);
  const candidates = assignees.data?.pages.flatMap((page) => page.items) ?? [];
  const selectedUnavailable =
    assignee !== "" &&
    !candidates.some((candidate) => candidate.userId === assignee);
  return (
    <form
      className="task-editor"
      aria-label={task ? "编辑任务" : "创建任务"}
      onSubmit={async (event) => {
        event.preventDefault();
        if (save.pending || disabled || conflict || committed || groupingBlocked) return;
        setNotice("");
        let body: TaskCreate | TaskUpdate;
        if (!baseline) {
          body = {
            title: title.trim(),
            description: description || null,
            acceptanceCriteria: acceptance || null,
            priority,
            dueAt: due ? new Date(due).toISOString() : null,
            assigneeUserId: assignee || null,
            stageId: stage || null,
            milestoneId: milestone || null,
            expectedProjectRevision: project.data!.revision!,
          };
        } else {
          const edits: Record<string, unknown> = {};
          if (title.trim() !== baseline.title) edits.title = title.trim();
          if (description !== (baseline.description ?? ""))
            edits.description = description || null;
          if (acceptance !== (baseline.acceptanceCriteria ?? ""))
            edits.acceptanceCriteria = acceptance || null;
          if (priority !== baseline.priority) edits.priority = priority;
          if (assignee !== (baseline.assigneeUserId ?? ""))
            edits.assigneeUserId = assignee || null;
          if (due !== localDate(baseline.dueAt))
            edits.dueAt = due ? new Date(due).toISOString() : null;
          if (stage !== (baseline.stageId ?? "")) edits.stageId = stage || null;
          if (milestone !== (baseline.milestoneId ?? "")) edits.milestoneId = milestone || null;
          if (!Object.keys(edits).length) {
            setNotice("没有需要保存的更改。");
            return;
          }
          const patch = { expectedRevision: revision, expectedProjectRevision: project.data!.revision!, ...edits };
          if (!matchesComponentSchema("TaskUpdateRequest", patch)) {
            setNotice("请检查任务字段后再保存。");
            return;
          }
          body = patch;
        }
        onBusy?.(true);
        try {
          const result = await save.run(body);
          if (!result || signal.aborted) return;
          setRevision(result.revision);
          setBaseline(result);
          setTitle(result.title);
          setDescription(result.description ?? "");
          setAcceptance(result.acceptanceCriteria ?? "");
          setPriority(result.priority);
          setAssignee(result.assigneeUserId ?? "");
          setDue(localDate(result.dueAt));
          setStage(result.stageId ?? "");
          setMilestone(result.milestoneId ?? "");
          const fresh = await onSaved(result);
          if (!fresh) setCommitted(result);
          if (!signal.aborted)
            setNotice(
              fresh
                ? "任务已保存。"
                : "任务已保存，但刷新失败。请重新读取后再操作。",
            );
        } finally {
          onBusy?.(false);
        }
      }}
    >
      <h3>{task ? "编辑任务" : "创建任务"}</h3>
      <fieldset
        disabled={save.pending || disabled || conflict || committed !== null}
      >
        <label htmlFor={`${id}-title`}>任务标题</label>
        <input
          id={`${id}-title`}
          required
          maxLength={240}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <label htmlFor={`${id}-description`}>任务描述</label>
        <textarea
          id={`${id}-description`}
          maxLength={10000}
          rows={4}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <div className="task-editor-fields">
          <div>
            <label htmlFor={`${id}-stage`}>所属阶段</label>
            <select id={`${id}-stage`} value={stage} onChange={event=>setStage(event.target.value)}>
              <option value="">未设置</option>
              {stage && !allStageItems.some(row=>row.id===stage) && <option value={stage}>当前阶段（尚未加载）</option>}
              {stageItems.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-milestone`}>所属里程碑</label>
            <select id={`${id}-milestone`} value={milestone} onChange={event=>setMilestone(event.target.value)}>
              <option value="">未设置</option>
              {milestone && !allMilestoneItems.some(row=>row.id===milestone) && <option value={milestone}>当前里程碑（尚未加载）</option>}
              {milestoneItems.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-assignee`}>负责人</label>
            <select
              id={`${id}-assignee`}
              value={assignee}
              onChange={(event) => setAssignee(event.target.value)}
            >
              <option value="">未分配</option>
              {selectedUnavailable && (
                <option value={assignee}>
                  当前负责人（候选尚未加载或已不可分配）
                </option>
              )}
              {candidates.map((candidate) => (
                <option key={candidate.userId} value={candidate.userId}>
                  {candidate.displayName ?? "未命名成员"}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-priority`}>优先级</label>
            <select
              id={`${id}-priority`}
              value={priority}
              onChange={(event) =>
                setPriority(event.target.value as Task["priority"])
              }
            >
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
              <option value="critical">紧急</option>
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-due`}>截止时间（本地时区）</label>
            <input
              id={`${id}-due`}
              type="datetime-local"
              value={due}
              onChange={(event) => setDue(event.target.value)}
            />
            <button type="button" onClick={() => setDue("")}>
              无到期时间
            </button>
          </div>
        </div>
        <label htmlFor={`${id}-acceptance`}>验收标准</label>
        <textarea
          id={`${id}-acceptance`}
          maxLength={10000}
          rows={3}
          value={acceptance}
          onChange={(event) => setAcceptance(event.target.value)}
        />
      </fieldset>
      {archivedGrouping && <div><p role="alert">所选结构已归档，请清空归属或选择活动阶段与里程碑。</p><button type="button" disabled={save.pending || disabled || conflict || committed !== null} onClick={() => {setStage(""); setMilestone("");}}>清空归属</button></div>}
      {incompatible && <p role="alert">任务阶段必须与里程碑所属阶段一致，请调整归属或清空里程碑。</p>}
      {(project.isError || (project.data && !project.data.revision)) && <p role="alert">项目版本不可用。<button type="button" onClick={()=>void project.refetch()}>重新读取项目版本</button></p>}
      {stages.isError && <p role="alert">阶段加载失败。<button type="button" onClick={()=>void stages.refetch()}>重试加载阶段</button></p>}
      {milestones.isError && <p role="alert">里程碑加载失败。<button type="button" onClick={()=>void milestones.refetch()}>重试加载里程碑</button></p>}
      {stages.hasNextPage && <button type="button" disabled={stages.isFetchingNextPage} onClick={()=>void stages.fetchNextPage()}>加载更多阶段选项</button>}
      {milestones.hasNextPage && <button type="button" disabled={milestones.isFetchingNextPage} onClick={()=>void milestones.fetchNextPage()}>加载更多里程碑选项</button>}
      {assignees.isError && (
        <p role="alert">
          负责人加载失败。
          <button
            type="button"
            disabled={assignees.isFetching}
            onClick={() => void assignees.refetch()}
          >
            重试加载负责人
          </button>
        </p>
      )}
      {assignees.hasNextPage && (
        <button
          type="button"
          disabled={assignees.isFetchingNextPage}
          onClick={() => void assignees.fetchNextPage()}
        >
          加载更多负责人
        </button>
      )}
      {save.state.phase === "error" && (
        <p role="alert">
          {save.state.error.status === 404
            ? "任务不存在或你已失去编辑权限。"
            : save.state.error.message}
        </p>
      )}
      {lineageConflict && (
        <p role="alert">草稿基于旧版本，请重新读取最新版本后再保存。</p>
      )}
      {conflict && (
        <>
          <p>本地草稿已保留；重新读取将替换草稿。</p>
          <button type="button" disabled={rereading} onClick={onReload}>
            {rereading ? "正在重新读取最新版本" : "重新读取最新版本（替换草稿）"}
          </button>
        </>
      )}
      {notice && <p role="status">{notice}</p>}
      {committed && (!task || !onReload) && (
        <button
          type="button"
          disabled={refreshing}
          onClick={async () => {
            setRefreshing(true);
            onBusy?.(true);
            try {
              if (await onSaved(committed)) {
                setCommitted(null);
                setNotice("任务已保存。");
              }
            } finally {
              setRefreshing(false);
              onBusy?.(false);
            }
          }}
        >
          重试刷新任务
        </button>
      )}
      <button
        className="primary-btn"
        type="submit"
        disabled={save.pending || disabled || conflict || committed !== null || groupingBlocked}
      >
        {save.pending ? "正在保存" : "保存任务"}
      </button>
    </form>
  );
}
