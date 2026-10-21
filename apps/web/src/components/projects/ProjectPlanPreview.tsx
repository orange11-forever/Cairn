import { useId, useRef, useState } from "react";
import { previewProjectPlan, type ProjectPlanPreviewResponse } from "../../api/projectPlanning.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";
import { ProjectEvidence } from "./ProjectEvidence.tsx";
import { PlanDependencyGraph } from "./PlanDependencyGraph.tsx";

interface Props {projectId: string; csrfToken: string; signal: AbortSignal}
const PRIORITY = {low:"低",medium:"中",high:"高",critical:"紧急"};

export function ProjectPlanPreview(props: Props) {
  return <PlanningPanel key={`${props.projectId}:${props.csrfToken}`} {...props}/>;
}

function PlanningPanel({projectId,csrfToken,signal}:Props) {
  const headingId = useId();
  const resultRef = useRef<HTMLDivElement>(null);
  const [result,setResult] = useState<{value:ProjectPlanPreviewResponse;scope:AbortSignal}|null>(null);
  const [selectedId,setSelectedId] = useState<string|null>(null);
  const action = useAbortableAction((requestSignal:AbortSignal)=>previewProjectPlan({projectId,csrfToken,signal:requestSignal}),signal);
  const preview = result?.scope === signal && !signal.aborted ? result.value : null;
  async function generate() {
    setResult(null); setSelectedId(null);
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
      <button type="button" disabled={action.pending || signal.aborted} onClick={()=>void generate()}>{action.pending ? "正在生成规划…" : preview ? "重新生成规划" : "生成规划预览"}</button></header>
    {action.pending && <p role="status">正在读取项目依据并生成规划，请稍候。</p>}
    {action.state.phase === "error" && <div role="alert" className="project-analysis-error"><p>{action.state.error.message}</p>{action.state.error.traceId && <small>请求编号：{action.state.error.traceId}</small>}</div>}
    {preview && <div className="project-analysis-result" ref={resultRef}>
      <p className="project-analysis-meta">{preview.assistantName} · {preview.model.name} · <time dateTime={preview.generatedAt}>{new Date(preview.generatedAt).toLocaleString("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"})}</time></p>
      <p>{preview.plan.summary}</p>
      <p className="project-analysis-scope">这是规划建议，尚未创建或修改项目任务。{preview.plan.citationIds.length > 0 && `依据：${preview.plan.citationIds.join("、")}。`}</p>
      {preview.plan.assumptions.length > 0 && <div className="plan-assumptions"><h4>待确认的假设</h4><ul>{preview.plan.assumptions.map((assumption,index)=><li key={index}>{assumption}</li>)}</ul></div>}
      {preview.plan.status === "planned" && <>
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
  </section>;
}
