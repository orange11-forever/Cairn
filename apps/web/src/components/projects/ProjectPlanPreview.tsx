import { useEffect, useId, useRef, useState } from "react";
import { applyProjectPlan, fetchAppliedProjectPlan, fetchAppliedProjectPlans, previewProjectPlan, type ProjectPlanApplication, type ProjectPlanApplicationPage, type ProjectPlanApplyRequest, type ProjectPlanPreviewResponse } from "../../api/projectPlanning.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";
import { ProjectEvidence } from "./ProjectEvidence.tsx";
import { PlanDependencyGraph } from "./PlanDependencyGraph.tsx";
import { PlanDraftEditor } from "./PlanDraftEditor.tsx";
import { AppliedPlanDetails } from "./AppliedPlanDetails.tsx";
import { ApiError } from "../../api/errors.ts";

interface Props {projectId: string; csrfToken: string; signal: AbortSignal; ownerId?: string; disabled?: boolean; onApplied?: () => Promise<void>; onOpenTask?: (id: string) => void}
const PRIORITY = {low:"低",medium:"中",high:"高",critical:"紧急"};

export function ProjectPlanPreview(props: Props) {
  return <PlanningPanel key={`${props.projectId}:${props.csrfToken}:${props.ownerId}`} {...props}/>;
}

function PlanningPanel({projectId,csrfToken,signal,ownerId="session",disabled=false,onApplied,onOpenTask}:Props) {
  const headingId = useId();
  const resultRef = useRef<HTMLDivElement>(null);
  const [result,setResult] = useState<{value:ProjectPlanPreviewResponse;scope:AbortSignal}|null>(null);
  const [selectedId,setSelectedId] = useState<string|null>(null);
  const storageKey = `cairn.pending-plan:${ownerId}:${projectId}`;
  const [initialStorage] = useState(()=>{
    try {return {id:sessionStorage.getItem(storageKey),error:""};}
    catch {return {id:null,error:"会话存储不可用。仍可预览规划；请启用此页面的会话存储并刷新后再确认创建。"};}
  });
  const [storageError,setStorageError] = useState(initialStorage.error);
  const [pendingId,setPendingId] = useState<string|null>(initialStorage.id);
  const [uncertain,setUncertain] = useState(pendingId!==null);
  const [submission,setSubmission] = useState<ProjectPlanApplyRequest|null>(null);
  const [saved,setSaved] = useState<ProjectPlanApplication|null>(null);
  const [history,setHistory] = useState<ProjectPlanApplicationPage|null>(null);
  const [editing,setEditing] = useState(false);
  const [confirming,setConfirming] = useState(false);
  const [notice,setNotice] = useState(pendingId ? "上次提交结果尚未确认，请先查询已保存结果。" : "");
  const [refreshFailed,setRefreshFailed] = useState(false);
  const [refreshing,setRefreshing] = useState(false);
  const inFlight=useRef(false);
  const mounted=useRef(true);
  const confirmRef=useRef<HTMLButtonElement>(null);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;};},[]);
  useEffect(()=>{if(confirming) confirmRef.current?.focus();},[confirming]);
  function current(){return mounted.current && !signal.aborted;}
  function clearPendingStorage(){
    try {sessionStorage.removeItem(storageKey);}
    catch {setStorageError("会话存储不可用，无法清除本机提交编号。已保存的规划仍可查询；请启用存储后刷新页面。");}
  }
  const applyAction=useAbortableAction(async(payload:ProjectPlanApplyRequest,requestSignal:AbortSignal)=>{
    try {return await applyProjectPlan({projectId,csrfToken,payload,signal:requestSignal});}
    catch(error) {
      if(!requestSignal.aborted && current()) {
        const definite=error instanceof ApiError && error.kind==="http" && error.status!==null && error.status<500 && error.code!=="plan_operation_conflict";
        setConfirming(false);
        if(definite) {clearPendingStorage();setPendingId(null);setSubmission(null);setNotice("规划未应用，草稿已保留。项目或资料变化后请重新生成。");}
        else {setUncertain(true);setNotice("提交结果尚未确认。请先查询结果，避免重复创建。");}
      }
      throw error;
    }
  },signal);
  const lookup=useAbortableAction(async(id:string,requestSignal:AbortSignal)=>{
    try{return await fetchAppliedProjectPlan({projectId,operationId:id,signal:requestSignal});}
    catch(error){if(error instanceof ApiError && error.status===404 && error.code==="not_found") return null;throw error;}
  },signal);
  const historyAction=useAbortableAction((cursor:string|null,requestSignal:AbortSignal)=>fetchAppliedProjectPlans({projectId,cursor,signal:requestSignal}),signal);
  const locked=disabled || applyAction.pending || lookup.pending || refreshing || uncertain || submission!==null;
  async function refreshProject(){
    setRefreshing(true);
    try {await onApplied?.();if(current()){setRefreshFailed(false);setNotice("规划已应用，真实项目内容已更新。");}}
    catch {if(current()){setRefreshFailed(true);setNotice("规划已应用，但项目刷新失败。请重新读取项目；无需再次创建。");}}
    finally {if(current())setRefreshing(false);}
  }
  async function accept(value:ProjectPlanApplication){
    if(!current())return;
    clearPendingStorage();setPendingId(null);setSubmission(null);setUncertain(false);
    setSaved(value);setResult(null);setEditing(false);setConfirming(false);applyAction.reset();lookup.reset();
    setNotice("规划已应用，正在读取真实项目内容。");
    await refreshProject();
  }
  async function confirm(){
    if(inFlight.current || signal.aborted || disabled || storageError || (!preview && !submission))return;
    const payload=submission??{operationId:pendingId??crypto.randomUUID(),preview:structuredClone(preview!)};
    try {sessionStorage.setItem(storageKey,payload.operationId);}
    catch {setNotice("无法保存提交编号，请允许此页面使用会话存储后再确认。");return;}
    inFlight.current=true;setPendingId(payload.operationId);setSubmission(payload);setNotice("");
    try {const value=await applyAction.run(payload);if(value)await accept(value);}
    finally {inFlight.current=false;}
  }
  async function querySubmission(){
    if(!pendingId)return;
    const value=await lookup.run(pendingId);
    if(value)await accept(value);
    else if(value===null && current()) {setUncertain(false);setNotice(submission?"尚未找到已应用记录，可以重新提交同一份规划。":"尚未找到已应用记录，请重新生成规划后确认。提交编号将继续复用。");}
  }
  async function loadHistory(more=false){
    const page=await historyAction.run(more?history?.nextCursor??null:null);
    if(page && current())setHistory({items:more?[...(history?.items??[]),...page.items]:page.items,nextCursor:page.nextCursor});
  }
  const action = useAbortableAction((requestSignal:AbortSignal)=>previewProjectPlan({projectId,csrfToken,signal:requestSignal}),signal);
  const preview = result?.scope === signal && !signal.aborted ? result.value : null;
  async function generate() {
    if(locked || signal.aborted)return;
    setResult(null); setSelectedId(null);setSaved(null);setEditing(false);setConfirming(false);setNotice("");applyAction.reset();
    const value=await action.run();
    if(value !== undefined) setResult({value,scope:signal});
  }
  function selectTask(id:string) {
    setSelectedId(id);
    const task=resultRef.current?.querySelector<HTMLElement>(`[data-plan-task="${id}"]`);
    task?.scrollIntoView?.({block:"nearest"});
    task?.focus({preventScroll:true});
  }
  return <section className="project-analysis project-plan-preview" aria-labelledby={headingId}>
    <header><div><h3 id={headingId}>规划预览</h3><p>根据项目目标与已有工作，提出阶段、里程碑、任务和依赖建议。</p></div>
      <button type="button" disabled={action.pending || locked || signal.aborted} onClick={()=>void generate()}>{action.pending ? "正在生成规划…" : preview ? "重新生成规划" : "生成规划预览"}</button></header>
    {action.pending && <p role="status">正在读取项目依据并生成规划，请稍候。</p>}
    {action.state.phase === "error" && <div role="alert" className="project-analysis-error"><p>{action.state.error.message}</p>{action.state.error.traceId && <small>请求编号：{action.state.error.traceId}</small>}</div>}
    {[applyAction,lookup,historyAction].map((item,index)=>item.state.phase==="error" && <div role="alert" className="project-analysis-error" key={index}><p>{item.state.error.message}</p>{item.state.error.traceId && <small>请求编号：{item.state.error.traceId}</small>}</div>)}
    {notice && <p role="status">{notice}</p>}
    {storageError && <p role="alert">{storageError}</p>}
    {pendingId && !signal.aborted && !applyAction.pending && <div className="project-structure-actions">
      <button type="button" disabled={lookup.pending} onClick={()=>void querySubmission()}>{lookup.pending?"正在查询…":"查询提交结果"}</button>
      {!uncertain && submission && <button type="button" disabled={disabled || lookup.pending} onClick={()=>void confirm()}>重新提交同一规划</button>}
    </div>}
    {refreshFailed && <button type="button" disabled={refreshing || signal.aborted} onClick={()=>void refreshProject()}>{refreshing?"正在读取…":"重新读取项目"}</button>}
    {saved && !signal.aborted && <AppliedPlanDetails value={saved} onOpenTask={onOpenTask}/>}
    {preview && <div className="project-analysis-result" ref={resultRef}>
      <p className="project-analysis-meta">{preview.assistantName} · {preview.model.name} · <time dateTime={preview.generatedAt}>{new Date(preview.generatedAt).toLocaleString("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"})}</time></p>
      <p>{preview.plan.summary}</p>
      <p className="project-analysis-scope">这是规划建议，尚未创建或修改项目任务。{preview.plan.citationIds.length > 0 && `依据：${preview.plan.citationIds.join("、")}。`}</p>
      {preview.plan.assumptions.length > 0 && <div className="plan-assumptions"><h4>待确认的假设</h4><ul>{preview.plan.assumptions.map((assumption,index)=><li key={index}>{assumption}</li>)}</ul></div>}
      {preview.plan.status === "planned" && <>
        {preview.canApply ? <form className="plan-application-form" onSubmit={event=>{event.preventDefault();if(!locked)setConfirming(true);}}>
          {editing && <PlanDraftEditor plan={preview.plan} disabled={locked || confirming} onChange={plan=>setResult({value:{...preview,plan},scope:signal})}/>}
          {!confirming && <div className="project-structure-actions">
            <button type="button" disabled={locked} onClick={()=>setEditing(value=>!value)}>{editing?"结束调整":"调整规划"}</button>
            <button type="submit" disabled={locked || Boolean(storageError)}>检查并应用规划</button>
          </div>}
          {confirming && <div className="plan-confirmation" role="group" aria-label="确认应用规划">
            <h4>确认新增项目内容</h4>
            <p>新增 {preview.plan.stages.length} 个阶段、{preview.plan.milestones.length} 个里程碑、{preview.plan.tasks.length} 个任务、{preview.plan.tasks.reduce((sum,task)=>sum+task.dependsOn.length,0)} 条依赖。</p>
            <p>现有内容保持原样。新任务以“待规划”状态创建，负责人和日期留空；确认记录仅你可见，新增内容对有项目权限的成员可见。</p>
            <div className="project-structure-actions"><button ref={confirmRef} type="button" disabled={locked} onClick={()=>void confirm()}>{applyAction.pending?"正在创建…":"确认创建"}</button><button type="button" disabled={locked} onClick={()=>setConfirming(false)}>返回调整</button></div>
          </div>}
        </form> : <p className="project-analysis-scope">当前为只读访问，可以查看规划；应用规划需要项目写入权限。</p>}
        <h4>任务依赖图</h4>
        <p className="project-analysis-scope">箭头从前置任务指向后续任务。位置表示依赖层级，不代表日期或工期；选择节点查看建议详情。</p>
        <PlanDependencyGraph tasks={preview.plan.tasks} selectedId={selectedId} onSelect={selectTask}/>
        {preview.plan.stages.map(stage=><section className="plan-stage" key={stage.id}>
          <h4>{stage.id} · {stage.name}</h4><p>{stage.goal}</p><small>依据：{stage.citationIds.join("、")}</small>
          {preview.plan.milestones.filter(item=>item.stageId===stage.id).map(milestone=><div className="plan-milestone" key={milestone.id}><strong>{milestone.id} · {milestone.name}</strong><p>验收：{milestone.acceptanceCriteria}</p><small>依据：{milestone.citationIds.join("、")}</small></div>)}
          {preview.plan.tasks.filter(task=>task.stageId===stage.id).map(task=><article className="plan-task" key={task.id} data-plan-task={task.id} data-selected={selectedId===task.id} tabIndex={-1} aria-label={`${task.id} · ${task.title}`}>
            <h5>{task.id} · {task.title}</h5><p>{task.description}</p><p>验收：{task.acceptanceCriteria}</p><p>优先级：{PRIORITY[task.priority]} · 里程碑：{task.milestoneId ?? "未关联"}</p><p>前置任务：{task.dependsOn.length ? task.dependsOn.map(id=>`${id} ${preview.plan.tasks.find(item=>item.id===id)!.title}`).join("、") : "无"}</p><small>依据：{task.citationIds.join("、")}</small>
          </article>)}
        </section>)}
      </>}
      <p className="project-analysis-scope">{preview.citations.length ? `本次参考 ${preview.citations.length} 条检索片段，未覆盖全部资料。` : "本次未检索到知识资料，仅依据项目结构。"}项目更新后请重新生成。</p>
      <ProjectEvidence snapshot={preview.snapshot} citations={preview.citations}/>
    </div>}
    <div className="plan-history">
      <button type="button" disabled={historyAction.pending || signal.aborted} onClick={()=>void loadHistory()}>{historyAction.pending?"正在读取规划…":"查看已确认规划"}</button>
      {history && !signal.aborted && <div><h4>我已确认的规划</h4>{history.items.length===0 && <p>还没有已确认的规划。</p>}{history.items.filter(item=>item.operationId!==saved?.operationId).map(item=><AppliedPlanDetails key={item.operationId} value={item} onOpenTask={onOpenTask}/>)}{history.nextCursor && <button type="button" disabled={historyAction.pending} onClick={()=>void loadHistory(true)}>加载更多已确认规划</button>}</div>}
    </div>
  </section>;
}
