import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { ApiError } from "../api/errors.ts";
import {
  createFeishuSource, disableFeishuSource, patchFeishuSource, queueFeishuSync,
  type FeishuSourceCreate, type FeishuSourcePatch, type KnowledgeSource,
} from "../api/knowledgeSources.ts";
import { FeishuSourceForm } from "../components/knowledge/FeishuSourceForm.tsx";
import { FeishuSourceList } from "../components/knowledge/FeishuSourceList.tsx";
import { FeishuSyncHistory } from "../components/knowledge/FeishuSyncHistory.tsx";
import { WorkspaceHeader } from "../components/WorkspaceHeader.tsx";
import { intervalLabel } from "../lib/feishuDocument.ts";
import { clearProjectKnowledge, clearProjectKnowledgeContent, sourceKeys, useFeishuHistory, useFeishuSources,
  useFeishuSync, usePrivatePageActive } from "../queries/knowledgeSources.ts";
import { useProjectQuery } from "../queries/projects.ts";
import { useSession } from "../session/SessionContext.tsx";

type Action =
  | { kind: "create"; body: FeishuSourceCreate }
  | { kind: "patch"; sourceId: string; body: FeishuSourcePatch }
  | { kind: "disable"; sourceId: string }
  | { kind: "sync"; sourceId: string };

type Mode = "view" | "create" | "edit";
const ACCESS: Record<KnowledgeSource["accessState"], string> = {
  unverified: "待验证", available: "可访问", access_denied: "无权限", not_found: "文档不存在",
};
const showDate = (value: string | null) => value === null ? "尚无" : new Date(value).toLocaleString("zh-CN");
const displayedError = (value: unknown) => value instanceof Error ? value.message : "来源暂时无法加载，请重试";

export function KnowledgeSourcesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { session } = useSession();
  if (projectId === undefined) return <Navigate to="/projects" replace />;
  if (session === null) return null;
  const role = session.identity.membership.role;
  if (role !== "owner" && role !== "admin") {
    return <section aria-label="飞书来源管理" className="feishu-page">
      <WorkspaceHeader id="feishu-page-title" title="飞书来源" description="当前账号无法管理项目来源。"
        actions={<Link className="task-knowledge-link" to={`/projects/${projectId}/knowledge`}>
          <ArrowLeft aria-hidden="true" size={17} />返回项目知识</Link>} />
      <p role="status" className="feishu-access-message">仅组织管理员可以管理飞书来源。</p>
    </section>;
  }
  return <KnowledgeSourcesWorkspace
    key={`${session.generation}:${session.identity.organization.id}:${projectId}`}
    organizationId={session.identity.organization.id} projectId={projectId}
    csrfToken={session.identity.csrfToken} sessionSignal={session.signal} />;
}

function KnowledgeSourcesWorkspace({ organizationId, projectId, csrfToken, sessionSignal }: {
  organizationId: string; projectId: string; csrfToken: string; sessionSignal: AbortSignal;
}) {
  const queryClient = useQueryClient();
  const active = usePrivatePageActive(sessionSignal);
  const project = useProjectQuery(organizationId, projectId, sessionSignal);
  const [accessLost, setAccessLost] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("view");
  const [confirmDisable, setConfirmDisable] = useState(false);
  const [restoreShared, setRestoreShared] = useState(false);
  const [operationError, setOperationError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);
  const actionController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const sources = useFeishuSources(organizationId, projectId, sessionSignal,
    active && !accessLost && project.isSuccess && !project.isFetching);
  const sourceAccessLost = sources.error instanceof ApiError && sources.error.status === 404;
  const listAuthorized = active && !accessLost && !sourceAccessLost && sources.isFetchedAfterMount;
  const items = listAuthorized
    ? (sources.data?.pages.flatMap((page) => page.items) ?? []) : [];
  const source = items.find((entry) => entry.id === selectedId) ?? null;
  const history = useFeishuHistory(organizationId, projectId, source?.id ?? null, sessionSignal,
    active && !accessLost && mode === "view" && source !== null);
  const historyAccessLost = history.error instanceof ApiError && history.error.status === 404;
  const historyItems = active && !accessLost && !historyAccessLost && history.isFetchedAfterMount
    ? (history.data?.pages.flatMap((page) => page.items) ?? []) : [];
  const newest = historyItems[0];
  const tracked = useFeishuSync(organizationId, projectId, source?.id ?? null,
    newest?.id ?? null, sessionSignal, active && !accessLost && mode === "view");
  const syncAccessLost = tracked.error instanceof ApiError && tracked.error.status === 404;
  const syncItems = !tracked.isFetchedAfterMount || tracked.data === undefined ? historyItems : historyItems.map((entry) =>
    entry.id === tracked.data?.id ? tracked.data : entry);

  const clearPrivate = useCallback(() => clearProjectKnowledge(queryClient, organizationId, projectId),
    [queryClient, organizationId, projectId]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; actionController.current?.abort(); };
  }, []);
  useEffect(() => {
    if (active) return;
    actionController.current?.abort();
    setOperationError(null);
    setNotice(null);
    void clearPrivate();
  }, [active, clearPrivate]);
  const deny = useCallback(() => {
    setAccessLost(true);
    setSelectedId(null);
    setMode("view");
    setOperationError(null);
    setNotice(null);
    actionController.current?.abort();
    void clearPrivate();
  }, [clearPrivate]);
  useEffect(() => {
    if (sources.error instanceof ApiError && sources.error.status === 404) deny();
  }, [sources.error, deny]);
  useEffect(() => {
    if (project.error instanceof ApiError && project.error.status === 404) deny();
  }, [project.error, deny]);
  useEffect(() => {
    if (!active || accessLost || sourceAccessLost || sources.data === undefined) return;
    // Authorization may have changed during a scheduled check while this route was open.
    void clearProjectKnowledgeContent(queryClient, organizationId, projectId);
  }, [active, accessLost, sourceAccessLost, sources.dataUpdatedAt, organizationId, projectId, queryClient]);
  useEffect(() => {
    if (history.error instanceof ApiError && history.error.status === 404) deny();
    if (tracked.error instanceof ApiError && tracked.error.status === 404) deny();
  }, [history.error, tracked.error, deny]);
  useEffect(() => {
    if (!active || tracked.data === undefined || source === null) return;
    // A completed sync may have observed a revoked or deleted upstream document.
    // Clear cached search, citations and answers before showing the updated state.
    void clearProjectKnowledgeContent(queryClient, organizationId, projectId);
    void queryClient.invalidateQueries({ queryKey: sourceKeys.list(organizationId, projectId) });
    void queryClient.invalidateQueries({ queryKey: sourceKeys.history(organizationId, projectId, source.id) });
  }, [active, tracked.data?.status, tracked.data?.resourceStatus, tracked.data?.failureCode,
    source?.id, organizationId, projectId, queryClient]);

  const mutation = useMutation({
    networkMode: "always",
    retry: false,
    mutationFn: async (action: Action) => {
      if (!navigator.onLine || document.visibilityState !== "visible" || sessionSignal.aborted) {
        throw new ApiError("aborted", "当前离线或页面未显示，请恢复后手动重试");
      }
      actionController.current?.abort();
      const controller = new AbortController();
      actionController.current = controller;
      const signal = AbortSignal.any([controller.signal, sessionSignal]);
      if (action.kind === "create") return createFeishuSource({ projectId, body: action.body, csrfToken, signal });
      if (action.kind === "patch") return patchFeishuSource({ projectId, sourceId: action.sourceId,
        body: action.body, csrfToken, signal });
      if (action.kind === "disable") return disableFeishuSource({ projectId, sourceId: action.sourceId,
        csrfToken, signal });
      return queueFeishuSync({ projectId, sourceId: action.sourceId, csrfToken, signal });
    },
  });
  const run = useCallback(async (action: Action) => {
    setOperationError(null); setNotice(null);
    try {
      const result = await mutation.mutateAsync(action);
      if (!mounted.current || sessionSignal.aborted || !active) return;
      await clearPrivate();
      if (!mounted.current || sessionSignal.aborted || document.visibilityState !== "visible" || !navigator.onLine) return;
      if (action.kind === "create") {
        setSelectedId((result as KnowledgeSource).id);
        setNotice("来源已登记。现在可以手动同步文档。");
      } else if (action.kind === "patch") {
        setNotice(action.body.status === "configured"
          ? "来源已恢复。请手动同步以重新验证访问权限。" : "来源设置已保存。");
        setRestoreShared(false);
      } else if (action.kind === "disable") {
        setNotice("来源已停用，项目成员无法再读取其已保存内容。");
        setConfirmDisable(false);
      } else {
        setNotice("同步已加入队列。快照完成后仍需等待索引才能检索。");
      }
      setMode("view");
      void sources.refetch();
      if (action.kind === "sync") void history.refetch();
    } catch (error) {
      if (!mounted.current || sessionSignal.aborted || !active) return;
      const apiError = error instanceof ApiError ? error : new ApiError("network", "操作失败，请手动重试");
      if (apiError.kind === "aborted") return;
      if (apiError.status === 404) { deny(); return; }
      setOperationError(apiError);
      if (apiError.status === 409) {
        void sources.refetch();
        if (source !== null) void history.refetch();
      }
    }
  }, [active, clearPrivate, deny, history, mutation, sessionSignal, source, sources]);

  const back = <Link className="task-knowledge-link" to={`/projects/${projectId}/knowledge`}>
    <ArrowLeft aria-hidden="true" size={17} strokeWidth={1.8} />返回项目知识</Link>;
  if (project.isPending || project.isFetching || !active) return <section className="feishu-page" aria-busy="true">
    <p role="status">{active ? "正在确认项目访问权限…" : "页面暂停显示。恢复网络并返回此页面后重新检查权限。"}</p>
  </section>;
  if (project.isError || accessLost || sourceAccessLost || historyAccessLost || syncAccessLost) return <section className="feishu-page" aria-label="飞书来源管理">
    <WorkspaceHeader id="feishu-page-title" title="飞书来源" description="当前项目的来源管理暂不可用。" actions={back} />
    <div className="feishu-access-message"><p role="alert">{accessLost || sourceAccessLost || historyAccessLost || syncAccessLost ? "项目来源不可用或你已失去管理权限。" : displayedError(project.error)}</p>
      {!accessLost && !sourceAccessLost && !historyAccessLost && !syncAccessLost && project.error instanceof ApiError && project.error.retryable ?
        <button type="button" onClick={() => void project.refetch()}>重新加载项目</button> : null}</div>
  </section>;

  return <section className="feishu-page" aria-label="飞书来源管理">
    <WorkspaceHeader id="feishu-page-title" title="飞书来源"
      description={`${project.data.name} · 登记文档、安排同步并查看读取结果。`}
      actions={<>{back}<button type="button" className="primary-btn" onClick={() => {
        setMode("create"); setMobileDetail(true); setConfirmDisable(false); setOperationError(null);
      }}><Plus aria-hidden="true" size={17} />添加来源</button></>} />
    {notice ? <p className="feishu-notice" role="status">{notice}</p> : null}
    {!listAuthorized && !sources.isError ? <p role="status" className="feishu-access-message">正在加载飞书来源…</p> : null}
    {sources.isError ? <div className="feishu-access-message"><p role="alert">{displayedError(sources.error)}</p>
      <button type="button" onClick={() => void sources.refetch()}>重新加载来源</button></div> : null}
    {sources.data && listAuthorized ? <div className="feishu-layout" data-mobile-detail={mobileDetail}>
      <FeishuSourceList items={items} selectedId={selectedId} hasNextPage={sources.hasNextPage}
        loadingMore={sources.isFetchingNextPage} onLoadMore={() => void sources.fetchNextPage()}
        onSelect={(id) => { setSelectedId(id); setMode("view"); setMobileDetail(true); setRestoreShared(false);
          setConfirmDisable(false); setOperationError(null); setNotice(null); }}
        onAdd={() => { setMode("create"); setMobileDetail(true); }} />
      <section className="feishu-detail" aria-label="来源详情">
        <button type="button" className="feishu-mobile-back" onClick={() => setMobileDetail(false)}>返回来源列表</button>
        {mode !== "view" ? <FeishuSourceForm source={mode === "edit" ? source : null}
          pending={mutation.isPending} error={operationError?.message ?? null}
          onCancel={() => { setMode("view"); setOperationError(null); }}
          onCreate={(body) => void run({ kind: "create", body })}
          onUpdate={(body) => { if (source) void run({ kind: "patch", sourceId: source.id, body }); }} /> :
        source === null ? <div className="feishu-empty"><h2>选择一个来源</h2>
          <p>查看文档状态、同步设置和历史记录。</p></div> : <>
          <div className="feishu-detail-heading"><div><h2>{source.name}</h2>
            <p>{source.documentId}</p></div>
            <div className="feishu-detail-actions"><button type="button" onClick={() => {
              setMode("edit"); setConfirmDisable(false); setOperationError(null);
            }}>编辑设置</button>
            {source.status === "configured" ? <button type="button" onClick={() => {
              setConfirmDisable(true); setOperationError(null);
            }}>停用来源</button> : null}</div>
          </div>
          <dl className="feishu-facts">
            <div><dt>来源状态</dt><dd>{source.status === "configured" ? "已启用" : "已停用"}</dd></div>
            <div><dt>访问状态</dt><dd>{ACCESS[source.accessState]}</dd></div>
            <div><dt>同步周期</dt><dd>{intervalLabel(source.syncIntervalSeconds)}</dd></div>
            <div><dt>凭证别名</dt><dd>{source.credentialRef}</dd></div>
            <div><dt>最近检查</dt><dd>{showDate(source.lastCheckedAt)}</dd></div>
            <div><dt>最近成功</dt><dd>{showDate(source.lastSuccessAt)}</dd></div>
            {source.nextSyncAt ? <div><dt>下次计划</dt><dd>{showDate(source.nextSyncAt)}</dd></div> : null}
          </dl>
          {source.accessState === "access_denied" ? <p className="feishu-guidance">应用无法读取文档。请确认飞书应用权限与文档共享，然后手动同步。</p> : null}
          {source.accessState === "not_found" ? <p className="feishu-guidance">飞书文档不存在。请核对 ID，或联系文档所有者。</p> : null}
          {source.status === "disabled" ? <p className="feishu-guidance">恢复时须再次确认项目共享，并重新同步验证访问权限。</p> : null}
          {confirmDisable ? <div className="feishu-disable-confirm" role="group" aria-label="确认停用来源">
            <p>停用「{source.name}」？项目成员将无法继续读取其已保存内容。</p>
            <button type="button" disabled={mutation.isPending} onClick={() => setConfirmDisable(false)}>取消</button>
            <button type="button" disabled={mutation.isPending} onClick={() => void run({ kind: "disable", sourceId: source.id })}>
              {mutation.isPending ? "正在停用…" : `确认停用 ${source.name}`}</button>
          </div> : null}
          {source.status === "disabled" ? <div className="feishu-restore-confirm">
            <label><input type="checkbox" checked={restoreShared} onChange={(event) => setRestoreShared(event.target.checked)} />
              我确认将此文档共享给当前项目中有读取权限的成员</label>
            <button type="button" disabled={!restoreShared || mutation.isPending}
              onClick={() => void run({ kind: "patch", sourceId: source.id,
                body: { status: "configured", accessPolicy: "project_members" } })}>恢复来源</button>
          </div> : null}
          {source.status === "configured" ? <button className="feishu-sync-action" type="button"
            disabled={mutation.isPending} onClick={() => void run({ kind: "sync", sourceId: source.id })}>
            {mutation.isPending ? "正在提交…" : "立即同步"}</button> : null}
          {operationError ? <p role="alert" className="form-error">{operationError.message}
            {operationError.traceId ? ` · 请求编号：${operationError.traceId}` : ""}</p> : null}
          {history.isError ? <div className="feishu-history-error"><p role="alert">{displayedError(history.error)}</p>
            <button type="button" onClick={() => void history.refetch()}>重新加载记录</button></div> : null}
          {!history.isFetchedAfterMount && !history.isError ? <p role="status">正在加载同步记录…</p> : null}
          {history.data && history.isFetchedAfterMount ? <FeishuSyncHistory source={source} items={syncItems}
            active={active} pollingStopped={tracked.automaticPollingStopped}
            hasNextPage={history.hasNextPage} loadingMore={history.isFetchingNextPage}
            onRefresh={() => { void history.refetch(); void tracked.refresh(); void sources.refetch(); }}
            onLoadMore={() => void history.fetchNextPage()}
            onRetry={() => void run({ kind: "sync", sourceId: source.id })} /> : null}
        </>}
      </section>
    </div> : null}
  </section>;
}
