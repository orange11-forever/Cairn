import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { ArrowLeft, BookOpenText, CalendarDays, FileText, HardDrive, PackageOpen, Search, UploadCloud, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { ApiError } from "../api/errors.ts";
import type { KnowledgeCitation, KnowledgeResource, KnowledgeResourcePage } from "../api/knowledge.ts";
import { KnowledgeCitationContext } from "../components/knowledge/KnowledgeCitationContext.tsx";
import { KnowledgeSearch } from "../components/knowledge/KnowledgeSearch.tsx";
import { KnowledgeAnswers } from "../components/knowledge/KnowledgeAnswers.tsx";
import { KnowledgeResourceDetails } from "../components/knowledge/KnowledgeResourceDetails.tsx";
import { KnowledgeUploadBatch } from "../components/knowledge/KnowledgeUploadBatch.tsx";
import { WorkspaceHeader } from "../components/WorkspaceHeader.tsx";
import { formatCalendarDate } from "../lib/dateTime.ts";
import { formatKnowledgeMediaType } from "../lib/knowledgeSearch.ts";
import { formatBytes } from "../lib/validation.ts";
import { knowledgeKeys, useKnowledgeResourcesQuery } from "../queries/knowledge.ts";
import { useProjectQuery } from "../queries/projects.ts";
import { useSession } from "../session/SessionContext.tsx";

type ResourceStatus = NonNullable<KnowledgeResource["latestVersion"]>["status"];
type WorkbenchSelection =
  | { kind: "resource"; resourceId: string; title: string }
  | { kind: "citation"; citation: KnowledgeCitation }
  | null;
type MobilePane = "explorer" | "content" | "assistant";

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

function ProjectsLink() {
  return (
    <Link aria-label="返回项目" className="task-knowledge-link" to="/projects">
      <ArrowLeft aria-hidden="true" size={17} strokeWidth={1.8} />
      <span>返回项目</span>
    </Link>
  );
}

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
        actions={<ProjectsLink />}
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
  const project = useProjectQuery(organizationId, projectId, signal);
  const resources = useKnowledgeResourcesQuery(
    organizationId, projectId, signal, project.isSuccess && !project.isFetching,
  );
  const [selection, setSelection] = useState<WorkbenchSelection>(null);
  const [mobilePane, setMobilePane] = useState<MobilePane>("content");
  const [compact, setCompact] = useState(() => window.matchMedia?.("(max-width: 900px)").matches ?? window.innerWidth <= 900);
  const [uploadOpen, setUploadOpen] = useState(false);
  const selectionEpoch = useRef(0);
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
    const query = window.matchMedia?.("(max-width: 900px)");
    if (query === undefined) return;
    const update = () => setCompact(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
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
  const clearSelection = useCallback(async () => {
    const previous = selection;
    const epoch = ++selectionEpoch.current;
    setSelection(null);
    if (previous === null) return;
    const key = previous.kind === "resource"
      ? knowledgeKeys.resource(organizationId, projectId, previous.resourceId)
      : knowledgeKeys.citationContext(organizationId, projectId,
        previous.citation.resourceId, previous.citation.resourceVersionId,
        previous.citation.chunkId);
    await queryClient.cancelQueries({ queryKey: key, exact: true });
    if (epoch === selectionEpoch.current) queryClient.removeQueries({ queryKey: key, exact: true });
  }, [organizationId, projectId, queryClient, selection]);

  const openSelection = useCallback(async (next: NonNullable<WorkbenchSelection>) => {
    const epoch = ++selectionEpoch.current;
    const previous = selection;
    setSelection(null);
    if (previous !== null) {
      const oldKey = previous.kind === "resource"
        ? knowledgeKeys.resource(organizationId, projectId, previous.resourceId)
        : knowledgeKeys.citationContext(organizationId, projectId,
          previous.citation.resourceId, previous.citation.resourceVersionId,
          previous.citation.chunkId);
      await queryClient.cancelQueries({ queryKey: oldKey, exact: true });
      if (epoch !== selectionEpoch.current || signal.aborted) return;
      queryClient.removeQueries({ queryKey: oldKey, exact: true });
    }
    if (epoch !== selectionEpoch.current || signal.aborted) return;
    const key = next.kind === "resource"
      ? knowledgeKeys.resource(organizationId, projectId, next.resourceId)
      : knowledgeKeys.citationContext(organizationId, projectId,
        next.citation.resourceId, next.citation.resourceVersionId,
        next.citation.chunkId);
    queryClient.removeQueries({ queryKey: key, exact: true });
    setSelection(next);
    setMobilePane("content");
  }, [organizationId, projectId, queryClient, selection, signal]);
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
    if ((selection?.kind === "resource" && selection.resourceId === resource.id) ||
      (selection?.kind === "citation" && selection.citation.resourceId === resource.id)) {
      selectionEpoch.current += 1;
      setSelection(null);
    }
    await queryClient.invalidateQueries({ queryKey: searchesKey, refetchType: "none" });
    if (!active.current || signal.aborted) return;
    setResourceDeletion((current) => ({
      revision: (current?.revision ?? 0) + 1,
      title: resource.title,
    }));
  }, [organizationId, projectId, queryClient, selection, signal]);

  if (project.isPending || project.isFetching) return (
    <section aria-busy="true" aria-label="项目知识工作区" className="knowledge-page">
      <p role="status">正在确认项目访问权限…</p>
    </section>
  );
  if (project.isError) return (
    <section aria-label="项目知识工作区" className="knowledge-page">
      <WorkspaceHeader id="knowledge-page-title" eyebrow="项目范围知识"
        title="项目知识" description="当前项目暂时无法打开。" actions={<ProjectsLink />} />
      <div className="knowledge-state knowledge-state-error">
        <p role="alert">{errorMessage(project.error)}</p>
        {project.error instanceof ApiError && project.error.traceId !== null ? (
          <p>请求编号：{project.error.traceId}</p>
        ) : null}
        {project.error instanceof ApiError && project.error.retryable ? (
          <button type="button" onClick={() => void project.refetch()}>重新加载项目</button>
        ) : null}
      </div>
    </section>
  );

  return (
    <section
      aria-busy={resources.isPending ? "true" : undefined}
      aria-label="项目知识工作区"
      className="knowledge-page"
    >
      <WorkspaceHeader
        id="knowledge-page-title"
        eyebrow="当前项目"
        title={project.data.name}
        description="项目知识"
        actions={<ProjectsLink />}
      />

      <nav aria-label="工作台分区" className="knowledge-mobile-panes">
        <button type="button" aria-pressed={mobilePane === "explorer"} onClick={() => setMobilePane("explorer")}>资料</button>
        <button type="button" aria-pressed={mobilePane === "content"} onClick={() => setMobilePane("content")}>内容</button>
        <button type="button" aria-pressed={mobilePane === "assistant"} onClick={() => setMobilePane("assistant")}>岑宁</button>
      </nav>

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

      {!accessUnavailable && resources.data !== undefined ? <div className="knowledge-workbench" data-mobile-pane={mobilePane}>
        <aside className="knowledge-explorer" aria-label="项目资料" hidden={compact && mobilePane !== "explorer"}>
          <div className="knowledge-explorer-heading">
            <div><span>项目资料</span><h2>{project.data.name}</h2></div>
            {capabilities?.canWrite === true ? <button type="button"
              aria-label="上传资料" aria-expanded={uploadOpen}
              onClick={() => setUploadOpen((value) => !value)}>
              <UploadCloud aria-hidden="true" size={18} />
            </button> : null}
          </div>
          {capabilities?.canWrite === true ? <div className="knowledge-explorer-upload">
            <KnowledgeUploadBatch key={`upload:${organizationId}:${projectId}`}
              organizationId={organizationId} projectId={projectId} csrfToken={csrfToken}
              sessionSignal={signal} onAccessUnavailable={onSearchAccessUnavailable}
              collapsible open={uploadOpen} onToggle={() => setUploadOpen((value) => !value)} />
          </div> : null}
          {items.length === 0 ? <div className="knowledge-state knowledge-state-empty">
            <BookOpenText aria-hidden="true" size={28} strokeWidth={1.8} />
            <div><h2>还没有知识资料</h2>
              <p>{capabilities?.canWrite ? "上传资料后可在此检索。" : "当前项目暂时没有可显示的知识资料。"}</p></div>
          </div> : null}
          {items.length > 0 ? <KnowledgeResourceList
          items={items}
          hasNextPage={resources.hasNextPage}
          paginationError={resources.isFetchNextPageError ? resources.error : null}
          pending={resources.isFetchingNextPage}
          onLoadMore={() => void resources.fetchNextPage()}
          selectedResourceId={selection?.kind === "resource" ? selection.resourceId : null}
          onOpenResource={(resource) => selection?.kind === "resource" &&
            selection.resourceId === resource.id
            ? void clearSelection()
            : void openSelection({ kind: "resource", resourceId: resource.id, title: resource.title })}
        /> : null}
        </aside>
        <section className="knowledge-content" aria-label="知识内容" hidden={compact && mobilePane !== "content"}>
          <div className="knowledge-content-tabs">
            <button type="button" aria-current={selection === null ? "page" : undefined}
              onClick={() => void clearSelection()}><Search aria-hidden="true" size={17} />搜索</button>
            {selection !== null ? <span>{selection.kind === "resource" ? selection.title : `${selection.citation.title} · 引用上下文`}</span> : null}
            {selection !== null ? <button type="button" aria-label="关闭当前内容"
              onClick={() => void clearSelection()}><X aria-hidden="true" size={18} /></button> : null}
          </div>
          <div hidden={selection !== null}>
            <KnowledgeSearch key={`${organizationId}:${projectId}`}
              organizationId={organizationId} projectId={projectId} csrfToken={csrfToken}
              sessionSignal={signal} onAccessUnavailable={onSearchAccessUnavailable}
              resourceDeletion={resourceDeletion}
              onOpenCitation={(citation) => void openSelection({ kind: "citation", citation })} />
          </div>
          {selection?.kind === "resource" ? <KnowledgeResourceDetails
            key={`selected:${selection.resourceId}`} id={`knowledge-center-resource-${selection.resourceId}`}
            organizationId={organizationId} projectId={projectId}
            resourceId={selection.resourceId} csrfToken={csrfToken}
            canWrite={capabilities?.canWrite === true}
            actionsDisabled={resources.fetchStatus !== "idle" || resources.isError}
            sessionSignal={signal} onResourceMissing={handleResourceMissing}
            onRetrySucceeded={handleRetrySucceeded} onDeleteSucceeded={handleDeleteSucceeded} /> : null}
          {selection?.kind === "citation" ? <KnowledgeCitationContext
            key={`selected:${selection.citation.resourceVersionId}:${selection.citation.chunkId}`}
            id="knowledge-center-citation" organizationId={organizationId}
            projectId={projectId} citation={selection.citation} sessionSignal={signal} /> : null}
        </section>
        <aside className="knowledge-assistant" aria-label="岑宁问答面板" hidden={compact && mobilePane !== "assistant"}>
          <KnowledgeAnswers key={`answers:${organizationId}:${projectId}`}
            organizationId={organizationId} projectId={projectId} csrfToken={csrfToken}
            sessionSignal={signal} onAccessUnavailable={onSearchAccessUnavailable}
            resourceDeletion={resourceDeletion} docked
            onOpenCitation={(citation) => void openSelection({ kind: "citation", citation })} />
        </aside>
      </div> : null}
      <footer className="knowledge-statusbar" aria-label="工作台状态">
        <span>{project.data.name}</span>
        {capabilities === undefined ? (
          <span>{resources.isPending ? "正在读取资料" : "资料暂不可用"}</span>
        ) : (
          <span><strong>{capabilities.canWrite ? "可维护资料" : "只读访问"}</strong>
            {` · 已加载 ${items.length} 项资料`}</span>
        )}
      </footer>
    </section>
  );
}

function KnowledgeResourceList({
  items,
  hasNextPage,
  paginationError,
  pending,
  onLoadMore,
  selectedResourceId,
  onOpenResource,
}: {
  items: KnowledgeResource[];
  hasNextPage: boolean;
  paginationError: unknown;
  pending: boolean;
  onLoadMore(): void;
  selectedResourceId: string | null;
  onOpenResource(resource: KnowledgeResource): void;
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
            selected={selectedResourceId === resource.id}
            onOpen={() => onOpenResource(resource)} />
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

function KnowledgeResourceRow({ resource, selected, onOpen }: {
  resource: KnowledgeResource;
  selected: boolean;
  onOpen(): void;
}) {
  const version = resource.latestVersion;
  const status = version?.status ?? "waiting";
  const statusLabel = version === null ? "等待版本" : RESOURCE_STATUS_LABELS[version.status];
  return (
    <li className="knowledge-resource" data-status={status} data-selected={selected || undefined}>
      <button type="button" className="knowledge-resource-select"
        aria-label={`${selected ? "收起" : "查看"}${resource.title}资料详情`}
        aria-expanded={selected} aria-controls={`knowledge-center-resource-${resource.id}`}
        onClick={onOpen}>
        <FileText aria-hidden="true" className="knowledge-resource-icon" size={20} strokeWidth={1.7} />
        <span className="knowledge-resource-content">
          <span className="knowledge-resource-title-line">
            <strong>{resource.title}</strong>
            <span className="knowledge-resource-status" data-status={status}>{statusLabel}</span>
          </span>
          <span className="knowledge-resource-metadata">
            {version === null ? (
              <>
                <span><FileText aria-hidden="true" size={15} />文件类型待生成</span>
                <span><HardDrive aria-hidden="true" size={15} />文件大小待生成</span>
                {resource.sourceType === "zip_entry" ? (
                  <span><PackageOpen aria-hidden="true" size={15} />ZIP 内文件</span>
                ) : null}
              </>
            ) : (
              <>
                <span title={version.mediaType}><FileText aria-hidden="true" size={15} />
                  {formatKnowledgeMediaType(version.mediaType)}</span>
                <span><HardDrive aria-hidden="true" size={15} />{formatBytes(version.sizeBytes)}</span>
              </>
            )}
            <time dateTime={resource.updatedAt}><CalendarDays aria-hidden="true" size={15} />
              {formatCalendarDate(resource.updatedAt, UPDATED_DATE_FORMAT)}</time>
          </span>
        </span>
      </button>
    </li>
  );
}
