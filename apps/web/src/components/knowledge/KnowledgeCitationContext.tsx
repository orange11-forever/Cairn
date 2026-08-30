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

interface KnowledgeCitationContextProps {
  id: string;
  organizationId: string;
  projectId: string;
  citation: KnowledgeCitation;
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

  return (
    <section
      id={id}
      aria-busy={query.isPending ? "true" : undefined}
      aria-label="引用上下文"
      className="knowledge-citation-context"
      role="region"
    >
      {query.isPending ? (
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
      {query.isSuccess ? (
        <ContextSuccess
          context={query.data}
          downloadUrl={buildKnowledgeDownloadUrl(projectId, citation.resourceId)}
        />
      ) : null}
    </section>
  );
}

function ContextSuccess({
  context,
  downloadUrl,
}: {
  context: KnowledgeChunkContext;
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
            <p>{chunk.text}</p>
          </div>
        ))}
      </div>
      <a
        className="knowledge-citation-download"
        href={downloadUrl}
        rel="noopener noreferrer"
        target="_blank"
      >
        下载原文件（新标签页）
      </a>
    </div>
  );
}
