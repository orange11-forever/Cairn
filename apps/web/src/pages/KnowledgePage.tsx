import { BookOpenText, Layers3 } from "lucide-react";
import { Navigate, useParams } from "react-router-dom";

import { ApiError } from "../api/errors.ts";
import { WorkspaceHeader } from "../components/WorkspaceHeader.tsx";
import { useKnowledgeResourcesQuery } from "../queries/knowledge.ts";
import { useSession } from "../session/SessionContext.tsx";

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "知识资料暂时无法加载，请重试";
}

export function KnowledgePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { session } = useSession();

  if (projectId === undefined) return <Navigate to="/projects" replace />;
  if (session === null) return null;

  return (
    <KnowledgeWorkspace
      organizationId={session.identity.organization.id}
      projectId={projectId}
      signal={session.signal}
    />
  );
}

function KnowledgeWorkspace({
  organizationId,
  projectId,
  signal,
}: {
  organizationId: string;
  projectId: string;
  signal: AbortSignal;
}) {
  const resources = useKnowledgeResourcesQuery(organizationId, projectId, signal);
  const pages = resources.data?.pages ?? [];
  const items = pages.flatMap((page) => page.items);
  const capabilities = pages[0]?.capabilities;

  return (
    <section
      aria-busy={resources.isPending ? "true" : undefined}
      aria-label="项目知识工作区"
      className="knowledge-page"
    >
      <WorkspaceHeader
        id="knowledge-page-title"
        eyebrow="项目范围知识"
        title="项目知识"
        description="管理当前项目的资料、处理状态与检索入口。"
        status={capabilities === undefined ? undefined : (
          <span className="knowledge-access">
            {capabilities.canWrite ? "可维护资料" : "只读访问"}
          </span>
        )}
      />

      {resources.isPending ? (
        <div className="knowledge-foundation knowledge-foundation-loading">
          <span className="knowledge-stratum">正在连接项目知识</span>
          <span aria-hidden="true" className="knowledge-stratum" />
          <span aria-hidden="true" className="knowledge-stratum" />
        </div>
      ) : null}

      {resources.isError && resources.data === undefined ? (
        <div className="knowledge-state knowledge-state-error">
          <p role="alert">{errorMessage(resources.error)}</p>
          {resources.error instanceof ApiError && resources.error.retryable ? (
            <button type="button" onClick={() => void resources.refetch()}>
              重新加载知识资料
            </button>
          ) : null}
        </div>
      ) : null}

      {resources.data !== undefined && items.length === 0 ? (
        <div className="knowledge-state knowledge-state-empty">
          <BookOpenText aria-hidden="true" size={28} strokeWidth={1.8} />
          <div>
            <h2>还没有知识资料</h2>
            <p>上传入口将在后续任务接入；当前项目知识边界已经连接真实 API。</p>
          </div>
        </div>
      ) : null}

      {items.length > 0 ? (
        <div className="knowledge-state knowledge-state-connected">
          <Layers3 aria-hidden="true" size={28} strokeWidth={1.8} />
          <div>
            <h2>知识资料已连接</h2>
            <p>当前已加载 {items.length} 项；资源列表将在后续任务展开。</p>
          </div>
        </div>
      ) : null}
    </section>
  );
}
