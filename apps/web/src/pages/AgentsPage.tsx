import { Link, Navigate, useParams } from "react-router-dom";

import { ApiError } from "../api/errors.ts";
import { AssistantSkills } from "../components/knowledge/AssistantSkills.tsx";
import { useProjectConversations } from "../components/knowledge/ProjectConversationsContext.tsx";
import { CairnLoader } from "../components/trail/CairnLoader.tsx";
import { WorkspaceHeader } from "../components/WorkspaceHeader.tsx";
import { useProjectQuery } from "../queries/projects.ts";
import { useSession } from "../session/SessionContext.tsx";

export function AgentsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { session } = useSession();
  if (projectId === undefined) return <Navigate to="/projects" replace />;
  if (session === null) return null;
  return <AgentWorkspace key={`${session.generation}:${projectId}`} projectId={projectId}
    organizationId={session.identity.organization.id} csrfToken={session.identity.csrfToken}
    signal={session.signal} />;
}

function AgentWorkspace({ projectId, organizationId, csrfToken, signal }: {
  projectId: string; organizationId: string; csrfToken: string; signal: AbortSignal;
}) {
  const project = useProjectQuery(organizationId, projectId, signal);
  const state = useProjectConversations();
  const error = project.error ?? state?.projectError;
  return <section className="agents-page" aria-labelledby="agents-page-title">
    <WorkspaceHeader id="agents-page-title" title="智能体"
      description="统一创建和配置你的项目助手，用于知识问答和编程任务。" />
    {project.isPending || project.isFetching ? <CairnLoader label="正在读取项目…" size="sm" /> : error ?
      <div className="agents-page-error">
        <p role="alert">{error instanceof Error ? error.message : "项目暂时无法读取。"}</p>
        {error instanceof ApiError && error.retryable ? <button type="button" onClick={() => void project.refetch()}>重新读取项目</button> : null}
        <Link to="/projects">返回项目</Link>
      </div> : project.data ? <>
        <p className="agents-project-scope">{project.data.name} · 当前账号的个人智能体 · 每个项目最多 20 个</p>
        <AssistantSkills projectId={projectId} csrfToken={csrfToken} sessionSignal={signal} standalone />
      </> : null}
  </section>;
}
