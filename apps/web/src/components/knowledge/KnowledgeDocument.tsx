import { useQueryClient } from "@tanstack/react-query";
import { Download, Info, Link2, RefreshCw } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { ApiError } from "../../api/errors.ts";
import { buildKnowledgeDownloadUrl } from "../../api/knowledge.ts";
import { knowledgeKeys, useKnowledgeContentQuery } from "../../queries/knowledge.ts";
import { KnowledgeCitationContext, type KnowledgeCitationReference } from "./KnowledgeCitationContext.tsx";
import { KnowledgeResourceDetails, type KnowledgeResourceDetailsProps } from "./KnowledgeResourceDetails.tsx";
const KnowledgeDocumentBody = lazy(() => import("./KnowledgeDocumentBody.tsx").then(module => ({ default: module.KnowledgeDocumentBody })));

function subscribeNetwork(callback: () => void) {
  window.addEventListener("online", callback); window.addEventListener("offline", callback);
  return () => { window.removeEventListener("online", callback); window.removeEventListener("offline", callback); };
}
function online() { return navigator.onLine; }

export function KnowledgeDocument(props: KnowledgeResourceDetailsProps & {
  title: string; citation?: KnowledgeCitationReference; unsupportedFormat?: boolean;
}) {
  const queryClient = useQueryClient();
  const connected = useSyncExternalStore(subscribeNetwork, online, () => true);
  const subscribeAbort = useCallback((callback: () => void) => {
    props.sessionSignal.addEventListener("abort", callback);
    return () => props.sessionSignal.removeEventListener("abort", callback);
  }, [props.sessionSignal]);
  const aborted = useSyncExternalStore(subscribeAbort, () => props.sessionSignal.aborted);
  const [recoveryRequired, setRecoveryRequired] = useState(!connected);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [blockedError, setBlockedError] = useState<ApiError | null>(null);
  const [initialBinaryCitation] = useState(props.citation !== undefined && props.unsupportedFormat === true);
  const body = useRef<HTMLDivElement>(null);
  const lastHit = useRef<string | null>(null);
  const key = knowledgeKeys.content(props.organizationId, props.projectId, props.resourceId,
    props.citation?.resourceVersionId, props.citation?.chunkId);
  const query = useKnowledgeContentQuery({ organizationId: props.organizationId,
    projectId: props.projectId, resourceId: props.resourceId,
    resourceVersionId: props.citation?.resourceVersionId, chunkId: props.citation?.chunkId,
    sessionSignal: props.sessionSignal, enabled: connected && !recoveryRequired && !props.unsupportedFormat && !initialBinaryCitation && blockedError === null });
  useEffect(() => {
    if (connected) return;
    setRecoveryRequired(true);
    void queryClient.cancelQueries({ queryKey: key, exact: true });
    queryClient.removeQueries({ queryKey: key, exact: true });
  }, [connected, queryClient, props.organizationId, props.projectId, props.resourceId,
    props.citation?.resourceVersionId, props.citation?.chunkId]);
  useEffect(() => {
    const abort = () => { void queryClient.cancelQueries({ queryKey: key, exact: true });
      queryClient.removeQueries({ queryKey: key, exact: true }); };
    props.sessionSignal.addEventListener("abort", abort, { once: true });
    return () => { props.sessionSignal.removeEventListener("abort", abort); abort(); };
  }, [props.organizationId, props.projectId, props.resourceId, props.citation?.resourceVersionId,
    props.citation?.chunkId, props.sessionSignal, queryClient]);
  const terminalError = query.error instanceof ApiError && [401, 404, 409].includes(query.error.status ?? 0);
  useEffect(() => {
    if (!(query.error instanceof ApiError)) return;
    setBlockedError(query.error);
    queryClient.removeQueries({ queryKey: key, exact: true });
  }, [query.error, queryClient]);
  useEffect(() => {
    if (!terminalError) return;
    void queryClient.invalidateQueries({ queryKey: knowledgeKeys.searches(props.organizationId, props.projectId), refetchType: "none" });
    void props.onResourceMissing();
  }, [terminalError]);
  function returnToCitation() {
    const targets = body.current?.querySelectorAll<HTMLElement>('[data-citation-hit="true"]');
    const citationStart = query.data?.highlight?.lineStart;
    if (!targets?.length || citationStart === undefined) return false;
    const target = Array.from(targets).sort((a, b) => {
      const aStart = Number(a.dataset.lineStart), aEnd = Number(a.dataset.lineEnd);
      const bStart = Number(b.dataset.lineStart), bEnd = Number(b.dataset.lineEnd);
      const aContainsStart = aStart <= citationStart && aEnd >= citationStart;
      const bContainsStart = bStart <= citationStart && bEnd >= citationStart;
      return Number(bContainsStart) - Number(aContainsStart) ||
        (aEnd - aStart) - (bEnd - bStart) ||
        Math.abs(aStart - citationStart) - Math.abs(bStart - citationStart);
    })[0]!;
    target.tabIndex = -1;
    const scroller = body.current?.closest<HTMLElement>(".knowledge-reader-scroll");
    if (scroller) {
      const targetBounds = target.getBoundingClientRect();
      const readerBounds = scroller.getBoundingClientRect();
      scroller.scrollTo({ top: scroller.scrollTop + targetBounds.top - readerBounds.top -
        (scroller.clientHeight - targetBounds.height) / 2, behavior: "instant" });
    } else {
      target.scrollIntoView?.({ block: "center", behavior: "instant" });
    }
    target.focus({ preventScroll: true });
    return true;
  }
  const available = connected && !recoveryRequired && !aborted &&
    query.isSuccess && !query.isFetching && !terminalError && blockedError === null;
  useLayoutEffect(() => {
    const hit = available ? query.data?.highlight : null;
    if (!hit || lastHit.current === hit.chunkId) return;
    const focus = () => {
      if (lastHit.current === hit.chunkId) return;
      if (returnToCitation()) lastHit.current = hit.chunkId;
    };
    focus();
    const observer = new MutationObserver(focus);
    if (body.current) observer.observe(body.current, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [available, query.data]);
  const displayedError = blockedError ?? query.error;
  const unsupported = props.unsupportedFormat || initialBinaryCitation || (displayedError instanceof ApiError && [413, 415].includes(displayedError.status ?? 0));
  const showDetails = detailsOpen || (unsupported && props.citation === undefined);
  return <section id={props.id} className="knowledge-document" aria-label={`${props.title} 正文`}>
    <header className="knowledge-document-header"><div><h2>{available ? query.data.title : props.title}</h2>
      <p>{available ? `${query.data.format === "markdown" ? "Markdown" : "纯文本"} · 全文 · ${query.data.lineCount} 行` : "全文预览"}</p></div>
      <div className="knowledge-reader-actions">
        <button type="button" disabled={!connected || query.isFetching || props.sessionSignal.aborted} onClick={() => {
          lastHit.current = null;
          if (blockedError !== null) setBlockedError(null);
          else if (recoveryRequired) setRecoveryRequired(false); else void query.refetch();
        }}><RefreshCw size={17} aria-hidden="true" />重新读取正文</button>
        <button type="button" aria-expanded={showDetails} aria-controls={`${props.id}-details`} onClick={() => setDetailsOpen(value => !value)}><Info size={17} aria-hidden="true" />资料详情</button>
        {available ? <a href={buildKnowledgeDownloadUrl(props.projectId, props.resourceId)} target="_blank" rel="noopener noreferrer"><Download size={17} aria-hidden="true" />下载原文件</a> : null}
      </div></header>
    {!connected || recoveryRequired ? <p role="status">{connected ? "网络已恢复，请重新读取正文。" : "网络已断开，正文已隐藏。恢复连接后请重新读取。"}</p> :
      !unsupported && blockedError === null && (query.isFetching || query.isPending) ? <p role="status">正在读取完整正文…</p> : null}
    {props.unsupportedFormat ? <p>该格式暂不支持全文预览，请下载原文件。引用可核对经过授权的相邻片段。</p> : null}
    {connected && !recoveryRequired && displayedError !== null ? <div className="knowledge-document-error">
      <p role="alert">{displayedError instanceof ApiError ? displayedError.message : "正文暂时无法读取，请重新读取。"}</p>
      {displayedError instanceof ApiError && displayedError.traceId ? <p>请求编号：{displayedError.traceId}</p> : null}
    </div> : null}
    {available ? <>
      {query.data.highlight ? <div className="knowledge-document-citation"><p><Link2 size={16} aria-hidden="true" />{query.data.highlight.matchType === "exact" ? "引用原文" : "引用所在区块"} · 第 {query.data.highlight.lineStart}–{query.data.highlight.lineEnd} 行</p>
        {query.data.highlight.matchType === "range" ? <blockquote>{query.data.highlight.text}</blockquote> : null}
        <button type="button" onClick={returnToCitation}>回到引用</button></div> : null}
      <div ref={body} className="knowledge-document-body"><Suspense fallback={<p role="status">正在排版正文…</p>}><KnowledgeDocumentBody content={query.data.content} format={query.data.format} highlight={query.data.highlight} /></Suspense></div>
      <p className="knowledge-document-eof" role="status">已到文档末尾 · 正文完整</p>
    </> : null}
    {showDetails ? <KnowledgeResourceDetails {...props} id={`${props.id}-details`} readingMode="full" /> : null}
    {unsupported && props.citation ? <KnowledgeCitationContext id={`${props.id}-context`} organizationId={props.organizationId} projectId={props.projectId} citation={props.citation} sessionSignal={props.sessionSignal} /> : null}
  </section>;
}
