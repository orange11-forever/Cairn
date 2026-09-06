import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { BookOpenText, CalendarDays, FileText, HardDrive, PackageOpen } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useParams } from "react-router-dom";

import { ApiError } from "../api/errors.ts";
import type { KnowledgeResource, KnowledgeResourcePage } from "../api/knowledge.ts";
import { KnowledgeSearch } from "../components/knowledge/KnowledgeSearch.tsx";
import { KnowledgeResourceDetails } from "../components/knowledge/KnowledgeResourceDetails.tsx";
import { KnowledgeUploadBatch } from "../components/knowledge/KnowledgeUploadBatch.tsx";
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
      key={`${session.generation}:${session.identity.organization.id}:${projectId}`}
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
  const queryClient = useQueryClient();
  const resources = useKnowledgeResourcesQuery(organizationId, projectId, signal);
  const active = useRef(true);
  const deletionNotice = useRef<HTMLParagraphElement | null>(null);
  const [resourceDeletion, setResourceDeletion] = useState<{
    revision: number;
    title: string;
  } | null>(null);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);
  useEffect(() => {
    if (resourceDeletion === null) return;
    requestAnimationFrame(() => deletionNotice.current?.focus());
  }, [resourceDeletion]);
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
  const handleResourceMissing = useCallback(async () => {
    void queryClient.invalidateQueries({
      queryKey: knowledgeKeys.searches(organizationId, projectId),
      refetchType: "none",
    });
    await resources.refetch();
  }, [organizationId, projectId, queryClient, resources.refetch]);

  const handleRetrySucceeded = useCallback(async (resource: KnowledgeResource) => {
    queryClient.setQueryData<InfiniteData<KnowledgeResourcePage, string | null>>(
      knowledgeKeys.resources(organizationId, projectId),
      (current) => current === undefined ? current : {
        ...current,
        pages: current.pages.map((page) => ({
          ...page,
          items: page.items.map((item) => item.id === resource.id ? resource : item),
        })),
      },
    );
    await queryClient.invalidateQueries({
      queryKey: knowledgeKeys.searches(organizationId, projectId),
      refetchType: "none",
    });
    await queryClient.invalidateQueries({
      queryKey: knowledgeKeys.resources(organizationId, projectId),
      exact: true,
      refetchType: "active",
    });
  }, [organizationId, projectId, queryClient]);

  const handleDeleteSucceeded = useCallback(async (resource: KnowledgeResource) => {
    const resourceKey = knowledgeKeys.resource(organizationId, projectId, resource.id);
    const searchesKey = knowledgeKeys.searches(organizationId, projectId);
    const citationFilter = {
      predicate: ({ queryKey }: { queryKey: readonly unknown[] }) =>
        queryKey[0] === "project-knowledge" &&
        queryKey[1] === organizationId &&
        queryKey[2] === projectId &&
        queryKey[3] === "citation-context" &&
        queryKey[4] === resource.id,
    };
    await Promise.all([
      queryClient.cancelQueries({
        queryKey: knowledgeKeys.resources(organizationId, projectId), exact: true,
      }),
      queryClient.cancelQueries({ queryKey: resourceKey, exact: true }),
      queryClient.cancelQueries({ queryKey: searchesKey }),
      queryClient.cancelQueries(citationFilter),
    ]);
    if (!active.current || signal.aborted) return;
    queryClient.setQueryData<InfiniteData<KnowledgeResourcePage, string | null>>(
      knowledgeKeys.resources(organizationId, projectId),
      (current) => current === undefined ? current : {
        ...current,
        pages: current.pages.map((page) => ({
          ...page,
          items: page.items.filter((item) => item.id !== resource.id),
        })),
      },
    );
    queryClient.removeQueries({ queryKey: resourceKey, exact: true });
    queryClient.removeQueries(citationFilter);
    await queryClient.invalidateQueries({ queryKey: searchesKey, refetchType: "none" });
    if (!active.current || signal.aborted) return;
    setResourceDeletion((current) => ({
      revision: (current?.revision ?? 0) + 1,
      title: resource.title,
    }));
  }, [organizationId, projectId, queryClient, signal]);

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

      {resourceDeletion === null ? null : <p
        aria-label="资料删除结果"
        aria-live="polite"
        className="knowledge-resource-delete-notice"
        ref={deletionNotice}
        role="status"
        tabIndex={-1}
      >已删除资料：{resourceDeletion.title}</p>}

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

      {!accessUnavailable && resources.data !== undefined && capabilities?.canWrite === true ? (
        <KnowledgeUploadBatch
          key={`upload:${organizationId}:${projectId}`}
          organizationId={organizationId}
          projectId={projectId}
          csrfToken={csrfToken}
          sessionSignal={signal}
          onAccessUnavailable={onSearchAccessUnavailable}
        />
      ) : null}

      {!accessUnavailable && resources.data !== undefined ? (
        <KnowledgeSearch
          key={`${organizationId}:${projectId}`}
          organizationId={organizationId}
          projectId={projectId}
          csrfToken={csrfToken}
          sessionSignal={signal}
          onAccessUnavailable={onSearchAccessUnavailable}
          resourceDeletion={resourceDeletion}
        />
      ) : null}

      {!accessUnavailable && resources.data !== undefined && items.length === 0 ? (
        <div className="knowledge-state knowledge-state-empty">
          <BookOpenText aria-hidden="true" size={28} strokeWidth={1.8} />
          <div>
            <h2>还没有知识资料</h2>
            <p>当前项目暂时没有可显示的知识资料。</p>
          </div>
        </div>
      ) : null}

      {items.length > 0 ? (
        <KnowledgeResourceList
          organizationId={organizationId}
          projectId={projectId}
          csrfToken={csrfToken}
          canWrite={capabilities?.canWrite === true}
          actionsDisabled={resources.fetchStatus !== "idle" || resources.isError}
          sessionSignal={signal}
          items={items}
          hasNextPage={resources.hasNextPage}
          paginationError={resources.isFetchNextPageError ? resources.error : null}
          pending={resources.isFetchingNextPage}
          onLoadMore={() => void resources.fetchNextPage()}
          onResourceMissing={handleResourceMissing}
          onRetrySucceeded={handleRetrySucceeded}
          onDeleteSucceeded={handleDeleteSucceeded}
        />
      ) : null}
    </section>
  );
}

function KnowledgeResourceList({
  organizationId,
  projectId,
  csrfToken,
  canWrite,
  actionsDisabled,
  sessionSignal,
  items,
  hasNextPage,
  paginationError,
  pending,
  onLoadMore,
  onResourceMissing,
  onRetrySucceeded,
  onDeleteSucceeded,
}: {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  canWrite: boolean;
  actionsDisabled: boolean;
  sessionSignal: AbortSignal;
  items: KnowledgeResource[];
  hasNextPage: boolean;
  paginationError: unknown;
  pending: boolean;
  onLoadMore(): void;
  onResourceMissing(): void | Promise<void>;
  onRetrySucceeded(resource: KnowledgeResource): void | Promise<void>;
  onDeleteSucceeded(resource: KnowledgeResource): void | Promise<void>;
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
          <KnowledgeResourceRow key={resource.id} resource={resource}
            organizationId={organizationId} projectId={projectId}
            csrfToken={csrfToken} canWrite={canWrite} actionsDisabled={actionsDisabled}
            sessionSignal={sessionSignal} onResourceMissing={onResourceMissing}
            onRetrySucceeded={onRetrySucceeded} onDeleteSucceeded={onDeleteSucceeded} />
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

function KnowledgeResourceRow({ resource, organizationId, projectId, sessionSignal,
  csrfToken, canWrite, actionsDisabled, onResourceMissing, onRetrySucceeded,
  onDeleteSucceeded }: {
  resource: KnowledgeResource;
  organizationId: string;
  projectId: string;
  csrfToken: string;
  canWrite: boolean;
  actionsDisabled: boolean;
  sessionSignal: AbortSignal;
  onResourceMissing(): void | Promise<void>;
  onRetrySucceeded(resource: KnowledgeResource): void | Promise<void>;
  onDeleteSucceeded(resource: KnowledgeResource): void | Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const panelId = `knowledge-resource-detail-${resource.id}`;
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
          <button type="button" className="knowledge-resource-toggle"
            aria-expanded={expanded} aria-controls={panelId}
            onClick={() => {
              const key = knowledgeKeys.resource(organizationId, projectId, resource.id);
              if (expanded) {
                void queryClient.cancelQueries({ queryKey: key, exact: true }).finally(() => {
                  queryClient.removeQueries({ queryKey: key, exact: true });
                });
                setExpanded(false);
                return;
              }
              queryClient.removeQueries({ queryKey: key, exact: true });
              setExpanded(true);
            }}>
            {expanded ? "收起资料详情" : "查看资料详情"}
          </button>
        </div>
      </article>
      {expanded ? <KnowledgeResourceDetails id={panelId} organizationId={organizationId}
        projectId={projectId} resourceId={resource.id} csrfToken={csrfToken}
        canWrite={canWrite} actionsDisabled={actionsDisabled} sessionSignal={sessionSignal}
        onResourceMissing={onResourceMissing} onRetrySucceeded={onRetrySucceeded}
        onDeleteSucceeded={onDeleteSucceeded} /> : null}
    </li>
  );
}
