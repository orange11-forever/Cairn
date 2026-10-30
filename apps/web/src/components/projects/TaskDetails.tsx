import { effortLabel } from "../../lib/effort.ts";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { type Task } from "../../api/projects.ts";
import { taskKeys, refreshProjectStructure, useTaskQuery, useStagesQuery, useMilestonesQuery } from "../../queries/projects.ts";
import { TaskEditor } from "./TaskEditor.tsx";
import { TaskDependencies } from "./TaskDependencies.tsx";

export function TaskDetails({
  taskId,
  projectId,
  organizationId,
  csrfToken,
  signal,
  canWrite,
  onClose,
  onBusy,
  externalBlocked = false,
  externalRereadVersion = 0,
  statusRevision,
  statusBaseRevision,
}: {
  taskId: string;
  projectId: string;
  organizationId: string;
  csrfToken: string;
  signal: AbortSignal;
  canWrite: boolean;
  onClose(): void;
  onBusy(busy: boolean): void;
  externalBlocked?: boolean;
  externalRereadVersion?: number;
  statusRevision?: number;
  statusBaseRevision?: number;
}) {
  const detail = useTaskQuery(organizationId, projectId, taskId, signal);
  const stages = useStagesQuery(organizationId, projectId, signal);
  const milestones = useMilestonesQuery(organizationId, projectId, signal);
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [ownedRevision, setOwnedRevision] = useState<
    { from: number; to: number } | undefined
  >();
  const [generation, setGeneration] = useState(0);
  const [notice, setNotice] = useState("");
  function setWriting(value: boolean) {
    setBusy(value);
    if (value) onBusy(true);
  }
  const localBlocked = busy || stale || conflict;
  useEffect(() => {
    onBusy(localBlocked);
  }, [localBlocked, onBusy]);
  useEffect(() => () => onBusy(false), [onBusy]);
  async function refresh(expectedRevision?: number) {
    const outcomes = await Promise.all(
      [
        refreshProjectStructure(queryClient, organizationId, projectId),
        detail.refetch(),
        queryClient.refetchQueries(
          {
            queryKey: taskKeys.dependencies(organizationId, projectId, taskId),
            exact: true,
          },
          { throwOnError: true },
        ),
        queryClient.refetchQueries(
          { queryKey: taskKeys.list(organizationId, projectId), exact: true },
          { throwOnError: true },
        ),
      ].map((operation) =>
        operation.then(
          (value) => !(value && "isError" in value && value.isError),
          () => false,
        ),
      ),
    );
    if (signal.aborted) return false;
    let fresh = outcomes.every(Boolean);
    const latest = queryClient.getQueryData<Task>(
      taskKeys.detail(organizationId, projectId, taskId),
    );
    if (
      fresh &&
      expectedRevision !== undefined &&
      latest?.revision !== expectedRevision
    ) {
      fresh = false;
      setConflict(true);
    }
    if (fresh && expectedRevision !== undefined)
      setOwnedRevision({ from: expectedRevision - 1, to: expectedRevision });
    setStale(!fresh);
    return fresh;
  }
  async function saved(task: Task) {
    if (signal.aborted) return false;
    queryClient.setQueryData(
      taskKeys.detail(organizationId, projectId, taskId),
      task,
    );
    return refresh(task.revision);
  }
  async function reload() {
    setWriting(true);
    try {
      if (await refresh()) {
        setConflict(false);
        setGeneration((value) => value + 1);
        setNotice("");
      } else setNotice("最新数据加载失败，请重试。");
    } finally {
      setWriting(false);
    }
  }
  return (
    <section className="task-details" aria-label="任务详情">
      <header>
        <h2>任务详情</h2>
        <button
          type="button"
          disabled={busy || externalBlocked}
          onClick={onClose}
        >
          关闭详情
        </button>
      </header>
      {detail.isPending && <p aria-busy="true">正在读取任务详情</p>}
      {detail.isError && (
        <p role="alert">
          {detail.error instanceof Error
            ? detail.error.message
            : "任务读取失败"}
          {!externalBlocked && (
            <button type="button" disabled={busy} onClick={() => void reload()}>
              {detail.data ? "重新读取最新版本（替换草稿）" : "重新读取任务"}
            </button>
          )}
        </p>
      )}
      {notice && <p role="alert">{notice}</p>}
      {detail.data && (
        <>
          <p>
            状态：
            {
              {
                backlog: "待规划",
                todo: "待处理",
                in_progress: "进行中",
                blocked: "已阻塞",
                done: "已完成",
                cancelled: "已取消",
              }[detail.data.status]
            }{" "}
            · 修订 {detail.data.revision}
          </p>
          <p>阶段：{detail.data.stageId ? stages.data?.pages.flatMap(page=>page.items).find(row=>row.id===detail.data!.stageId)?.name ?? "阶段尚未加载" : "未设置"} · 里程碑：{detail.data.milestoneId ? milestones.data?.pages.flatMap(page=>page.items).find(row=>row.id===detail.data!.milestoneId)?.name ?? "里程碑尚未加载" : "未设置"}</p>
          {canWrite ? (
            <TaskEditor
              key={`${generation}:${externalRereadVersion}`}
              task={detail.data}
              organizationId={organizationId}
              projectId={projectId}
              csrfToken={csrfToken}
              signal={signal}
              disabled={localBlocked || externalBlocked}
              onConflict={setConflict}
              revisionOverride={
                detail.data.revision === statusRevision
                  ? { from: statusBaseRevision ?? -1, to: statusRevision! }
                  : ownedRevision
              }
              onBusy={setWriting}
              onSaved={saved}
              onReload={() => void reload()}
            />
          ) : (
            <>
              <h3>{detail.data.title}</h3>
              <p>只读权限</p>
              <dl>
                <dt>任务描述</dt>
                <dd>{detail.data.description ?? "未填写"}</dd>
                <dt>负责人</dt>
                <dd>{detail.data.assigneeUserId ?? "未分配"}</dd>
                <dt>优先级</dt>
                <dd>{detail.data.priority}</dd>
                <dt>截止时间</dt>
                <dd>{detail.data.dueAt ?? "无到期时间"}</dd>
                <dt>初始估算</dt><dd>{effortLabel(detail.data.estimatedEffortMinutes)}</dd>
                <dt>剩余工作量</dt><dd>{effortLabel(detail.data.remainingEffortMinutes)}</dd>
                <dt>验收标准</dt>
                <dd>{detail.data.acceptanceCriteria ?? "未填写"}</dd>
              </dl>
            </>
          )}
          {stale && (
            <p role="alert">
              更新已提交，但刷新失败。
              <button
                type="button"
                disabled={busy || externalBlocked}
                onClick={() => void reload()}
              >
                重新读取最新版本（替换草稿）
              </button>
            </p>
          )}
          <TaskDependencies
            key={`dependencies-${generation}:${externalRereadVersion}`}
            task={detail.data}
            organizationId={organizationId}
            csrfToken={csrfToken}
            signal={signal}
            canWrite={canWrite}
            disabled={localBlocked || externalBlocked}
            onConflict={setConflict}
            onBusy={setWriting}
            onChanged={(revision) => refresh(revision)}
            onReload={() => void reload()}
          />
        </>
      )}
    </section>
  );
}
