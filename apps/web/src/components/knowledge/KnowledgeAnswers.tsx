import { useMutation } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import { type FormEvent, useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import { ApiError } from "../../api/errors.ts";
import {
  answerKnowledge,
  type KnowledgeAnswerCitation,
  type KnowledgeAnswerResponse,
} from "../../api/knowledgeAnswers.ts";
import { formatKnowledgeLocator, formatKnowledgeMediaType, validateKnowledgeQuery } from "../../lib/knowledgeSearch.ts";
import { KnowledgeCitationContext } from "./KnowledgeCitationContext.tsx";

export interface KnowledgeAnswersProps {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  sessionSignal: AbortSignal;
  onAccessUnavailable(error: ApiError): void;
  resourceDeletion?: { revision: number; title: string } | null;
}

function presentError(error: unknown): string | null {
  if (error instanceof ApiError && error.kind === "aborted") return null;
  if (error instanceof ApiError && error.status === 409) return "项目资料已发生变化，请重新提问";
  if (error instanceof ApiError && error.status === 429 && error.retryAfterSeconds !== null) {
    return `提问过于频繁，请在 ${error.retryAfterSeconds} 秒后重试`;
  }
  return error instanceof Error && error.message.trim()
    ? error.message
    : "暂时无法生成回答，请手动重试";
}

export function KnowledgeAnswers({
  organizationId,
  projectId,
  csrfToken,
  sessionSignal,
  onAccessUnavailable,
  resourceDeletion = null,
}: KnowledgeAnswersProps) {
  const inputId = useId();
  const helpId = useId();
  const [draft, setDraft] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<KnowledgeAnswerResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [online, setOnline] = useState(() => navigator.onLine);
  const requestRef = useRef<AbortController | null>(null);
  const deletionRevision = useRef(0);
  const accessCallback = useRef(onAccessUnavailable);
  const mutation = useMutation({
    mutationFn: ({ question, signal }: { question: string; signal: AbortSignal }) =>
      answerKnowledge({ projectId, question, csrfToken, signal }),
    retry: false,
    networkMode: "always",
    gcTime: 0,
  });

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  useEffect(() => {
    const abort = () => {
      requestRef.current?.abort();
      requestRef.current = null;
      setAnswer(null);
      mutation.reset();
    };
    sessionSignal.addEventListener("abort", abort, { once: true });
    return () => {
      sessionSignal.removeEventListener("abort", abort);
      abort();
    };
  }, [projectId, sessionSignal]); // mutation identity is intentionally lifecycle-local

  useEffect(() => {
    accessCallback.current = onAccessUnavailable;
  }, [onAccessUnavailable]);

  useLayoutEffect(() => {
    if (resourceDeletion === null || resourceDeletion.revision === deletionRevision.current) return;
    deletionRevision.current = resourceDeletion.revision;
    requestRef.current?.abort();
    requestRef.current = null;
    setAnswer(null);
    mutation.reset();
    setNotice(`资料“${resourceDeletion.title}”已删除，回答已清空。`);
  }, [resourceDeletion]);

  useEffect(() => {
    if (online) return;
    requestRef.current?.abort();
    requestRef.current = null;
    setAnswer(null);
    mutation.reset();
    setNotice("当前处于离线状态，回答已清空");
  }, [online]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = validateKnowledgeQuery(draft);
    if (!validation.ok) {
      setValidationError(validation.message);
      return;
    }
    if (!online) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setDraft(validation.query);
    setValidationError(null);
    setNotice(null);
    setAnswer(null);
    mutation.reset();
    mutation.mutate(
      { question: validation.query, signal: controller.signal },
      {
        onSuccess: (response) => {
          if (controller.signal.aborted || requestRef.current !== controller) return;
          requestRef.current = null;
          setAnswer(response);
        },
        onError: (error) => {
          if (controller.signal.aborted || requestRef.current !== controller) return;
          requestRef.current = null;
          if (error instanceof ApiError && error.status === 404) accessCallback.current(error);
        },
      },
    );
  }

  function cancel() {
    requestRef.current?.abort();
    requestRef.current = null;
    mutation.reset();
    setAnswer(null);
    setNotice("回答生成已取消");
  }

  const error = mutation.error === null ? null : presentError(mutation.error);

  return (
    <section className="knowledge-answers" aria-label="项目知识问答">
      <div className="knowledge-search-heading">
        <span className="knowledge-search-kicker">基于项目资料</span>
        <h2>向项目知识提问</h2>
        <p id={helpId}>生成的回答来自当前项目资料，请核对引用。</p>
      </div>
      <form className="knowledge-search-form" onSubmit={submit}>
        <label htmlFor={inputId}>向项目知识提问</label>
        <div className="knowledge-search-controls">
          <textarea
            id={inputId} rows={3} value={draft} disabled={!online}
            aria-describedby={`${helpId}${validationError === null ? "" : " knowledge-answer-error"}`}
            aria-invalid={validationError === null ? undefined : "true"}
            onChange={(event) => {
              setDraft(event.target.value);
              if (validationError !== null) setValidationError(null);
            }}
          />
          <div className="knowledge-search-actions">
            <button type="submit" disabled={!online || mutation.isPending}>
              <Sparkles aria-hidden="true" size={18} />生成回答
            </button>
            {mutation.isPending ? (
              <button type="button" className="secondary-action" onClick={cancel}>
                <X aria-hidden="true" size={18} />取消
              </button>
            ) : null}
          </div>
        </div>
        {validationError === null ? null : (
          <p id="knowledge-answer-error" className="form-error" role="alert">{validationError}</p>
        )}
      </form>
      <div className="knowledge-answer-output" aria-busy={mutation.isPending ? "true" : undefined}>
        {mutation.isPending ? <p role="status" aria-live="polite">正在查找资料并生成回答…</p> : null}
        {notice === null ? null : <p role="status" aria-live="polite">{notice}</p>}
        {error === null ? null : <p role="alert">{error}</p>}
        {answer === null ? null : answer.status === "insufficient_evidence" ? (
          <div className="knowledge-answer-insufficient" role="status">
            <strong>现有项目资料不足以回答这个问题</strong>
            <p>可以补充相关资料，或换一种问法再试。</p>
          </div>
        ) : (
          <KnowledgeAnswerResult
            answer={answer} organizationId={organizationId} projectId={projectId}
            sessionSignal={sessionSignal}
          />
        )}
      </div>
    </section>
  );
}

function KnowledgeAnswerResult({ answer, organizationId, projectId, sessionSignal }: {
  answer: KnowledgeAnswerResponse;
  organizationId: string;
  projectId: string;
  sessionSignal: AbortSignal;
}) {
  return (
    <article className="knowledge-answer-result" aria-label="生成式回答" role="region">
      <p className="knowledge-answer-note">回答由 AI 根据项目资料生成，请核对引用</p>
      <div className="knowledge-answer-paragraphs">
        {answer.paragraphs.map((paragraph, index) => (
          <div key={`${index}:${paragraph.text}`}>
            <p>{paragraph.text}</p>
            <p className="knowledge-answer-inline-citations">来源：{paragraph.citationIds.join("、")}</p>
          </div>
        ))}
      </div>
      <ol className="knowledge-answer-sources" aria-label="回答来源">
        {answer.citations.map((citation) => (
          <AnswerCitation key={citation.id} citation={citation} organizationId={organizationId}
            projectId={projectId} sessionSignal={sessionSignal} />
        ))}
      </ol>
    </article>
  );
}

function AnswerCitation({ citation, organizationId, projectId, sessionSignal }: {
  citation: KnowledgeAnswerCitation;
  organizationId: string;
  projectId: string;
  sessionSignal: AbortSignal;
}) {
  const [open, setOpen] = useState(false);
  const contextId = useId();
  return (
    <li>
      <div className="knowledge-answer-source-heading">
        <strong>{citation.id} · {citation.title}</strong>
        <span>{formatKnowledgeMediaType(citation.mediaType)} · {formatKnowledgeLocator(citation.locator)}</span>
      </div>
      <p>{citation.excerpt}</p>
      <button className="knowledge-citation-toggle" type="button" aria-expanded={open}
        aria-controls={contextId} onClick={() => setOpen((value) => !value)}>
        {open ? "收起引用上下文" : "查看引用上下文"}
      </button>
      {open ? <KnowledgeCitationContext id={contextId} organizationId={organizationId}
        projectId={projectId} citation={citation} sessionSignal={sessionSignal} /> : null}
    </li>
  );
}
