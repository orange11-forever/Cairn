import { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "../../api/errors.ts";
import { applyProjectOperation, fetchProjectOperation, fetchProjectOperations, previewProjectOperation, type OperationPage, type OperationPreview, type OperationRequest, type ProjectAction, type ProjectOperation } from "../../api/projectOperations.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";

interface Props {projectId:string;ownerId:string;csrfToken:string;signal:AbortSignal;disabled?:boolean;onApplied:()=>Promise<void>;onBusy?:(busy:boolean)=>void;onOpenTask?:(id:string)=>void}
const TYPES={create_task:"创建任务",update_task:"调整任务字段",change_status:"变更任务状态",add_dependency:"添加依赖",remove_dependency:"移除依赖"};
const PRIORITY={low:"低",medium:"中",high:"高",critical:"紧急"};
const STATUS={backlog:"待规划",todo:"待处理",in_progress:"进行中",blocked:"已阻塞",done:"已完成",cancelled:"已取消"};
const FIELDS={title:"标题",description:"描述",priority:"优先级",acceptanceCriteria:"验收标准"};

export function OperationDetails({action,snapshot,removedPredecessorId,taskNames}:{action:ProjectAction;snapshot?:OperationPreview["snapshot"];removedPredecessorId?:string;taskNames?:Record<string,string>}) {
  const task=(id:string)=>{const title=snapshot?.tasks.find(item=>item.id===id)?.title??taskNames?.[id];return title?`${title}（${id}）`:id;};
  const value=(field:string,input:unknown)=> input===null || input==="" || input===undefined ? "未填写" : field==="priority" ? PRIORITY[input as keyof typeof PRIORITY] : String(input);
  if(action.type==="create_task")return <dl className="operation-details"><dt>标题</dt><dd>{action.title}</dd><dt>描述</dt><dd>{action.description??"未填写"}</dd><dt>优先级</dt><dd>{PRIORITY[action.priority??"medium"]}</dd><dt>验收标准</dt><dd>{action.acceptanceCriteria??"未填写"}</dd><dt>阶段 / 里程碑</dt><dd>{snapshot?.stages.find(s=>s.id===action.stageId)?.name??action.stageId??"未关联"} / {snapshot?.milestones.find(m=>m.id===action.milestoneId)?.name??action.milestoneId??"未关联"}</dd><dt>初始状态</dt><dd>待规划</dd></dl>;
  if(action.type==="update_task") {
    const before=snapshot?.tasks.find(item=>item.id===action.taskId);
    return <dl className="operation-details"><dt>任务</dt><dd>{task(action.taskId)}</dd><dt>{FIELDS[action.field]}变更</dt><dd>{before && <><span>原值：{value(action.field,before[action.field])}</span><br/></>}新值：{value(action.field,action.value)}</dd></dl>;
  }
  if(action.type==="change_status") {
    const before=snapshot?.tasks.find(item=>item.id===action.taskId);
    return <dl className="operation-details"><dt>任务</dt><dd>{task(action.taskId)}</dd><dt>状态变更</dt><dd>{before?`${STATUS[before.status]} → `:""}{STATUS[action.status]}</dd></dl>;
  }
  if(action.type==="add_dependency")return <dl className="operation-details"><dt>前置任务</dt><dd>{task(action.predecessorTaskId)}</dd><dt>后续任务</dt><dd>{task(action.successorTaskId)}</dd></dl>;
  const edge=snapshot?.dependencies.find(item=>item.id===action.dependencyId);
  const predecessor=edge?.predecessorTaskId??removedPredecessorId;
  return <dl className="operation-details"><dt>后续任务</dt><dd>{task(action.taskId)}</dd><dt>{predecessor?"移除的前置任务":"移除的依赖编号"}</dt><dd>{predecessor?task(predecessor):action.dependencyId}</dd></dl>;
}

function SavedOperation({value,onOpenTask}:{value:ProjectOperation;onOpenTask?:Props["onOpenTask"]}) {
  const taskId=value.action.type==="create_task" ? value.result.id : value.action.type==="add_dependency" ? value.action.successorTaskId : value.action.taskId;
  const taskNames:Record<string,string>={};
  if(typeof taskId==="string" && typeof value.result.title==="string")taskNames[taskId]=value.result.title;
  if(typeof value.result.predecessorTaskId==="string" && typeof value.result.predecessorTitle==="string")taskNames[value.result.predecessorTaskId]=value.result.predecessorTitle;
  if(typeof value.result.successorTaskId==="string" && typeof value.result.successorTitle==="string")taskNames[value.result.successorTaskId]=value.result.successorTitle;
  return <article className="plan-task"><h4>{TYPES[value.action.type]} · 已执行</h4><p>你的要求：{value.intent}</p><OperationDetails action={value.action} taskNames={taskNames} removedPredecessorId={typeof value.result.predecessorTaskId==="string"?value.result.predecessorTaskId:undefined}/><p><time dateTime={value.appliedAt}>{new Date(value.appliedAt).toLocaleString("zh-CN")}</time></p><small>操作编号：{value.operationId}</small>{typeof taskId==="string" && onOpenTask && <p><button type="button" onClick={()=>onOpenTask(taskId)}>打开真实任务</button></p>}</article>;
}

export function ProjectOperations(props:Props) {return <OperationsPanel key={`${props.ownerId}:${props.projectId}:${props.csrfToken}`} {...props}/>;}
function OperationsPanel({projectId,ownerId,csrfToken,signal,disabled=false,onApplied,onBusy,onOpenTask}:Props) {
  const heading=useId(),inputId=useId();
  const [intent,setIntent]=useState("");
  const [preview,setPreview]=useState<OperationPreview|null>(null);
  const [saved,setSaved]=useState<ProjectOperation|null>(null);
  const [history,setHistory]=useState<OperationPage|null>(null);
  const [notice,setNotice]=useState("");
  const [refreshing,setRefreshing]=useState(false),[refreshFailed,setRefreshFailed]=useState(false);
  const storageKey=`cairn.pending-operation:${ownerId}:${projectId}`;
  const [storage]=useState(()=>{try{return {id:sessionStorage.getItem(storageKey),error:""};}catch{return {id:null,error:"会话存储不可用，请启用后刷新页面再确认执行。"};}});
  const [storageError,setStorageError]=useState(storage.error);
  const [pendingId,setPendingId]=useState<string|null>(storage.id);
  const [uncertain,setUncertain]=useState(storage.id!==null);
  const [submission,setSubmission]=useState<OperationRequest|null>(null);
  const inFlight=useRef(false),mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const current=()=>mounted.current && !signal.aborted;
  const generation=useAbortableAction((text:string,requestSignal:AbortSignal)=>previewProjectOperation({projectId,csrfToken,intent:text,signal:requestSignal}),signal);
  const apply=useAbortableAction(async(payload:OperationRequest,requestSignal:AbortSignal)=>{
    try{return await applyProjectOperation({projectId,csrfToken,payload,signal:requestSignal});}
    catch(error){
      if(current() && !requestSignal.aborted){
        const definite=error instanceof ApiError && error.kind==="http" && error.status!==null && error.status<500 && error.code!=="operation_conflict";
        if(definite){clearPending();setSubmission(null);setNotice("操作未执行。项目或权限变化后，请重新生成建议。");}
        else {setUncertain(true);setNotice("提交结果尚未确认，请先查询结果。操作编号会继续复用，避免重复写入。");}
      }
      throw error;
    }
  },signal);
  const lookup=useAbortableAction(async(id:string,requestSignal:AbortSignal)=>{
    try{return await fetchProjectOperation({projectId,operationId:id,signal:requestSignal});}
    catch(error){if(error instanceof ApiError && error.status===404 && error.code==="not_found")return null;throw error;}
  },signal);
  const records=useAbortableAction((cursor:string|null,requestSignal:AbortSignal)=>fetchProjectOperations({projectId,cursor,signal:requestSignal}),signal);
  const busy=apply.pending || lookup.pending || refreshing;
  const locked=disabled || busy || uncertain || submission!==null || signal.aborted;
  useEffect(()=>{onBusy?.(busy || uncertain);return()=>onBusy?.(false);},[busy,uncertain,onBusy]);
  function clearPending(){
    try{sessionStorage.removeItem(storageKey);}
    catch{setStorageError("无法清除本机操作编号。已执行结果仍可查询，请启用存储后刷新页面。");}
    setPendingId(null);setUncertain(false);
  }
  async function refresh(){
    setRefreshing(true);
    try{await onApplied();if(current()){setRefreshFailed(false);setNotice("操作已执行，真实项目内容已更新。");}}
    catch{if(current()){setRefreshFailed(true);setNotice("操作已执行，但项目刷新失败。请重新读取项目，无需再次执行。");}}
    finally{if(current())setRefreshing(false);}
  }
  async function accept(value:ProjectOperation){
    if(!current())return;
    clearPending();setSubmission(null);setSaved(value);setPreview(null);apply.reset();lookup.reset();
    await refresh();
  }
  async function generate(){
    if(locked || !intent.trim())return;
    setPreview(null);setSaved(null);setNotice("");apply.reset();
    const result=await generation.run(intent.trim());
    if(result && current())setPreview(result);
  }
  async function confirm(){
    if(inFlight.current || disabled || busy || uncertain || signal.aborted || storageError || (!preview && !submission))return;
    const payload:OperationRequest=submission??{operationId:pendingId??crypto.randomUUID(),confirmed:true,preview:structuredClone(preview!)};
    try{sessionStorage.setItem(storageKey,payload.operationId);}catch{setStorageError("无法保存操作编号，请启用会话存储后再确认执行。");return;}
    inFlight.current=true;setPendingId(payload.operationId);setSubmission(payload);setNotice("");
    try{const result=await apply.run(payload);if(result)await accept(result);}finally{inFlight.current=false;}
  }
  async function query(){
    if(!pendingId)return;
    const result=await lookup.run(pendingId);
    if(result)await accept(result);
    else if(result===null && current()){setUncertain(false);setNotice(submission?"尚未找到已执行记录。可以重新提交同一个操作编号。":"尚未找到已执行记录。请重新生成建议后确认，将继续复用原操作编号。");}
  }
  async function loadHistory(more=false){
    const page=await records.run(more?history?.nextCursor??null:null);
    if(page && current())setHistory({items:more?[...(history?.items??[]),...page.items]:page.items,nextCursor:page.nextCursor});
  }
  return <section className="project-analysis project-operations" aria-labelledby={heading}>
    <header><div><h3 id={heading}>助手项目操作</h3><p>描述一个具体操作，核对建议后确认执行。支持创建任务、调整标题/描述/优先级/验收标准、更新状态及维护依赖。</p></div></header>
    <form className="operation-intent" onSubmit={event=>{event.preventDefault();void generate();}}>
      <label htmlFor={inputId}>你要执行的操作</label><textarea id={inputId} value={intent} maxLength={2000} rows={3} disabled={locked || generation.pending} onChange={event=>{setIntent(event.target.value);setPreview(null);}} placeholder="例如：创建一个名为“确认发布窗口”的高优先级任务"/>
      <button type="submit" disabled={locked || generation.pending || !intent.trim()}>{generation.pending?"正在生成建议…":"生成待确认操作"}</button>
    </form>
    {[generation,apply,lookup,records].map((item,index)=>item.state.phase==="error" && <div className="project-analysis-error" role="alert" key={index}><p>{index===1 && preview?.suggestion.action?`${TYPES[preview.suggestion.action.type]}：`:""}{item.state.error.message}</p>{item.state.error.traceId && <small>请求编号：{item.state.error.traceId}</small>}</div>)}
    {storageError && <p role="alert">{storageError}</p>}
    {notice && <p role="status">{notice}</p>}
    {uncertain && !notice && <p role="status">上次提交结果尚未确认，请先查询操作结果。</p>}
    {pendingId && <div className="project-structure-actions"><button type="button" disabled={busy || signal.aborted} onClick={()=>void query()}>{lookup.pending?"正在查询…":"查询操作结果"}</button>{submission && !uncertain && <button type="button" disabled={disabled || busy || signal.aborted} onClick={()=>void confirm()}>重新提交同一操作</button>}</div>}
    {refreshFailed && <button type="button" disabled={refreshing || signal.aborted} onClick={()=>void refresh()}>重新读取项目</button>}
    {preview && !signal.aborted && <div className="plan-confirmation" role="group" aria-label="确认助手操作">
      <h4>{preview.suggestion.action?TYPES[preview.suggestion.action.type]:"需要补充说明"}</h4><p>{preview.suggestion.explanation}</p>
      {preview.suggestion.action && <><OperationDetails action={preview.suggestion.action} snapshot={preview.snapshot}/><p className="project-analysis-scope">以上是待确认变更，尚未执行。操作记录仅你可见，实际任务按项目权限共享。</p>{preview.canExecute?<button type="button" disabled={locked || Boolean(storageError)} onClick={()=>void confirm()}>{apply.pending?"正在执行…":"确认执行此操作"}</button>:<p>当前为只读访问，执行需要项目写入权限。</p>}</>}
    </div>}
    {saved && !signal.aborted && <SavedOperation value={saved} onOpenTask={onOpenTask}/>}
    <div className="plan-history"><button type="button" disabled={records.pending || signal.aborted} onClick={()=>void loadHistory()}>{records.pending?"正在读取记录…":"查看我的操作记录"}</button>{history && !signal.aborted && <div><h4>我已确认的操作</h4>{history.items.length===0 && <p>还没有已执行的操作。</p>}{history.items.filter(item=>item.operationId!==saved?.operationId).map(item=><SavedOperation key={item.operationId} value={item} onOpenTask={onOpenTask}/>)}{history.nextCursor && <button type="button" disabled={records.pending} onClick={()=>void loadHistory(true)}>加载更多操作</button>}</div>}</div>
  </section>;
}
