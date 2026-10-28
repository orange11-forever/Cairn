import { useEffect, useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Project } from "../../api/projects.ts";
import { fetchScheduleScenario, updateProjectCapacity, type CapacityRequest, type ScheduleScenario } from "../../api/projectScheduling.ts";
import { effortLabel, hoursToMinutes, minutesToHours } from "../../lib/effort.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";
import { projectKeys, refreshProjectStructure, useProjectQuery } from "../../queries/projects.ts";

interface Props {organizationId:string;projectId:string;csrfToken:string;signal:AbortSignal;disabled?:boolean;onBusy?:(busy:boolean)=>void;onOpenTask?:(id:string)=>void}
const STATUSES={backlog:"待规划",todo:"待处理",in_progress:"进行中",blocked:"已阻塞",done:"已完成",cancelled:"已取消"};
const DAYS=["周一","周二","周三","周四","周五","周六","周日"];
function localToday(){const now=new Date();return new Date(now.getTime()-now.getTimezoneOffset()*60_000).toISOString().slice(0,10);}

export function ProjectSchedule(props:Props){return <SchedulePanel key={`${props.projectId}:${props.csrfToken}`} {...props}/>;}
function SchedulePanel({organizationId,projectId,csrfToken,signal,disabled=false,onBusy,onOpenTask}:Props){
  const heading=useId(),dateId=useId(),client=useQueryClient();
  const project=useProjectQuery(organizationId,projectId,signal);
  const [start,setStart]=useState(localToday),[result,setResult]=useState<ScheduleScenario|null>(null),[canWrite,setCanWrite]=useState<boolean|null>(null);
  const [notice,setNotice]=useState("");
  const action=useAbortableAction((startDate:string,requestSignal:AbortSignal)=>fetchScheduleScenario({projectId,startDate,signal:requestSignal}),signal);
  const current=result && !signal.aborted && !project.isFetching && !project.isError && result.startDate===start && result.project.revision===project.data?.revision ? result : null;
  async function calculate(){
    if(disabled || !start || signal.aborted)return;
    setResult(null);setNotice("");const value=await action.run(start);
    if(value && !signal.aborted){
      const latest=client.getQueryData<Project>(projectKeys.detail(organizationId,projectId));
      if((latest?.revision??0)>(value.project.revision??0)){setNotice("计算期间项目已更新，请重新计算。");return;}
      client.setQueryData(projectKeys.detail(organizationId,projectId),value.project);setResult(value);setCanWrite(value.canWrite);
    }
  }
  const capacityProject=project.data?.workingWeekdays ? {...project.data,workingWeekdays:project.data.workingWeekdays} : null;
  const taskName=(id:string)=>current?.tasks.find(task=>task.id===id)?.title??id;
  return <section className="project-analysis project-schedule" aria-labelledby={heading}>
    <header><div><h3 id={heading}>进度与工期情景</h3><p>使用已记录的剩余工作量、依赖和项目每日总人时计算串行情景。日期表示当前假设下的结果。</p></div></header>
    <form className="schedule-controls" onSubmit={event=>{event.preventDefault();void calculate();}}><label htmlFor={dateId}>情景开始日期</label><input id={dateId} type="date" required value={start} onChange={event=>setStart(event.target.value)} disabled={disabled || action.pending}/><button type="submit" disabled={disabled || action.pending || !start || signal.aborted}>{action.pending?"正在计算…":"计算工期情景"}</button></form>
    {action.state.phase==="error" && <div className="project-analysis-error" role="alert"><p>{action.state.error.message}</p>{action.state.error.traceId && <small>请求编号：{action.state.error.traceId}</small>}</div>}
    {notice && <p role="status">{notice}</p>}
    {result && !current && !action.pending && !signal.aborted && <p role="status">项目输入或开始日期已变化，旧情景已隐藏。请重新计算。</p>}
    {canWrite && capacityProject && <CapacityEditor project={capacityProject} organizationId={organizationId} csrfToken={csrfToken} signal={signal} disabled={disabled} onBusy={onBusy} onSaved={()=>setNotice("产能已保存，请重新计算工期情景。")}/>}
    {canWrite===false && <p className="project-analysis-scope">当前为只读访问，可查看情景；修改产能和任务工作量需要项目写入权限。</p>}
    {current && <div className="project-analysis-result">
      <p className="project-analysis-meta">读取时间：<time dateTime={current.readAt}>{new Date(current.readAt).toLocaleString("zh-CN")}</time> · 项目修订 {current.project.revision}</p>
      <p>已知剩余工作量：{effortLabel(current.knownRemainingMinutes)}。每日项目总产能：{effortLabel(current.project.dailyCapacityMinutes)}。</p>
      <p className="project-analysis-scope">以下状态来自实际任务记录；估算、剩余量与情景日期分别展示，不推算工作量完成率。</p>
      {current.gaps.length>0 && <div className="schedule-gaps"><h4>暂不能给出完成日期</h4><ul>{current.gaps.map((gap,index)=><li key={index}>{gap.message}{gap.taskIds.length>0 && <> 涉及：{gap.taskIds.map(taskName).join("、")}</>}</li>)}</ul></div>}
      {current.warnings.length>0 && <details><summary>估算提醒（{current.warnings.length}）</summary><ul>{current.warnings.map((warning,index)=><li key={index}>{warning.message} {warning.taskIds.map(taskName).join("、")}</li>)}</ul></details>}
      {current.completionDate && <div className="schedule-dates"><h4>串行资源排程</h4><p>工作日开始：<time dateTime={current.effectiveStartDate??undefined}>{current.effectiveStartDate}</time> · 情景完成：<time dateTime={current.completionDate}>{current.completionDate}</time></p><p className="project-analysis-scope">每日余量可继续下一任务，正工作量任务在完整工作日之后进入下一工作日；0工作量不额外占用日期。</p></div>}
      {current.criticalChain && <div className="schedule-critical"><h4>最长依赖链下界</h4><p>{effortLabel(current.criticalChain.remainingMinutes)} ÷ 每日产能 = {new Intl.NumberFormat("zh-CN",{maximumFractionDigits:3}).format(current.criticalChain.workdayLowerBound)} 个理论工作日。</p><p>{current.criticalChain.taskIds.length?current.criticalChain.taskIds.map(taskName).join(" → "):"没有未完成任务。"}</p><p className="project-analysis-scope">此下界忽略任务之间共享产能的争用，不能代替上方串行资源完成日期。</p></div>}
      <h4>实际任务与计算输入</h4><div className="schedule-table-scroll"><table className="schedule-table"><thead><tr><th scope="col">任务 / 实际状态</th><th scope="col">初始估算</th><th scope="col">记录剩余量</th><th scope="col">情景日期 / 工作分钟偏移</th></tr></thead><tbody>{current.tasks.map(task=>{const row=current.schedule.find(item=>item.taskId===task.id);return <tr key={task.id}><th scope="row"><button type="button" disabled={disabled || !onOpenTask} onClick={()=>onOpenTask?.(task.id)}>{task.title}</button><small>{STATUSES[task.status]} · 修订 {task.revision}</small></th><td>{effortLabel(task.estimatedEffortMinutes)}</td><td>{effortLabel(task.remainingEffortMinutes)}{task.status==="done" && <small>计算按0处理</small>}{task.status==="cancelled" && <small>已排除工作量</small>}</td><td>{row?<><span>{row.startDate} → {row.endDate}</span><small>{row.startOffsetMinutes} → {row.endOffsetMinutes} 分钟</small></>:task.status==="done"?"实际已完成":task.status==="cancelled"?"实际已取消":"暂无日期"}</td></tr>;})}</tbody></table></div>
      {current.tasks.length===0 && <p>当前项目没有任务。</p>}
      <details className="schedule-assumptions"><summary>计算方法、周日历与假设</summary><p>工作日：{current.project.workingWeekdays.map(day=>DAYS[day-1]).join("、")}。</p><ul>{current.assumptions.map(item=><li key={item}>{item}</li>)}</ul><p>任务优先级、创建时间、修订、工作量与完整依赖均随本次响应返回；重算使用最新读取的项目数据。</p></details>
    </div>}
  </section>;
}

function CapacityEditor({project,organizationId,csrfToken,signal,disabled,onBusy,onSaved}:{project:Project & {workingWeekdays:number[]};organizationId:string;csrfToken:string;signal:AbortSignal;disabled:boolean;onBusy?:Props["onBusy"];onSaved:()=>void}){
  const id=useId(),client=useQueryClient();
  const [hours,setHours]=useState(minutesToHours(project.dailyCapacityMinutes)),[weekdays,setWeekdays]=useState(project.workingWeekdays);
  const [revision,setRevision]=useState(project.revision),[notice,setNotice]=useState(""),[refreshing,setRefreshing]=useState(false),[refreshFailed,setRefreshFailed]=useState(false);
  const mounted=useRef(true);useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const save=useAbortableAction((payload:CapacityRequest,requestSignal:AbortSignal)=>updateProjectCapacity({projectId:project.id,csrfToken,payload,signal:requestSignal}),signal);
  const busy=save.pending || refreshing;
  useEffect(()=>{onBusy?.(busy);return()=>onBusy?.(false);},[busy,onBusy]);
  const stale=revision!==project.revision;
  function reload(){setRevision(project.revision);setHours(minutesToHours(project.dailyCapacityMinutes));setWeekdays(project.workingWeekdays);setNotice("");save.reset();}
  async function refresh(){
    setRefreshing(true);
    try{await refreshProjectStructure(client,organizationId,project.id);if(mounted.current && !signal.aborted){setRefreshFailed(false);setNotice("产能已保存。");}}
    catch{if(mounted.current && !signal.aborted){setRefreshFailed(true);setNotice("产能已保存，但项目刷新失败。请重新读取项目，无需再次保存。");}}
    finally{if(mounted.current)setRefreshing(false);}
  }
  return <details className="schedule-capacity"><summary>设置项目每日可投入总人时</summary><form className="plan-editor" onSubmit={async event=>{
    event.preventDefault();if(disabled || busy || stale || refreshFailed || revision===null || revision===undefined)return;
    let minutes:number|null;try{minutes=hoursToMinutes(hours);}catch(error){setNotice(error instanceof Error?error.message:"请检查每日产能。");return;}
    if(weekdays.length===0){setNotice("请至少选择一个工作日。");return;}
    const value=await save.run({expectedProjectRevision:revision,dailyCapacityMinutes:minutes,workingWeekdays:weekdays});
    if(value && mounted.current && !signal.aborted){setRevision(value.revision);client.setQueryData(projectKeys.detail(organizationId,project.id),value);onSaved();await refresh();}
  }}><fieldset disabled={disabled || busy || refreshFailed}><label htmlFor={id}>每天可投入的人时（整个项目合计）<input id={id} type="number" min="0" step="any" value={hours} onChange={event=>setHours(event.target.value)}/></label><p className="project-analysis-scope">留空为未知，0为当前不可用。按最近整分钟保存；不按成员分配产能。</p><fieldset className="schedule-weekdays"><legend>每周工作日</legend>{DAYS.map((name,index)=><label key={name}><input type="checkbox" checked={weekdays.includes(index+1)} onChange={event=>setWeekdays(days=>event.target.checked?[...days,index+1].sort((a,b)=>a-b):days.filter(day=>day!==index+1))}/>{name}</label>)}</fieldset><button type="submit" disabled={stale || !revision}>{save.pending?"正在保存产能…":"保存项目产能"}</button></fieldset>{stale && <p role="status">项目版本已变化，本地输入已保留。<button type="button" disabled={busy} onClick={reload}>重新读取产能（替换输入）</button></p>}{save.state.phase==="error" && <div role="alert"><p>{save.state.error.message}</p>{save.state.error.traceId && <small>请求编号：{save.state.error.traceId}</small>}<button type="button" disabled={busy} onClick={()=>{void client.refetchQueries({queryKey:projectKeys.detail(organizationId,project.id),exact:true});}}>重新读取项目版本</button></div>}{notice && <p role="status">{notice}</p>}{refreshFailed && <button type="button" disabled={refreshing || signal.aborted} onClick={()=>void refresh()}>重新读取项目</button>}</form></details>;
}
