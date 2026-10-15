import { useId, useState } from "react";
import {
  addTaskDependency,
  deleteTaskDependency,
  type Task,
} from "../../api/projects.ts";
import { ApiError } from "../../api/errors.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";
import {
  useDependenciesQuery,
  useProjectTasksQuery,
} from "../../queries/projects.ts";

export function TaskDependencies({
  task,
  organizationId,
  csrfToken,
  signal,
  canWrite,
  disabled,
  onBusy,
  onChanged,
  onReload,
  onConflict,
}: {
  task: Task;
  organizationId: string;
  csrfToken: string;
  signal: AbortSignal;
  canWrite: boolean;
  disabled: boolean;
  onBusy(busy: boolean): void;
  onChanged(revision: number): Promise<boolean>;
  onReload(): void;
  onConflict?(conflict: boolean): void;
}) {
  const id = useId();
  const dependencies = useDependenciesQuery(
    organizationId,
    task.projectId,
    task.id,
    signal,
  );
  const candidates = useProjectTasksQuery(
    organizationId,
    canWrite ? task.projectId : null,
    signal,
  );
  const [selected, setSelected] = useState("");
  const [notice, setNotice] = useState("");
  const action = useAbortableAction(
    async (
      kind: "add" | "delete",
      target: string,
      actionSignal: AbortSignal,
    ) => {
      const common = {
        taskId: task.id,
        expectedRevision: task.revision,
        csrfToken,
        signal: actionSignal,
      };
      try {
        if (kind === "add")
          await addTaskDependency({ ...common, predecessorTaskId: target });
        else await deleteTaskDependency({ ...common, dependencyId: target });
        return true;
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
  const edges = dependencies.data?.pages.flatMap((page) => page.items) ?? [];
  const tasks = candidates.data?.pages.flatMap((page) => page.items) ?? [];
  const available = tasks.filter(
    (candidate) =>
      candidate.id !== task.id &&
      !edges.some((edge) => edge.predecessorTaskId === candidate.id),
  );
  const conflict =
    action.state.phase === "error" &&
    action.state.error.code === "revision_conflict";
  const blocked =
    disabled ||
    action.pending ||
    dependencies.isError ||
    dependencies.hasNextPage ||
    dependencies.isPending ||
    conflict;
  async function mutate(kind: "add" | "delete", target: string) {
    if (blocked) return;
    onBusy(true);
    setNotice("");
    try {
      if (await action.run(kind, target)) {
        setSelected("");
        const fresh = await onChanged(task.revision + 1);
        if (!signal.aborted)
          setNotice(
            fresh
              ? "依赖已更新。"
              : "依赖已更新，但刷新失败。请重新读取后再操作。",
          );
      }
    } finally {
      onBusy(false);
    }
  }
  return (
    <section className="task-dependencies" aria-label="前置依赖">
      <h3>前置依赖</h3>
      {dependencies.isPending && <p aria-busy="true">正在加载前置依赖</p>}
      {dependencies.isError && (
        <p role="alert">
          前置依赖加载失败。
          <button type="button" onClick={() => void dependencies.refetch()}>
            重试加载依赖
          </button>
        </p>
      )}
      {dependencies.data && edges.length === 0 && !dependencies.hasNextPage && (
        <p>尚无前置依赖。</p>
      )}
      <ul>
        {edges.map((edge) => (
          <li key={edge.id}>
            <span>
              {tasks.find(
                (candidate) => candidate.id === edge.predecessorTaskId,
              )?.title ?? `任务 ${edge.predecessorTaskId}`}
            </span>
            {canWrite && (
              <button
                type="button"
                disabled={blocked}
                aria-label={`删除依赖：${tasks.find((candidate) => candidate.id === edge.predecessorTaskId)?.title ?? edge.predecessorTaskId}`}
                onClick={() => void mutate("delete", edge.id)}
              >
                删除依赖
              </button>
            )}
          </li>
        ))}
      </ul>
      {dependencies.hasNextPage && (
        <button
          type="button"
          disabled={dependencies.isFetchingNextPage}
          onClick={() => void dependencies.fetchNextPage()}
        >
          加载更多依赖
        </button>
      )}
      {canWrite && (
        <div className="task-dependency-add">
          <label htmlFor={`${id}-candidate`}>添加前置任务</label>
          <select
            id={`${id}-candidate`}
            disabled={blocked}
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            <option value="">选择同项目任务</option>
            {available.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.title}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={blocked || !selected}
            onClick={() => void mutate("add", selected)}
          >
            添加依赖
          </button>
          {candidates.hasNextPage && (
            <button
              type="button"
              disabled={candidates.isFetchingNextPage}
              onClick={() => void candidates.fetchNextPage()}
            >
              加载更多候选任务
            </button>
          )}
          {candidates.isError && (
            <p role="alert">
              候选任务加载失败。
              <button type="button" onClick={() => void candidates.refetch()}>
                重试加载候选任务
              </button>
            </p>
          )}
        </div>
      )}
      {action.state.phase === "error" && (
        <p role="alert">
          {action.state.error.code === "revision_conflict"
            ? "任务已被更新，请重新读取最新版本。"
            : action.state.error.message}
        </p>
      )}
      {conflict && (
        <button type="button" onClick={onReload}>
          重新读取最新版本（替换草稿）
        </button>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
