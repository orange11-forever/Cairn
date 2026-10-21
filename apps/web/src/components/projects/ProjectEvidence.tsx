import type { ProjectAnalysisResponse } from "../../api/projectAnalysis.ts";

const STATUS = {
  backlog: "待规划", todo: "待处理", in_progress: "进行中",
  blocked: "已阻塞", done: "已完成", cancelled: "已取消",
};
const PRIORITY = { low: "低", medium: "中", high: "高", critical: "紧急" };
const DATE = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});


export function ProjectEvidence({snapshot, citations}: Pick<ProjectAnalysisResponse, "snapshot" | "citations">) {
  return <>
        <details className="project-analysis-evidence">
          <summary>S1 · 项目结构快照 · {snapshot.tasks.length} 个任务</summary>
          <p>{snapshot.project.description ?? "尚未填写项目目标。"}</p>
          <p>{snapshot.stages.length} 个阶段 · {snapshot.milestones.length} 个里程碑 · {snapshot.dependencies.length} 条依赖</p>
          {snapshot.stages.length > 0 && <p>阶段：{snapshot.stages.map(stage => `${stage.name}${stage.archived ? "（已归档）" : ""}`).join("、")}</p>}
          {snapshot.milestones.map(milestone => <div key={milestone.id}>
            <p>里程碑：{milestone.name}{milestone.archived ? "（已归档）" : ""}</p>
            <p>说明：{milestone.description ?? "未填写"}</p>
            <p>截止：{milestone.dueAt ? <time dateTime={milestone.dueAt}>{DATE.format(new Date(milestone.dueAt))}</time> : "未设置"}
              {" · 阶段："}{snapshot.stages.find(stage => stage.id === milestone.stageId)?.name ?? "未归组"}</p>
            <p>验收：{milestone.acceptanceCriteria ?? "未填写"}</p>
          </div>)}
          <ul>{snapshot.tasks.map(task => <li key={task.id}>
            <strong>{task.title}</strong><span>{STATUS[task.status]}</span>
            <p>优先级：{PRIORITY[task.priority]} · 负责人：{task.assigneeUserId ?? "未分配"}</p>
            <p>截止：{task.dueAt ? <time dateTime={task.dueAt}>{DATE.format(new Date(task.dueAt))}</time> : "未设置"}</p>
            <p>阶段：{snapshot.stages.find(stage => stage.id === task.stageId)?.name ?? "未归组"}
              {" · 里程碑："}{snapshot.milestones.find(milestone => milestone.id === task.milestoneId)?.name ?? "未关联"}</p>
            {task.parentTaskId && <p>父任务：{snapshot.tasks.find(parent => parent.id === task.parentTaskId)?.title}</p>}
            {task.description && <p>{task.description}</p>}
            <p>验收：{task.acceptanceCriteria ?? "未填写"}</p>
          </li>)}</ul>
          {snapshot.dependencies.map(dependency => <p key={dependency.id}>
            {snapshot.tasks.find(task => task.id === dependency.predecessorTaskId)?.title}
            {" → "}
            {snapshot.tasks.find(task => task.id === dependency.successorTaskId)?.title}
          </p>)}
        </details>
        {citations.map(citation => <details className="project-analysis-evidence" key={citation.id}>
          <summary>{citation.id} · {citation.title}</summary>
          <p>{citation.excerpt}</p>
        </details>)}
  </>;
}
