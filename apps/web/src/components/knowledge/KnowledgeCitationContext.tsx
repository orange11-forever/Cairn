import { Download, Link2 } from "lucide-react";
import { KnowledgeText } from "./KnowledgeText.tsx";
import { useQueryClient } from "@tanstack/react-query";
import { useLayoutEffect, useRef } from "react";

import { ApiError } from "../../api/errors.ts";
import {
  buildKnowledgeDownloadUrl,
  type KnowledgeChunkContext,
  type KnowledgeCitation,
} from "../../api/knowledge.ts";
import { formatKnowledgeLocator } from "../../lib/knowledgeSearch.ts";
import {
  knowledgeKeys,
  useKnowledgeChunkContextQuery,
} from "../../queries/knowledge.ts";

export type KnowledgeCitationReference = Pick<KnowledgeCitation, "resourceId" | "resourceVersionId" | "chunkId" | "title">;

interface KnowledgeCitationContextProps {
  id: string;
  organizationId: string;
  projectId: string;
  citation: KnowledgeCitationReference;
  sessionSignal: AbortSignal;
}

type PresentedContextError = {
  message: string;
  traceId: string | null;
  retryable: boolean;
};

export function presentKnowledgeCitationContextError(
  error: unknown,
): PresentedContextError | null {
  if (error instanceof ApiError && error.kind === "aborted") return null;
  if (error instanceof ApiError && error.status === 404) {
    return {
      message: "该引用已不可用，请重新搜索",
      traceId: error.traceId,
      retryable: false,
    };
  }
  if (error instanceof ApiError) {
    return {
      message: error.message,
      traceId: error.traceId,
      retryable: error.retryable,
    };
  }
  return {
    message: "引用上下文暂时无法加载，请稍后重试",
    traceId: null,
    retryable: true,
  };
}

export function KnowledgeCitationContext({
  id,
  organizationId,
  projectId,
  citation,
  sessionSignal,
}: KnowledgeCitationContextProps) {
  const queryClient = useQueryClient();
  const delivered404s = useRef(new WeakSet<ApiError>());
  const query = useKnowledgeChunkContextQuery({
    organizationId,
    projectId,
    resourceId: citation.resourceId,
    resourceVersionId: citation.resourceVersionId,
    chunkId: citation.chunkId,
    sessionSignal,
  });

  useLayoutEffect(() => {
    const error = query.error;
    if (
      !(error instanceof ApiError) ||
      error.status !== 404 ||
      delivered404s.current.has(error)
    ) return;
    delivered404s.current.add(error);
    void queryClient.invalidateQueries({
      queryKey: knowledgeKeys.searches(organizationId, projectId),
      refetchType: "none",
    });
    void queryClient.refetchQueries({
      queryKey: knowledgeKeys.resources(organizationId, projectId),
      exact: true,
      type: "active",
    });
  }, [organizationId, projectId, query.error, queryClient]);

  const presentedError = query.error === null
    ? null
    : presentKnowledgeCitationContextError(query.error);
  const authorizing = query.isFetching;

  return (
    <section
      id={id}
      aria-busy={authorizing ? "true" : undefined}
      aria-label="引用上下文"
      className="knowledge-citation-context"
      role="region"
    >
      {authorizing ? (
        <p role="status" aria-live="polite">正在加载引用上下文…</p>
      ) : null}
      {presentedError === null ? null : (
        <div className="knowledge-citation-context-error">
          <p role="alert">{presentedError.message}</p>
          {presentedError.traceId === null
            ? null
            : <p>请求编号：{presentedError.traceId}</p>}
          {presentedError.retryable ? (
            <button type="button" onClick={() => void query.refetch()}>
              重新加载引用上下文
            </button>
          ) : null}
        </div>
      )}
      {query.isSuccess && !authorizing ? (
        <ContextSuccess
          title={citation.title}
          context={query.data}
          downloadUrl={buildKnowledgeDownloadUrl(projectId, citation.resourceId)}
        />
      ) : null}
    </section>
  );
}

function ContextSuccess({
  context,
  title,
  downloadUrl,
}: {
  context: KnowledgeChunkContext;
  title: string;
  downloadUrl: string;
}) {
  const chunks = [
    context.before === null
      ? null
      : { label: "前文", chunk: context.before, hit: false },
    { label: "命中片段", chunk: context.hit, hit: true },
    context.after === null
      ? null
      : { label: "后文", chunk: context.after, hit: false },
  ].filter((entry): entry is NonNullable<typeof entry> => entry !== null);

  return (
    <div className="knowledge-citation-context-success">
      <header className="knowledge-context-header"><h2>{title}</h2><p><Link2 size={16} aria-hidden="true" />引用上下文 · 命中片段与相邻内容</p></header>
      <p className="knowledge-context-boundary">以下是当前引用附近的片段，不是完整文档。可下载原文件核对完整内容。</p>
      <div className="knowledge-citation-chunks">
        {chunks.map(({ label, chunk, hit }) => (
          <div
            className="knowledge-citation-chunk"
            data-hit={hit ? "true" : undefined}
            key={chunk.id}
          >
            <div className="knowledge-citation-chunk-heading">
              <strong>{label}</strong>
              <span>{formatKnowledgeLocator(chunk.locator)}</span>
            </div>
            <KnowledgeText text={chunk.text} />
          </div>
        ))}
      </div>
      <a
        className="knowledge-citation-download"
        href={downloadUrl}
        rel="noopener noreferrer"
        target="_blank"
      >
        <Download size={17} aria-hidden="true" />下载原文件（新标签页）
      </a>
    </div>
  );
}
