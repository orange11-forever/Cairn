import type { ProjectPlanPreviewResponse } from "../../api/projectPlanning.ts";

type Draft = ProjectPlanPreviewResponse["plan"];

export function PlanDraftEditor({plan, onChange, disabled}: {plan: Draft; onChange(value: Draft): void; disabled: boolean}) {
  return <div className="plan-editor">
    <p>调整将创建的内容。阶段归属和任务依赖沿用当前建议，创建后可在项目中继续编辑。</p>
    {plan.stages.map((stage,index)=><fieldset key={stage.id} disabled={disabled}>
      <legend>{stage.id} · 阶段</legend>
      <label>{stage.id} 阶段名称<input required maxLength={120} value={stage.name} onChange={e=>onChange({...plan,stages:plan.stages.map((item,i)=>i===index?{...item,name:e.target.value}:item)})}/></label>
      <p>{stage.goal}</p>
    </fieldset>)}
    {plan.milestones.map((milestone,index)=><fieldset key={milestone.id} disabled={disabled}>
      <legend>{milestone.id} · 里程碑</legend>
      <label>{milestone.id} 里程碑名称<input required maxLength={160} value={milestone.name} onChange={e=>onChange({...plan,milestones:plan.milestones.map((item,i)=>i===index?{...item,name:e.target.value}:item)})}/></label>
      <label>{milestone.id} 验收标准<textarea required maxLength={600} rows={2} value={milestone.acceptanceCriteria} onChange={e=>onChange({...plan,milestones:plan.milestones.map((item,i)=>i===index?{...item,acceptanceCriteria:e.target.value}:item)})}/></label>
    </fieldset>)}
    {plan.tasks.map((task,index)=>{
      function update(value:Partial<Draft["tasks"][number]>) {onChange({...plan,tasks:plan.tasks.map((item,i)=>i===index?{...item,...value}:item)});}
      return <fieldset key={task.id} disabled={disabled}>
        <legend>{task.id} · 任务</legend>
        <label>{task.id} 任务名称<input required maxLength={160} value={task.title} onChange={e=>update({title:e.target.value})}/></label>
        <label>{task.id} 任务描述<textarea required maxLength={600} rows={3} value={task.description} onChange={e=>update({description:e.target.value})}/></label>
        <label>{task.id} 验收标准<textarea required maxLength={600} rows={2} value={task.acceptanceCriteria} onChange={e=>update({acceptanceCriteria:e.target.value})}/></label>
        <label>{task.id} 优先级<select value={task.priority} onChange={e=>update({priority:e.target.value as typeof task.priority})}><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">紧急</option></select></label>
      </fieldset>;
    })}
  </div>;
}
