import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { ArrowLeft, BookOpenText, CalendarDays, FileText, HardDrive, PackageOpen, Search, UploadCloud, X, PanelLeft, PanelRight, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useParams, useSearchParams, useLocation } from "react-router-dom";

import { ApiError } from "../api/errors.ts";
import type { KnowledgeResource, KnowledgeResourcePage } from "../api/knowledge.ts";
import { type KnowledgeCitationReference } from "../components/knowledge/KnowledgeCitationContext.tsx";
import { KnowledgeSearch } from "../components/knowledge/KnowledgeSearch.tsx";
import { KnowledgeAnswers } from "../components/knowledge/KnowledgeAnswers.tsx";
import { KnowledgeDocument } from "../components/knowledge/KnowledgeDocument.tsx";
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
  | { kind: "citation"; citation: KnowledgeCitationReference }
  | null;
type ContentTab = NonNullable<WorkbenchSelection>;
function tabId(tab: ContentTab): string { return tab.kind === "resource" ? `resource:${tab.resourceId}` : `citation:${tab.citation.resourceVersionId}:${tab.citation.chunkId}`; }
function tabTitle(tab: ContentTab): string { return tab.kind === "resource" ? tab.title : `${tab.citation.title} · 引用上下文`; }
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
      canManageSources={session.identity.membership.role === "owner" || session.identity.membership.role === "admin"}
    />
  );
}

function KnowledgeWorkspace({
  organizationId,
  projectId,
  csrfToken,
  signal,
  canManageSources,
}: {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  signal: AbortSignal;
  canManageSources: boolean;
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
      canManageSources={canManageSources}
      onSearchAccessUnavailable={handleSearchAccessUnavailable}
    />
  );
}

function KnowledgeAccessUnavailable({ error }: { error: ApiError }) {
  return (
    <section aria-label="项目知识工作区" className="knowledge-page">
      <WorkspaceHeader
        id="knowledge-page-title"
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
  canManageSources,
  onSearchAccessUnavailable,
}: {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  signal: AbortSignal;
  canManageSources: boolean;
  onSearchAccessUnavailable(error: ApiError): void;
}) {
  const queryClient = useQueryClient();
  const project = useProjectQuery(organizationId, projectId, signal);
  const resources = useKnowledgeResourcesQuery(
    organizationId, projectId, signal, project.isSuccess && !project.isFetching,
  );
  useEffect(() => () => {
    const privateContent = {
      predicate: ({ queryKey }: { queryKey: readonly unknown[] }) =>
        queryKey[0] === "project-knowledge" && queryKey[1] === organizationId &&
        queryKey[2] === projectId && ["resource", "citation-context", "content", "search"].includes(String(queryKey[3])),
    };
    void queryClient.cancelQueries(privateContent);
    queryClient.removeQueries(privateContent);
  }, [organizationId, projectId, queryClient]);
  const [selection, setSelection] = useState<WorkbenchSelection>(null);
  const [tabs, setTabs] = useState<ContentTab[]>([]);
  const [searchTabOpen, setSearchTabOpen] = useState(true);
  const [explorerOpen, setExplorerOpen] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [searchParams] = useSearchParams();
  const location = useLocation();
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
    void queryClient.cancelQueries({ queryKey: [...knowledgeKeys.project(organizationId, projectId), "content"] });
    queryClient.removeQueries({ queryKey: [...knowledgeKeys.project(organizationId, projectId), "content"] });
    setSearchTabOpen(true);
    if (previous === null) return;
    const key = previous.kind === "resource"
      ? knowledgeKeys.resource(organizationId, projectId, previous.resourceId)
      : knowledgeKeys.citationContext(organizationId, projectId,
        previous.citation.resourceId, previous.citation.resourceVersionId,
        previous.citation.chunkId);
    await queryClient.cancelQueries({ queryKey: key, exact: true });
    if (epoch === selectionEpoch.current) queryClient.removeQueries({ queryKey: key, exact: true });
  }, [organizationId, projectId, queryClient, selection]);

  const openSelection = useCallback(async (incoming: NonNullable<WorkbenchSelection>) => {
    // Retain references only: search excerpts and other result fields belong to the search controller.
    const next: ContentTab = incoming.kind === "citation" ? {
      kind: "citation",
      citation: {
        resourceId: incoming.citation.resourceId,
        resourceVersionId: incoming.citation.resourceVersionId,
        chunkId: incoming.citation.chunkId,
        title: incoming.citation.title,
      },
    } : incoming;
    const epoch = ++selectionEpoch.current;
    const previous = selection;
    setSelection(null);
    await queryClient.cancelQueries({ queryKey: [...knowledgeKeys.project(organizationId, projectId), "content"] });
    queryClient.removeQueries({ queryKey: [...knowledgeKeys.project(organizationId, projectId), "content"] });
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
    setTabs(current => current.some(tab => tabId(tab) === tabId(next)) ? current : [...current, next]);
    setSelection(next);
    setMobilePane("content");
  }, [organizationId, projectId, queryClient, selection, signal]);
  function restoreTabFocus(id: string) {
    requestAnimationFrame(() => {
      // A delayed paint must not steal focus after the user starts another action.
      if (!active.current || signal.aborted || document.activeElement !== document.body) return;
      document.getElementById(id)?.focus();
    });
  }
  async function closeTab(tab: ContentTab) {
    const remaining = tabs.filter(entry => tabId(entry) !== tabId(tab));
    setTabs(remaining);
    let focusId = selection === null ? "knowledge-search-tab" : `knowledge-tab-${tabId(selection)}`;
    if (selection !== null && tabId(selection) === tabId(tab)) {
      const next = remaining[remaining.length - 1];
      if (next === undefined) { await clearSelection(); focusId = "knowledge-search-tab"; }
      else { await openSelection(next); focusId = `knowledge-tab-${tabId(next)}`; }
    }
    restoreTabFocus(focusId);
  }
  async function closeSearchTab() {
    setSearchTabOpen(false);
    void queryClient.cancelQueries({ queryKey: knowledgeKeys.searches(organizationId, projectId) });
    queryClient.removeQueries({ queryKey: knowledgeKeys.searches(organizationId, projectId) });
    if (selection === null) {
      const next = tabs[tabs.length - 1];
      if (next !== undefined) { await openSelection(next); restoreTabFocus(`knowledge-tab-${tabId(next)}`); }
    }
  }
  useEffect(() => {
    if (searchParams.get("view") === "search") {
      void clearSelection();
      setMobilePane("content");
    }
  }, [searchParams, location.key]);
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
        ["citation-context", "content"].includes(String(queryKey[3])) &&
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
    setTabs(current => current.filter(tab => (tab.kind === "resource" ? tab.resourceId : tab.citation.resourceId) !== resource.id));
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
      <WorkspaceHeader id="knowledge-page-title" title="项目知识" description="当前项目暂时无法打开。" actions={<ProjectsLink />} />
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
      <h1 id="knowledge-page-title" className="workbench-sr-only">{project.data.name}</h1>
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

      {!accessUnavailable && resources.data !== undefined ? <div className="knowledge-workbench" data-mobile-pane={mobilePane} data-explorer-open={compact || explorerOpen} data-assistant-open={compact || assistantOpen}>
        <aside className="knowledge-explorer" aria-label="项目资料" hidden={compact ? mobilePane !== "explorer" : !explorerOpen}>
          <div className="knowledge-explorer-heading">
            <h2>项目资料</h2>
            {capabilities?.canWrite === true ? <button type="button"
              aria-label="上传资料" aria-expanded={uploadOpen}
              onClick={() => setUploadOpen((value) => !value)}>
              <UploadCloud aria-hidden="true" size={18} />
            </button> : null}
          </div>
          <p className="knowledge-explorer-project" title={project.data.name}>{project.data.name}</p>
          {canManageSources ? <Link className="knowledge-sources-entry" aria-label="打开来源与同步" to={`/projects/${projectId}/knowledge/sources`}><RefreshCw size={15} aria-hidden="true" />来源与同步</Link> : null}
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
          selectedResourceId={selection?.kind === "resource" ? selection.resourceId : selection?.kind === "citation" ? selection.citation.resourceId : null}
          onOpenResource={(resource) => void openSelection({ kind: "resource", resourceId: resource.id, title: resource.title })}
        /> : null}
        </aside>
        <section className="knowledge-content" aria-label="知识内容" hidden={compact && mobilePane !== "content"}>
          <div className="knowledge-content-tabs" role="tablist" aria-label="内容标签" onKeyDown={event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || (event.target as HTMLElement).getAttribute("role") !== "tab") return;
            const controls = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("[role=tab]"));
            const index = controls.indexOf(event.target as HTMLButtonElement);
            const next = event.key === "Home" ? 0 : event.key === "End" ? controls.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + controls.length) % controls.length;
            event.preventDefault(); controls[next]?.focus(); controls[next]?.click();
          }}>
            {searchTabOpen ? <div className="knowledge-tab" data-active={selection === null}>
              <button type="button" role="tab" tabIndex={selection === null ? 0 : -1} aria-selected={selection === null} id="knowledge-search-tab" aria-controls="knowledge-active-content"
                onClick={() => void clearSelection()}><Search aria-hidden="true" size={17} />搜索</button>
              <button type="button" className="knowledge-tab-close" aria-label="关闭搜索标签" onClick={() => void closeSearchTab()}><X size={15} aria-hidden="true" /></button>
            </div> : null}
            {tabs.map(tab => <div className="knowledge-tab" key={tabId(tab)} data-active={selection !== null && tabId(selection) === tabId(tab)}>
              <button type="button" role="tab" id={`knowledge-tab-${tabId(tab)}`} aria-controls="knowledge-active-content" title={tabTitle(tab)}
                tabIndex={selection !== null && tabId(selection) === tabId(tab) ? 0 : -1} aria-selected={selection !== null && tabId(selection) === tabId(tab)} onClick={() => void openSelection(tab)}>
                <FileText size={16} aria-hidden="true" /><span>{tabTitle(tab)}</span>
              </button>
              <button type="button" className="knowledge-tab-close" aria-label={`关闭${tabTitle(tab)}标签`} onClick={() => void closeTab(tab)}><X size={15} aria-hidden="true" /></button>
            </div>)}
          </div>
          <div className="knowledge-reader-toolbar">
            <span className="knowledge-breadcrumb"><BookOpenText size={15} aria-hidden="true" />项目资料<span aria-hidden="true">/</span><span>{selection === null ? searchTabOpen ? "搜索" : "未打开资料" : tabTitle(selection)}</span></span>
            <div className="knowledge-pane-controls">
              <button type="button" aria-label={explorerOpen ? "收起资料栏" : "展开资料栏"} aria-pressed={explorerOpen} onClick={() => setExplorerOpen(value => !value)}><PanelLeft size={18} aria-hidden="true" /></button>
              <button type="button" aria-label={assistantOpen ? "收起助手" : "展开助手"} aria-pressed={assistantOpen} onClick={() => setAssistantOpen(value => !value)}><PanelRight size={18} aria-hidden="true" /></button>
            </div>
          </div>
          <div className="knowledge-reader-scroll" id="knowledge-active-content" role="tabpanel" aria-labelledby={selection === null ? searchTabOpen ? "knowledge-search-tab" : "knowledge-empty-title" : `knowledge-tab-${tabId(selection)}`}>
          {selection === null && !searchTabOpen ? <div className="knowledge-center-empty"><BookOpenText size={32} aria-hidden="true" /><h2 id="knowledge-empty-title">打开一份项目资料</h2><p>从资料栏选择文件，或搜索项目知识以核对引用。</p><button type="button" onClick={() => void clearSelection()}><Search size={17} aria-hidden="true" />搜索项目资料</button></div> : null}
          {selection === null && searchTabOpen ? <KnowledgeSearch key={`${organizationId}:${projectId}`}
              organizationId={organizationId} projectId={projectId} csrfToken={csrfToken}
              sessionSignal={signal} onAccessUnavailable={onSearchAccessUnavailable}
              resourceDeletion={resourceDeletion}
              onOpenCitation={(citation) => void openSelection({ kind: "citation", citation })} /> : null}
          {selection?.kind === "resource" ? <KnowledgeDocument
            key={`selected:${selection.resourceId}`} id={`knowledge-center-resource-${selection.resourceId}`}
            organizationId={organizationId} projectId={projectId}
            resourceId={selection.resourceId} title={selection.title} csrfToken={csrfToken}
            unsupportedFormat={items.some(item => item.id === selection.resourceId && item.latestVersion !== null && !["text/markdown", "text/plain"].includes(item.latestVersion.mediaType))}
            canWrite={capabilities?.canWrite === true}
            actionsDisabled={resources.fetchStatus !== "idle" || resources.isError}
            sessionSignal={signal} onResourceMissing={handleResourceMissing}
            onRetrySucceeded={handleRetrySucceeded} onDeleteSucceeded={handleDeleteSucceeded} /> : null}
          {selection?.kind === "citation" ? <KnowledgeDocument
            key={`selected:${selection.citation.resourceVersionId}:${selection.citation.chunkId}`}
            id="knowledge-center-citation" organizationId={organizationId}
            projectId={projectId} citation={selection.citation} sessionSignal={signal}
            resourceId={selection.citation.resourceId} title={selection.citation.title}
            unsupportedFormat={items.some(item => item.id === selection.citation.resourceId && item.latestVersion !== null && !["text/markdown", "text/plain"].includes(item.latestVersion.mediaType))}
            csrfToken={csrfToken} canWrite={capabilities?.canWrite === true}
            actionsDisabled={resources.fetchStatus !== "idle" || resources.isError}
            onResourceMissing={handleResourceMissing} onRetrySucceeded={handleRetrySucceeded}
            onDeleteSucceeded={handleDeleteSucceeded} /> : null}
          </div>
        </section>
        <aside className="knowledge-assistant" aria-label="岑宁问答面板" hidden={compact ? mobilePane !== "assistant" : !assistantOpen}>
          <KnowledgeAnswers key={`answers:${organizationId}:${projectId}`}
            organizationId={organizationId} projectId={projectId} csrfToken={csrfToken}
            sessionSignal={signal} onAccessUnavailable={onSearchAccessUnavailable}
            resourceDeletion={resourceDeletion} docked projectName={project.data.name}
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
        aria-label={`${"查看"}${resource.title}资料详情`}
        aria-pressed={selected} aria-controls={`knowledge-center-resource-${resource.id}`}
        onClick={onOpen}>
        <FileText aria-hidden="true" className="knowledge-resource-icon" size={20} strokeWidth={1.7} />
        <span className="knowledge-resource-content">
          <span className="knowledge-resource-title-line">
            <strong>{resource.title}</strong>
            <span className="knowledge-resource-status" data-status={status} title={statusLabel}><span className="workbench-sr-only">{statusLabel}</span></span>
          </span>
          <span className="knowledge-resource-metadata">
            {resource.sourceType === "feishu_document" ? <span className="knowledge-feishu-mark">飞书</span> : null}
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
