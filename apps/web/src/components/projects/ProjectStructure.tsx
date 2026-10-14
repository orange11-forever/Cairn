import { useEffect, useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { matchesComponentSchema } from "@cairn/sdk";
import { createStage, updateStage, createMilestone, updateMilestone, type Stage, type Milestone } from "../../api/projects.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";
import { refreshProjectStructure, taskKeys, useProjectQuery, useStagesQuery, useMilestonesQuery } from "../../queries/projects.ts";
function localDate(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
type Draft = {
  kind: "stage" | "milestone";
  row?: Stage | Milestone;
  name: string;
  position: string;
  description: string;
  acceptance: string;
  due: string;
  stageId: string;
};
export function ProjectStructure({
  organizationId,
  projectId,
  csrfToken,
  signal,
  canWrite,
  disabled,
  lifecycleDisabled = false,
  onBusy
}: {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  signal: AbortSignal;
  canWrite: boolean;
  disabled: boolean;
  lifecycleDisabled?: boolean;
  onBusy(busy: boolean): void;
}) {
  const id = useId();
  const client = useQueryClient();
  const project = useProjectQuery(organizationId, projectId, signal);
  const stages = useStagesQuery(organizationId, projectId, signal);
  const milestones = useMilestonesQuery(organizationId, projectId, signal);
  const [showArchived, setShowArchived] = useState(false);
  type Lifecycle = { kind: "stage" | "milestone"; row: Stage | Milestone; archived: boolean };
  const [lifecycle, setLifecycle] = useState<Lifecycle | null>(null);
  const [lifecycleMode, setLifecycleMode] = useState(false);
  const [lifecycleConflict, setLifecycleConflict] = useState(false);
  const lifecycleAction = useAbortableAction(async (target: Lifecycle, actionSignal: AbortSignal) => {
    const expectedProjectRevision = project.data?.revision;
    if (!expectedProjectRevision) throw new Error("请重新读取项目版本后再保存。");
    const options = {projectId, objectId: target.row.id, csrfToken, signal: actionSignal,
      body: {archived: target.archived, expectedRevision: target.row.revision, expectedProjectRevision}};
    return target.kind === "stage" ? updateStage(options) : updateMilestone(options);
  }, signal);
  const lifecycle409 = lifecycleAction.state.phase === "error" && lifecycleAction.state.error.status === 409;
  useEffect(() => { if (lifecycleAction.state.phase === "error" && lifecycleAction.state.error.code === "revision_conflict") setLifecycleConflict(true); }, [lifecycleAction.state]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState("");
  const [stale, setStale] = useState(false);
  const [revisionConflict, setRevisionConflict] = useState(false);
  const [reading, setReading] = useState(false);
  const action = useAbortableAction(async (current: Draft, actionSignal: AbortSignal) => {
    const expectedProjectRevision = project.data?.revision;
    if (!expectedProjectRevision) throw new Error("请重新读取项目版本后再保存。");
    const options = {
      projectId,
      csrfToken,
      signal: actionSignal
    };
    if (current.kind === "stage") {
      const fields = {
        name: current.name.trim(),
        position: Number(current.position)
      };
      if (current.row) {
        const row = current.row as Stage;
        const body = {
          expectedProjectRevision,
          expectedRevision: row.revision,
          ...(fields.name === row.name ? {} : {
            name: fields.name
          }),
          ...(fields.position === row.position ? {} : {
            position: fields.position
          })
        };
        if (!matchesComponentSchema("StageUpdateRequest", body)) throw new Error("请检查阶段字段。");
        return updateStage({
          ...options,
          objectId: current.row.id,
          body
        });
      }
      const body = {
        expectedProjectRevision,
        ...fields
      };
      if (!matchesComponentSchema("StageCreateRequest", body)) throw new Error("请检查阶段字段。");
      return createStage({
        ...options,
        body
      });
    }
    const fields = {
      name: current.name.trim(),
      description: current.description || null,
      acceptanceCriteria: current.acceptance || null,
      stageId: current.stageId || null
    };
    if (current.row) {
      const row = current.row as Milestone;
      // Preserve the server's seconds, subsecond precision and timezone when untouched.
      const body = {
        expectedProjectRevision,
        expectedRevision: row.revision,
        ...(fields.name === row.name ? {} : {
          name: fields.name
        }),
        ...(current.description === (row.description ?? "") ? {} : {
          description: fields.description
        }),
        ...(current.acceptance === (row.acceptanceCriteria ?? "") ? {} : {
          acceptanceCriteria: fields.acceptanceCriteria
        }),
        ...(current.stageId === (row.stageId ?? "") ? {} : {
          stageId: fields.stageId
        }),
        ...(current.due === localDate(row.dueAt) ? {} : {
          dueAt: current.due ? new Date(current.due).toISOString() : null
        })
      };
      if (!matchesComponentSchema("MilestoneUpdateRequest", body)) throw new Error("请检查里程碑字段。");
      return updateMilestone({
        ...options,
        objectId: row.id,
        body
      });
    }
    const body = {
      expectedProjectRevision,
      ...fields,
      dueAt: current.due ? new Date(current.due).toISOString() : null
    };
    if (!matchesComponentSchema("MilestoneCreateRequest", body)) throw new Error("请检查里程碑字段。");
    return createMilestone({
      ...options,
      body
    });
  }, signal);
  const actionConflict = action.state.phase === "error" && action.state.error.code === "revision_conflict";
  const conflict = revisionConflict || actionConflict || lifecycleConflict || lifecycle409;
  useEffect(() => {
    if (actionConflict) setRevisionConflict(true);
  }, [actionConflict]);
  useEffect(() => {
    onBusy(action.pending || lifecycleAction.pending || Boolean(lifecycle) || stale || conflict || reading);
  }, [action.pending, lifecycleAction.pending, lifecycle, stale, conflict, reading, onBusy]);
  useEffect(() => () => onBusy(false), [onBusy]);
  const blocked = disabled || action.pending || lifecycleAction.pending || stale || conflict || reading || project.isError || !project.data?.revision;
  const stageItems = stages.data?.pages.flatMap(page => page.items) ?? [];
  const milestoneItems = milestones.data?.pages.flatMap(page => page.items) ?? [];
  const archivedDraftStage = draft?.kind === "milestone" && stageItems.some(row => row.id === draft.stageId && row.archived);
  const visibleStages = stageItems.filter(row => showArchived || !row.archived);
  const visibleMilestones = milestoneItems.filter(row => showArchived || !row.archived);
  function open(kind: Draft["kind"], row?: Stage | Milestone) {
    const milestone = kind === "milestone" ? row as Milestone | undefined : undefined;
    action.reset();
    setLifecycle(null);
    setLifecycleMode(false);
    lifecycleAction.reset();
    setNotice("");
    setDraft({
      kind,
      row,
      name: row?.name ?? "",
      position: String(kind === "stage" && row ? (row as Stage).position : stageItems.length),
      description: milestone?.description ?? "",
      acceptance: milestone?.acceptanceCriteria ?? "",
      due: localDate(milestone?.dueAt ?? null),
      stageId: milestone?.stageId ?? ""
    });
  }
  async function refresh() {
    await Promise.all([refreshProjectStructure(client, organizationId, projectId), client.invalidateQueries({
      queryKey: taskKeys.list(organizationId, projectId),
      exact: true,
      refetchType: "active"
    }, {
      throwOnError: true
    }), client.invalidateQueries({
      queryKey: taskKeys.detailScope(organizationId, projectId),
      refetchType: "active"
    }, {
      throwOnError: true
    })]);
    const latest = client.getQueryData<import("../../api/projects.ts").Project>(["projects", organizationId, "detail", projectId]);
    if (!latest?.revision) throw new Error("项目版本缺失，请重新读取。");
  }
  async function submitLifecycle(target: Lifecycle) {
    if (blocked || draft || lifecycleDisabled) return;
    setNotice("");
    const result = await lifecycleAction.run(target);
    if (!result || signal.aborted) return;
    setStale(true);
    setLifecycle(null);
    const label = target.kind === "stage" ? "阶段" : "里程碑";
    try {
      await refresh();
      if (signal.aborted) return;
      setStale(false);
      setNotice(`${label}已${target.archived ? "归档" : "恢复"}。`);
    } catch {
      if (!signal.aborted) setNotice(`${label}已${target.archived ? "归档" : "恢复"}，但刷新失败。请重新读取后再操作。`);
    }
  }
  function lifecycleButton(kind: Lifecycle["kind"], row: Stage | Milestone) {
    const label = kind === "stage" ? "阶段" : "里程碑";
    return <button type="button" disabled={blocked || Boolean(draft) || lifecycleDisabled || Boolean(lifecycle)}
      aria-label={`${row.archived ? "恢复" : "归档"}${label}：${row.name}`}
      onClick={() => {
        const target = {kind, row, archived: !row.archived};
        lifecycleAction.reset();
        setNotice("");
        setLifecycleMode(true);
        setLifecycle(target);
        if (!target.archived) void submitLifecycle(target);
      }}>{row.archived ? "恢复" : "归档"}</button>;
  }
  return <section className="project-structure" aria-label="项目结构">
    <header><div><h3>阶段与里程碑</h3><p>项目说明 / 目标：{project.data?.description ?? "暂无项目说明"}</p></div>
      {canWrite && <div className="project-structure-actions"><button type="button" disabled={blocked || Boolean(lifecycle)} onClick={() => open("stage")}>创建阶段</button><button type="button" disabled={blocked || Boolean(lifecycle)} onClick={() => open("milestone")}>创建里程碑</button></div>}
    </header>
    <label className="project-structure-filter"><input type="checkbox" checked={showArchived} onChange={event => setShowArchived(event.target.checked)} />显示归档项</label>
    {project.isPending && <p aria-busy="true">正在读取项目版本</p>}
    {(project.isError || project.data && !project.data.revision) && <p role="alert">项目版本不可用，重新读取后才能保存。</p>}
    <div className="project-structure-lists">
      <div><h4>阶段</h4>{stages.isPending && <p aria-busy="true">正在加载阶段</p>}
        {stages.isError && <p role="alert">阶段加载失败。<button type="button" onClick={() => void stages.refetch()}>重试加载阶段</button></p>}
        {stages.data && !visibleStages.length && <p>{!showArchived && stageItems.some(row => row.archived) ? "暂无活动阶段，可勾选显示归档项查看历史阶段。" : "还没有阶段，可以创建第一个阶段。"}</p>}
        <ul>{visibleStages.map(row => <li key={row.id}><span>{row.name} · 顺序 {row.position}{row.archived && " · 已归档"}</span>{canWrite && <div className="project-structure-actions">{!row.archived && <button type="button" disabled={blocked || Boolean(lifecycle)} onClick={() => open("stage", row)} aria-label={`编辑阶段：${row.name}`}>编辑</button>}{lifecycleButton("stage", row)}</div>}</li>)}</ul>
        {stages.hasNextPage && <button type="button" disabled={stages.isFetchingNextPage} onClick={() => void stages.fetchNextPage()}>加载更多阶段</button>}
      </div>
      <div><h4>里程碑</h4>{milestones.isPending && <p aria-busy="true">正在加载里程碑</p>}
        {milestones.isError && <p role="alert">里程碑加载失败。<button type="button" onClick={() => void milestones.refetch()}>重试加载里程碑</button></p>}
        {milestones.data && !visibleMilestones.length && <p>{!showArchived && milestoneItems.some(row => row.archived) ? "暂无活动里程碑，可勾选显示归档项查看历史节点。" : "还没有里程碑，可以创建验收节点。"}</p>}
        <ul>{visibleMilestones.map(row => <li key={row.id}><div><strong>{row.name}{row.archived && " · 已归档"}</strong><p>阶段：{row.stageId ? stageItems.find(stage => stage.id === row.stageId)?.name ?? "阶段尚未加载" : "未设置"}</p>{row.description && <p>{row.description}</p>}{row.acceptanceCriteria && <p>验收：{row.acceptanceCriteria}</p>}{row.dueAt && <p>截止：{new Date(row.dueAt).toLocaleString()}</p>}</div>{canWrite && <div className="project-structure-actions">{!row.archived && <button type="button" disabled={blocked || Boolean(lifecycle)} onClick={() => open("milestone", row)} aria-label={`编辑里程碑：${row.name}`}>编辑</button>}{lifecycleButton("milestone", row)}</div>}</li>)}</ul>
        {milestones.hasNextPage && <button type="button" disabled={milestones.isFetchingNextPage} onClick={() => void milestones.fetchNextPage()}>加载更多里程碑</button>}
      </div>
    </div>
    {lifecycle && <div className="task-editor" role="group" aria-label={lifecycle.archived ? "归档确认" : "恢复目标"}>
      <p>{lifecycle.archived ? "确认归档" : "恢复"}{lifecycle.kind === "stage" ? "阶段" : "里程碑"}：{lifecycle.row.name}？</p>
      {lifecycle.archived && <p>{lifecycle.kind === "stage" ? "请先解除所有任务关联，并归档活动里程碑。" : "请先解除所有任务关联。"}归档后可恢复。</p>}
      <button type="button" disabled={blocked} onClick={() => void submitLifecycle(lifecycle)}>{lifecycleAction.pending ? (lifecycle.archived ? "正在归档" : "正在恢复") : (lifecycle.archived ? "确认归档" : "恢复此项")}</button>
      <button type="button" disabled={lifecycleAction.pending || reading} onClick={() => {setLifecycle(null); lifecycleAction.reset();}}>{lifecycle.archived ? "取消归档" : "取消恢复"}</button>
    </div>}
    {draft && <form className="task-editor" aria-label={draft.kind === "stage" ? "阶段表单" : "里程碑表单"} onSubmit={async event => {
      event.preventDefault();
      if (blocked || archivedDraftStage) return;
      setNotice("");
      if (draft.row && draft.name.trim() === draft.row.name && (draft.kind === "stage" ? Number(draft.position) === (draft.row as Stage).position : draft.description === ((draft.row as Milestone).description ?? "") && draft.acceptance === ((draft.row as Milestone).acceptanceCriteria ?? "") && draft.stageId === ((draft.row as Milestone).stageId ?? "") && draft.due === localDate((draft.row as Milestone).dueAt))) {
        setNotice("没有需要保存的更改。");
        return;
      }
      const row = await action.run(draft);
      if (!row || signal.aborted) return;
      setStale(true);
      try {
        await refresh();
        if (signal.aborted) return;
        setStale(false);
        setDraft(null);
        setNotice("项目结构已保存。");
      } catch {
        if (!signal.aborted) setNotice("项目结构已保存，但刷新失败。请重新读取后再操作。");
      }
    }}>
      <fieldset disabled={blocked}>
        <label htmlFor={`${id}-name`}>{draft.kind === "stage" ? "阶段名称" : "里程碑名称"}</label><input id={`${id}-name`} autoFocus required maxLength={draft.kind === "stage" ? 120 : 160} value={draft.name} onChange={event => setDraft({
          ...draft,
          name: event.target.value
        })} />
        {draft.kind === "stage" ? <><label htmlFor={`${id}-position`}>排序位置</label><input id={`${id}-position`} required type="number" min="0" step="1" value={draft.position} onChange={event => setDraft({
            ...draft,
            position: event.target.value
          })} /></> : <>
          <label htmlFor={`${id}-stage`}>里程碑所属阶段</label><select id={`${id}-stage`} value={archivedDraftStage ? "" : draft.stageId} aria-invalid={archivedDraftStage || undefined} aria-describedby={archivedDraftStage ? `${id}-archived-stage` : undefined} onChange={event => setDraft({
            ...draft,
            stageId: event.target.value
          })}><option value="">未设置</option>{draft.stageId && !stageItems.some(row => row.id === draft.stageId) && <option value={draft.stageId}>当前阶段（尚未加载）</option>}{stageItems.filter(row => !row.archived).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
          {archivedDraftStage && <div><p id={`${id}-archived-stage`} role="alert">所选阶段已归档，请清空里程碑所属阶段或选择活动阶段。其他输入已保留。</p><button type="button" onClick={() => setDraft({...draft, stageId: ""})}>清空里程碑所属阶段</button></div>}
          <label htmlFor={`${id}-description`}>里程碑说明</label><textarea id={`${id}-description`} maxLength={4000} value={draft.description} onChange={event => setDraft({
            ...draft,
            description: event.target.value
          })} />
          <label htmlFor={`${id}-acceptance`}>里程碑验收标准</label><textarea id={`${id}-acceptance`} maxLength={10000} value={draft.acceptance} onChange={event => setDraft({
            ...draft,
            acceptance: event.target.value
          })} />
          <label htmlFor={`${id}-due`}>里程碑截止时间（本地时区）</label><input id={`${id}-due`} type="datetime-local" value={draft.due} onChange={event => setDraft({
            ...draft,
            due: event.target.value
          })} /><button type="button" onClick={() => setDraft({
            ...draft,
            due: ""
          })}>清空里程碑截止时间</button>
        </>}
      </fieldset>
      <button type="submit" disabled={blocked || archivedDraftStage}>{action.pending ? "正在保存" : draft.kind === "stage" ? "保存阶段" : "保存里程碑"}</button><button type="button" disabled={action.pending || reading} onClick={() => {
        setDraft(null);
        action.reset();
      }}>取消编辑</button>
    </form>}
    {lifecycleAction.state.phase === "error" && <p role="alert">{lifecycleAction.state.error.message}</p>}
    {action.state.phase === "error" && <p role="alert">{action.state.error.message}</p>}
    {conflict && <p>{draft ? "本地输入已保留；重新读取项目结构会替换草稿。" : lifecycleMode ? "目标已保留；请重新读取项目结构后再操作。" : "项目版本已变更，请重新读取后再操作。"}</p>}
    {notice && <p role="status">{notice}</p>}
    {(conflict || stale || project.isError || project.data && !project.data.revision) && <button type="button" disabled={reading || disabled} onClick={async () => {
      setReading(true);
      try {
        await refresh();
        if (signal.aborted) return;
        if (lifecycle) {
          const pages = client.getQueryData<{pages: {items: (Stage | Milestone)[]}[]}>(["project-structure", organizationId, projectId, lifecycle.kind === "stage" ? "stages" : "milestones"]);
          const fresh = pages?.pages.flatMap(page => page.items).find(row => row.id === lifecycle.row.id);
          if (!fresh) throw new Error("归档目标尚未读取，请继续加载结构后重试。");
          setLifecycle({...lifecycle, row: fresh});
        }
        setDraft(null);
        action.reset();
        lifecycleAction.reset();
        setLifecycleConflict(false);
        setStale(false);
        setRevisionConflict(false);
        setNotice("已重新读取项目结构。");
      } catch {
        if (!signal.aborted) setNotice("重新读取失败，请重试。");
      } finally {
        if (!signal.aborted) setReading(false);
      }
    }}>{reading ? "正在重新读取项目结构" : (lifecycleMode ? "重新读取项目结构" : "重新读取项目结构（替换草稿）")}</button>}
  </section>;
}
