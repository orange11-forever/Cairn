import { useQueryClient } from "@tanstack/react-query";
import { BookOpenText, CalendarDays, FileText, HardDrive, PackageOpen } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";

import { ApiError } from "../api/errors.ts";
import type { KnowledgeResource } from "../api/knowledge.ts";
import { KnowledgeSearch } from "../components/knowledge/KnowledgeSearch.tsx";
import { WorkspaceHeader } from "../components/WorkspaceHeader.tsx";
import { formatCalendarDate } from "../lib/dateTime.ts";
import { formatKnowledgeMediaType } from "../lib/knowledgeSearch.ts";
import { formatBytes } from "../lib/validation.ts";
import { knowledgeKeys, useKnowledgeResourcesQuery } from "../queries/knowledge.ts";
import { useSession } from "../session/SessionContext.tsx";

type ResourceStatus = NonNullable<KnowledgeResource["latestVersion"]>["status"];

const RESOURCE_STATUS_LABELS: Record<ResourceStatus, string> = {
  queued: "等待处理",
  processing: "处理中",
  ready: "可检索",
  failed: "处理失败",
};

const UPDATED_DATE_FORMAT = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "long",
  day: "numeric",
});

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
      csrfToken={session.identity.csrfToken}
      signal={session.signal}
    />
  );
}

function KnowledgeWorkspace({
  organizationId,
  projectId,
  csrfToken,
  signal,
}: {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  signal: AbortSignal;
}) {
  const queryClient = useQueryClient();
  const [searchAccessError, setSearchAccessError] = useState<ApiError | null>(null);
  useEffect(() => setSearchAccessError(null), [organizationId, projectId]);

  const handleSearchAccessUnavailable = useCallback((error: ApiError) => {
    setSearchAccessError(error);
    const projectKey = knowledgeKeys.project(organizationId, projectId);
    void queryClient.cancelQueries({ queryKey: projectKey }).finally(() => {
      queryClient.removeQueries({ queryKey: projectKey });
    });
  }, [organizationId, projectId, queryClient]);

  if (searchAccessError !== null) {
    return <KnowledgeAccessUnavailable error={searchAccessError} />;
  }

  return (
    <KnowledgeWorkspaceContent
      organizationId={organizationId}
      projectId={projectId}
      csrfToken={csrfToken}
      signal={signal}
      onSearchAccessUnavailable={handleSearchAccessUnavailable}
    />
  );
}

function KnowledgeAccessUnavailable({ error }: { error: ApiError }) {
  return (
    <section aria-label="项目知识工作区" className="knowledge-page">
      <WorkspaceHeader
        id="knowledge-page-title"
        eyebrow="项目范围知识"
        title="项目知识"
        description="管理当前项目的资料、处理状态与检索入口。"
      />
      <div className="knowledge-state knowledge-state-error">
        <p role="alert">{errorMessage(error)}</p>
      </div>
    </section>
  );
}

function KnowledgeWorkspaceContent({
  organizationId,
  projectId,
  csrfToken,
  signal,
  onSearchAccessUnavailable,
}: {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  signal: AbortSignal;
  onSearchAccessUnavailable(error: ApiError): void;
}) {
  const resources = useKnowledgeResourcesQuery(organizationId, projectId, signal);
  const accessError = resources.isError &&
    resources.error instanceof ApiError &&
    resources.error.status === 404
    ? resources.error
    : null;
  const accessUnavailable = accessError !== null;
  const pages = accessUnavailable ? [] : (resources.data?.pages ?? []);
  const items = pages.flatMap((page) => page.items);
  const capabilities = pages[pages.length - 1]?.capabilities;
  const displayedError = accessError ?? resources.error;

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

      {accessUnavailable || (resources.isError && resources.data === undefined) ? (
        <div className="knowledge-state knowledge-state-error">
          <p role="alert">{errorMessage(displayedError)}</p>
          {displayedError instanceof ApiError && displayedError.retryable ? (
            <button type="button" onClick={() => void resources.refetch()}>
              重新加载知识资料
            </button>
          ) : null}
        </div>
      ) : null}

      {!accessUnavailable && resources.data !== undefined ? (
        <KnowledgeSearch
          key={`${organizationId}:${projectId}`}
          organizationId={organizationId}
          projectId={projectId}
          csrfToken={csrfToken}
          sessionSignal={signal}
          onAccessUnavailable={onSearchAccessUnavailable}
        />
      ) : null}

      {!accessUnavailable && resources.data !== undefined && items.length === 0 ? (
        <div className="knowledge-state knowledge-state-empty">
          <BookOpenText aria-hidden="true" size={28} strokeWidth={1.8} />
          <div>
            <h2>还没有知识资料</h2>
            <p>上传入口将在后续任务接入；当前项目知识边界已经连接真实 API。</p>
          </div>
        </div>
      ) : null}

      {items.length > 0 ? (
        <KnowledgeResourceList
          items={items}
          hasNextPage={resources.hasNextPage}
          paginationError={resources.isFetchNextPageError ? resources.error : null}
          pending={resources.isFetchingNextPage}
          onLoadMore={() => void resources.fetchNextPage()}
        />
      ) : null}
    </section>
  );
}

function KnowledgeResourceList({
  items,
  hasNextPage,
  paginationError,
  pending,
  onLoadMore,
}: {
  items: KnowledgeResource[];
  hasNextPage: boolean;
  paginationError: unknown;
  pending: boolean;
  onLoadMore(): void;
}) {
  const canRetryPagination = paginationError instanceof ApiError && paginationError.retryable;

  return (
    <section className="knowledge-resources" aria-labelledby="knowledge-resources-title">
      <div className="knowledge-resources-heading">
        <div>
          <span className="knowledge-resources-kicker">资料状态</span>
          <h2 id="knowledge-resources-title">知识资料</h2>
        </div>
        <span>已加载 {items.length} 项</span>
      </div>
      <ul aria-label="知识资料" className="knowledge-resource-list">
        {items.map((resource) => (
          <KnowledgeResourceRow key={resource.id} resource={resource} />
        ))}
      </ul>
      {hasNextPage ? (
        <div className="knowledge-pagination">
          {paginationError !== null ? (
            <p role="alert">{errorMessage(paginationError)}</p>
          ) : null}
          {paginationError === null || canRetryPagination ? (
            <button type="button" disabled={pending} onClick={onLoadMore}>
              {pending
                ? "正在加载更多知识资料"
                : paginationError === null
                  ? "加载更多知识资料"
                  : "重新加载更多知识资料"}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function KnowledgeResourceRow({ resource }: { resource: KnowledgeResource }) {
  const version = resource.latestVersion;
  const status = version?.status ?? "waiting";
  const statusLabel = version === null ? "等待版本" : RESOURCE_STATUS_LABELS[version.status];

  return (
    <li className="knowledge-resource" data-status={status}>
      <article>
        <FileText aria-hidden="true" className="knowledge-resource-icon" size={22} strokeWidth={1.7} />
        <div className="knowledge-resource-content">
          <div className="knowledge-resource-title-line">
            <h3>{resource.title}</h3>
            <span className="knowledge-resource-status" data-status={status}>{statusLabel}</span>
          </div>
          <div className="knowledge-resource-metadata">
            {version === null ? (
              <>
                <span>
                  <FileText aria-hidden="true" size={15} />
                  文件类型待生成
                </span>
                <span>
                  <HardDrive aria-hidden="true" size={15} />
                  文件大小待生成
                </span>
                {resource.sourceType === "zip_entry" ? (
                  <span>
                    <PackageOpen aria-hidden="true" size={15} />
                    ZIP 内文件
                  </span>
                ) : null}
              </>
            ) : (
              <>
                <span title={version.mediaType}>
                  <FileText aria-hidden="true" size={15} />
                  {formatKnowledgeMediaType(version.mediaType)}
                </span>
                <span>
                  <HardDrive aria-hidden="true" size={15} />
                  {formatBytes(version.sizeBytes)}
                </span>
              </>
            )}
            <time dateTime={resource.updatedAt}>
              <CalendarDays aria-hidden="true" size={15} />
              {formatCalendarDate(resource.updatedAt, UPDATED_DATE_FORMAT)}
            </time>
          </div>
        </div>
      </article>
    </li>
  );
}
