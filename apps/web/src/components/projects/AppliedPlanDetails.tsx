import type { ProjectPlanApplication } from "../../api/projectPlanning.ts";

export function AppliedPlanDetails({value,onOpenTask}:{value:ProjectPlanApplication;onOpenTask?:(id:string)=>void}) {
  return <article className="applied-plan" aria-label="已确认规划">
    <h4>{value.plan.summary}</h4>
    <p className="project-analysis-meta">确认于 <time dateTime={value.appliedAt}>{new Date(value.appliedAt).toLocaleString("zh-CN")}</time></p>
    <p>这是确认时的规划记录。任务的当前状态和内容以项目中的实际记录为准。</p>
    {value.plan.assumptions.length>0 && <ul>{value.plan.assumptions.map((text,i)=><li key={i}>{text}</li>)}</ul>}
    {value.plan.stages.map(stage=><details key={stage.id} open>
      <summary>{stage.name}</summary><p>{stage.goal}</p>
      {value.plan.milestones.filter(item=>item.stageId===stage.id).map(item=><p key={item.id}><strong>{item.name}</strong> · 验收：{item.acceptanceCriteria}</p>)}
      <ul>{value.plan.tasks.filter(item=>item.stageId===stage.id).map(task=><li key={task.id}>
        <button type="button" onClick={()=>onOpenTask?.(value.taskIds[task.id]!)} aria-label={`打开任务：${task.title}`}>{task.title}</button>
        <p>{task.description}</p><p>验收：{task.acceptanceCriteria}</p>
        <p>确认时优先级：{{low:"低",medium:"中",high:"高",critical:"紧急"}[task.priority]}</p>
        {task.dependsOn.length>0 && <p>前置任务：{task.dependsOn.map(id=>value.plan.tasks.find(item=>item.id===id)?.title??id).join("、")}</p>}
      </li>)}</ul>
    </details>)}
  </article>;
}
