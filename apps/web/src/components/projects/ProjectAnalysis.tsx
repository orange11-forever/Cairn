import { useId, useState } from "react";
import { ProjectEvidence } from "./ProjectEvidence.tsx";

import { analyzeProject, type ProjectAnalysisResponse } from "../../api/projectAnalysis.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";

interface Props { projectId: string; csrfToken: string; signal: AbortSignal }


export function ProjectAnalysis(props: Props) {
  return <AnalysisPanel key={`${props.projectId}:${props.csrfToken}`} {...props} />;
}

function AnalysisPanel({ projectId, csrfToken, signal }: Props) {
  const headingId = useId();
  const [result, setResult] = useState<{ value: ProjectAnalysisResponse; scope: AbortSignal } | null>(null);
  const action = useAbortableAction(
    (requestSignal: AbortSignal) => analyzeProject({ projectId, csrfToken, signal: requestSignal }), signal,
  );
  const analysis = result?.scope === signal && !signal.aborted ? result.value : null;

  async function run() {
    setResult(null);
    const value = await action.run();
    if (value !== undefined) setResult({ value, scope: signal });
  }

  return (
    <section className="project-analysis" aria-labelledby={headingId}>
      <header>
        <div>
          <h3 id={headingId}>项目分析</h3>
          <p>依据已保存的项目内容和相关资料，梳理进展、缺口、风险与下一步。</p>
        </div>
        <button type="button" disabled={action.pending || signal.aborted} onClick={() => void run()}>
          {action.pending ? "正在分析…" : analysis ? "重新分析" : "分析项目"}
        </button>
      </header>
      {action.pending && <p role="status">正在读取项目与资料并生成分析，请稍候。</p>}
      {action.state.phase === "error" && <div role="alert" className="project-analysis-error">
        <p>{action.state.error.message}</p>
        {action.state.error.code === "answer_unavailable" && <p>请确认已在服务端配置可用模型；可在知识工作区的“助手与技能”中选择模型。</p>}
        {action.state.error.traceId && <small>请求编号：{action.state.error.traceId}</small>}
      </div>}
      {analysis && <div className="project-analysis-result">
        <p className="project-analysis-meta">
          {analysis.assistantName} · {analysis.model.name} · <time dateTime={analysis.generatedAt}>
            {new Date(analysis.generatedAt).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
          </time>
        </p>
        {analysis.status === "insufficient_evidence" ? <p role="status">现有信息不足以形成分析，请补充项目目标、任务或资料后重新分析。</p> :
          <div className="project-analysis-findings">
            {analysis.paragraphs.map((paragraph, index) => <div key={index}>
              <p>{paragraph.text}</p>
              <small>依据：{paragraph.citationIds.join("、")}</small>
            </div>)}
          </div>
        }
        <p className="project-analysis-scope">{analysis.citations.length === 0
          ? "本次未检索到知识资料，分析仅依据项目结构。"
          : `本次参考 ${analysis.citations.length} 条资料片段，未覆盖全部项目资料。`}
          项目更新后请重新分析；建议尚未应用到项目。
        </p>
        <ProjectEvidence snapshot={analysis.snapshot} citations={analysis.citations} />
      </div>}
    </section>
  );
}
