import { useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState, type FormEvent } from "react";

import { ApiError } from "../../api/errors.ts";
import type { KnowledgeCitation, KnowledgeSearchResponse } from "../../api/knowledge.ts";
import {
  KNOWLEDGE_SEARCH_LIMIT,
  formatKnowledgeLocator,
  formatKnowledgeMediaType,
  validateKnowledgeQuery,
} from "../../lib/knowledgeSearch.ts";
import {
  knowledgeKeys,
  type SubmittedKnowledgeSearch,
  useKnowledgeSearchQuery,
} from "../../queries/knowledge.ts";
import { KnowledgeCitationContext } from "./KnowledgeCitationContext.tsx";

export interface KnowledgeSearchProps {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  sessionSignal: AbortSignal;
  onAccessUnavailable(error: ApiError): void;
}

export function presentKnowledgeSearchError(error: unknown): {
  message: string;
  traceId: string | null;
  retryable: boolean;
} {
  if (!(error instanceof ApiError)) {
    return {
      message: "知识搜索暂时无法完成，请稍后重试",
      traceId: null,
      retryable: true,
    };
  }
  const retryAfter = error.status === 429 && error.retryAfterSeconds !== null
    ? ` 请在 ${error.retryAfterSeconds} 秒后再次搜索。`
    : "";
  return {
    message: `${error.message}${retryAfter}`,
    traceId: error.traceId,
    retryable: error.retryable,
  };
}

export function KnowledgeSearch({
  organizationId,
  projectId,
  csrfToken,
  sessionSignal,
  onAccessUnavailable,
}: KnowledgeSearchProps) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const helpId = useId();
  const [draft, setDraft] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [search, setSearch] = useState<SubmittedKnowledgeSearch | null>(null);
  const [resultTreeRevision, setResultTreeRevision] = useState(0);
  const onAccessUnavailableRef = useRef(onAccessUnavailable);
  const deliveredAccessErrorsRef = useRef(new WeakSet<ApiError>());
  const query = useKnowledgeSearchQuery({
    organizationId,
    projectId,
    search,
    csrfToken,
    sessionSignal,
  });

  useLayoutEffect(() => {
    onAccessUnavailableRef.current = onAccessUnavailable;
    const error = query.error;
    if (
      !(error instanceof ApiError) ||
      error.status !== 404 ||
      deliveredAccessErrorsRef.current.has(error)
    ) {
      return;
    }
    deliveredAccessErrorsRef.current.add(error);
    onAccessUnavailableRef.current(error);
  }, [onAccessUnavailable, query.error]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = validateKnowledgeQuery(draft);
    if (!validation.ok) {
      setValidationError(validation.message);
      return;
    }
    setDraft(validation.query);
    setValidationError(null);
    setNotice(null);
    setResultTreeRevision((current) => current + 1);
    if (search?.query === validation.query && search.limit === KNOWLEDGE_SEARCH_LIMIT) {
      void query.refetch();
      return;
    }
    setSearch({ query: validation.query, limit: KNOWLEDGE_SEARCH_LIMIT });
  }

  function cancel() {
    if (search === null) return;
    void queryClient.cancelQueries({
      queryKey: knowledgeKeys.search(
        organizationId,
        projectId,
        search.query,
        search.limit,
      ),
      exact: true,
    });
    setSearch(null);
    setNotice("搜索已取消");
  }

  const pending = search !== null && query.isFetching;
  const error = search === null || query.error === null
    ? null
    : presentKnowledgeSearchError(query.error);

  return (
    <section className="knowledge-search" aria-label="项目知识检索">
      <div className="knowledge-search-heading">
        <span className="knowledge-search-kicker">真实项目检索</span>
        <h2>搜索项目知识</h2>
        <p id={helpId}>搜索只返回当前项目已索引的原文片段，不生成 AI 答案。</p>
      </div>
      <form className="knowledge-search-form" onSubmit={submit}>
        <label htmlFor={inputId}>搜索项目知识</label>
        <div className="knowledge-search-controls">
          <textarea
            id={inputId}
            value={draft}
            rows={2}
            aria-invalid={validationError === null ? undefined : "true"}
            aria-describedby={
              `${helpId}${validationError === null ? "" : " knowledge-search-error"}`
            }
            onChange={(event) => {
              setDraft(event.target.value);
              if (validationError !== null) setValidationError(null);
            }}
          />
          <div className="knowledge-search-actions">
            <button type="submit">
              <Search aria-hidden="true" size={18} />
              搜索项目知识
            </button>
            {pending ? (
              <button type="button" className="secondary-action" onClick={cancel}>
                <X aria-hidden="true" size={18} />
                取消搜索
              </button>
            ) : null}
          </div>
        </div>
        {validationError === null ? null : (
          <p id="knowledge-search-error" className="form-error" role="alert">
            {validationError}
          </p>
        )}
      </form>
      <div className="knowledge-search-output" aria-busy={pending ? "true" : undefined}>
        {pending ? <p role="status" aria-live="polite">正在搜索项目知识…</p> : null}
        {notice === null ? null : <p role="status" aria-live="polite">{notice}</p>}
        {error === null ? null : (
          <div className="knowledge-search-error">
            <p role="alert">{error.message}</p>
            {error.traceId === null ? null : <p>请求编号：{error.traceId}</p>}
            {error.retryable ? (
              <button type="button" onClick={() => void query.refetch()}>
                重新搜索
              </button>
            ) : null}
          </div>
        )}
        {search !== null && query.isSuccess ? (
          <KnowledgeSearchResults
            key={resultTreeRevision}
            organizationId={organizationId}
            projectId={projectId}
            response={query.data}
            sessionSignal={sessionSignal}
          />
        ) : null}
      </div>
    </section>
  );
}

function KnowledgeSearchResults({
  organizationId,
  projectId,
  response,
  sessionSignal,
}: {
  organizationId: string;
  projectId: string;
  response: KnowledgeSearchResponse;
  sessionSignal: AbortSignal;
}) {
  const fallback = response.retrievalMode === "keyword_fallback";
  return (
    <div className="knowledge-search-results">
      {fallback ? (
        <p className="knowledge-search-fallback" role="status">
          语义检索暂时不可用，本次使用关键词结果。
        </p>
      ) : (
        <p className="knowledge-search-mode">混合检索</p>
      )}
      {response.results.length === 0 ? (
        <div className="knowledge-search-empty" role="status">
          <strong>没有匹配片段</strong>
          <p>请尝试更换关键词或缩短查询。</p>
        </div>
      ) : (
        <>
          <p>找到 {response.results.length} 个匹配片段</p>
          <ol className="knowledge-search-result-list" aria-label="知识搜索结果">
            {response.results.map((citation) => (
              <KnowledgeSearchResult
                key={citation.chunkId}
                organizationId={organizationId}
                projectId={projectId}
                citation={citation}
                sessionSignal={sessionSignal}
              />
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

function KnowledgeSearchResult({
  organizationId,
  projectId,
  citation,
  sessionSignal,
}: {
  organizationId: string;
  projectId: string;
  citation: KnowledgeCitation;
  sessionSignal: AbortSignal;
}) {
  const panelId = useId();
  const [expanded, setExpanded] = useState(false);
  return (
    <li className="knowledge-search-result">
      <article>
        <div className="knowledge-search-result-heading">
          <h3>{citation.title}</h3>
          <span>{formatKnowledgeMediaType(citation.mediaType)}</span>
        </div>
        <p className="knowledge-search-locator">
          {formatKnowledgeLocator(citation.locator)}
        </p>
        <p className="knowledge-search-excerpt">{citation.excerpt}</p>
        <button
          aria-controls={panelId}
          aria-expanded={expanded}
          className="knowledge-citation-toggle"
          type="button"
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? "收起引用上下文" : "查看引用上下文"}
        </button>
        {expanded ? (
          <KnowledgeCitationContext
            id={panelId}
            organizationId={organizationId}
            projectId={projectId}
            citation={citation}
            sessionSignal={sessionSignal}
          />
        ) : null}
      </article>
    </li>
  );
}
