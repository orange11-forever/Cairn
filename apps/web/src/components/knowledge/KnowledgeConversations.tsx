import { FileText, Plus, Send, UserRound, X } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef } from "react";
import { ApiError } from "../../api/errors.ts";
import type { KnowledgeCitation } from "../../api/knowledge.ts";
import { isConversationId } from "../../api/knowledgeConversations.ts";
import { AssistantAvatar } from "./AssistantAvatar.tsx";
import { KnowledgeAnswerResult } from "./KnowledgeAnswers.tsx";
import { useProjectConversations } from "./ProjectConversationsContext.tsx";
import { AssistantSkills } from "./AssistantSkills.tsx";

export function KnowledgeConversations({ organizationId, projectId, sessionSignal, onAccessUnavailable, onOpenCitation, resourceDeletion = null, projectName = "当前项目" }: {
  organizationId: string; projectId: string; sessionSignal: AbortSignal; onAccessUnavailable(error: ApiError): void;
  onOpenCitation?(citation: KnowledgeCitation): void; resourceDeletion?: { revision: number; title: string } | null; projectName?: string;
}) {
  const state = useProjectConversations();
  const inputId = useId();
  const deletion = useRef(0);
  const output = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (state !== null && state.selectedId !== null && state.recovery === undefined && isConversationId(state.selectedId)) void state.detail.refetch({ cancelRefetch: false });
  }, []);
  useEffect(() => { if (state?.projectError instanceof ApiError) onAccessUnavailable(state.projectError); }, [state?.projectError, onAccessUnavailable]);
  useLayoutEffect(() => {
    if (resourceDeletion !== null && resourceDeletion.revision !== deletion.current) { deletion.current = resourceDeletion.revision; state?.invalidateHistory(); }
  }, [resourceDeletion]);
  useEffect(() => { output.current?.scrollTo?.({ top: output.current.scrollHeight, behavior: "auto" }); }, [state?.detail.data?.turns.length, state?.detail.isFetching, state?.busy, state?.preview.length]);
  if (state === null) return null;
  const detailError = state.detail.error;
  const invalidId = state.selectedId !== null && !isConversationId(state.selectedId);
  const message = state.error instanceof ApiError && state.error.status === 429 && state.error.retryAfterSeconds !== null ? `提问过于频繁，请在 ${state.error.retryAfterSeconds} 秒后再发送。` : state.error instanceof Error ? state.error.message : null;
  const current = state.projectError === null && state.online && !state.detail.isFetching && !state.detail.isError ? state.detail.data : undefined;
  return <section className={`knowledge-answers knowledge-answers-docked${state.activity === "send" ? " is-generating" : ""}`} aria-label="项目知识问答">
    <div className="knowledge-search-heading"><AssistantAvatar name={state.assistant.data?.name ?? "岑宁"} avatarDataUrl={state.assistant.data?.avatarDataUrl} /><div><h2>{state.assistant.data?.name ?? "岑宁"}</h2><p>项目问答 · 助手独立对话</p></div></div>
    <AssistantSkills projectId={projectId} csrfToken={state.csrfToken} sessionSignal={sessionSignal} />
    <div className="conversation-mobile-controls">
      <label><span className="workbench-sr-only">选择对话</span><select aria-label="选择对话" value={state.selectedId ?? ""} onChange={event => state.selectConversation(event.target.value || null)}><option value="">新对话</option>{state.selectedId !== null && !state.entries.some(item => item.id === state.selectedId) ? <option value={state.selectedId}>{current?.title ?? "当前对话"}</option> : null}{state.entries.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
      <button type="button" onClick={() => state.selectConversation(null)}><Plus size={17} aria-hidden="true" /><span>新建对话</span></button>
      <button type="button" aria-pressed={state.showAllHistory} onClick={() => state.setShowAllHistory(!state.showAllHistory)}>{state.showAllHistory ? "当前助手" : "全部历史"}</button>
    </div>
    {state.list.isError ? <div className="conversation-mobile-list-error"><p role="alert">对话列表暂时无法读取。</p><button type="button" onClick={() => void state.list.refetch()}>重新读取对话列表</button></div> : null}
    {state.list.hasNextPage ? <button className="conversation-mobile-more" type="button" disabled={state.list.isFetchingNextPage} onClick={() => void state.list.fetchNextPage()}>加载更多对话</button> : null}
    <div className="conversation-model-status" role="status" aria-label="当前回答模型">{state.model.isPending ? "正在读取模型配置…" : state.model.isError ? <><span>模型配置暂时无法读取。</span><button type="button" onClick={() => void state.model.refetch()}>重新读取模型配置</button></> : state.activeModel !== undefined ? <><span title={state.activeModel.model ?? undefined}>{state.activeModel.name}</span><span> · 根据本轮项目资料回答</span></> : state.assistant.data?.modelId ? <><span>所选模型已不可用，请在助手与技能中选择可用模型并保存。</span><button type="button" onClick={() => void state.model.refetch()}>重新读取模型配置</button></> : "模型尚未配置，历史对话仍可读取。"}</div>
    <div className="knowledge-answer-output" ref={output} aria-busy={state.busy || state.detail.isFetching}>
      {state.selectedId === null ? <div className="knowledge-answer-welcome"><AssistantAvatar name={state.assistant.data?.name ?? "岑宁"} avatarDataUrl={state.assistant.data?.avatarDataUrl} /><h3>从一个问题开始</h3><p className="knowledge-answer-intro">围绕当前项目连续提问，对话会保存下来，方便下次继续。</p><p className="knowledge-answer-welcome-hint">回答来自项目资料，请核对每一轮的引用。</p></div> : null}
      {invalidId || (detailError instanceof ApiError && detailError.status === 404) ? <p role="alert">对话不存在或不可访问，可以新建对话。</p> : state.detail.isError && state.recovery === undefined ? <p role="alert">对话暂时无法读取，请重新读取会话。</p> : null}
      {state.detail.isFetching && current === undefined ? <p role="status">正在读取对话…</p> : null}
      {current?.turns.some(turn => (turn.assistantId ?? null) !== (state.assistant.data?.id ?? null)) ? <p role="status">这段历史未完整归属当前助手，保留为只读。请为当前助手新建对话。</p> : null}
      {current?.turns.map(turn => <section className="conversation-turn" key={turn.id} aria-label={`第${turn.sequence}轮问答`} role="region">
        <div className="knowledge-answer-question"><span className="knowledge-user-avatar"><UserRound size={19} aria-hidden="true" /></span><div><strong>你</strong><span className="knowledge-question-text">{turn.question}</span></div></div>
        {state.historyVerified ? <><div className="knowledge-answer-author"><AssistantAvatar name={turn.assistantName ?? "岑宁"} avatarDataUrl={state.assistants.data?.items.find(item => item.id === turn.assistantId)?.avatarDataUrl} /><strong>{turn.assistantName ?? "岑宁"}</strong>{turn.model ? <span className="conversation-turn-model" title={turn.model.model ?? undefined}>{turn.model.name}</span> : null}<span className="conversation-turn-model">配置 v{turn.assistantRevision ?? 0}</span>{turn.skillId ? <span>{state.skills.data?.items.find(item => item.id === turn.skillId)?.name ?? "技能回答"}</span> : null}</div>
        {turn.answerUnavailable ? <p className="conversation-turn-notice">引用资料已变化或无法访问，这轮历史回答暂不可用。</p> : turn.answer?.status === "insufficient_evidence" ? <div className="knowledge-answer-insufficient" role="status"><strong>现有项目资料不足以回答这个问题</strong><p>可以补充资料，或换一种问法。</p></div> : turn.answer !== null ? <KnowledgeAnswerResult answer={turn.answer} organizationId={organizationId} projectId={projectId} sessionSignal={sessionSignal} onOpenCitation={onOpenCitation} /> : null}</> : <p className="conversation-turn-notice">历史回答尚未重新核验，请重新读取会话。</p>}
        {turn.contextTruncated ? <p className="conversation-turn-notice">这轮只使用了近期有效的历史，部分上下文已省略。</p> : null}
      </section>)}
      {state.preview.length > 0 ? <section className="conversation-turn conversation-preview" aria-label="正在生成的回答">
        <div className="knowledge-answer-author"><AssistantAvatar name={state.assistant.data?.name ?? "岑宁"} avatarDataUrl={state.assistant.data?.avatarDataUrl} /><strong>{state.assistant.data?.name ?? "岑宁"}</strong></div>
        <p className="conversation-turn-notice" role="status">正在生成 · 尚未保存；完成后可核对引用。</p>
        {state.preview.map((paragraph, index) => <p className="knowledge-answer-paragraph" key={index}>{paragraph.text}</p>)}
      </section> : null}
      {!state.online ? <p role="status">当前离线，联网后可重新读取会话。</p> : null}
      {state.busy && state.preview.length === 0 ? <p role="status">{state.activity === "read" ? "正在重新读取会话…" : "正在查找资料并生成回答…"}</p> : null}
      {message === null ? null : <p role="alert">{message}</p>}
      {state.notice === null ? null : <p role="status">{state.notice}</p>}
      {state.selectedId !== null && !invalidId && !state.busy ? <button className="conversation-reread" type="button" disabled={state.busy || !state.online} onClick={() => void state.reread()}>重新读取会话</button> : null}
      {current?.turns.length === 50 ? <p role="status">这段对话已满 50 轮，可以新建对话继续提问。</p> : null}
    </div>
    <form className="knowledge-search-form" onSubmit={event => { event.preventDefault(); void state.send(); }}>
      <label className="assistant-skill-selection">使用技能<select aria-label="使用技能" value={state.selectedSkill ?? ""} disabled={state.busy || state.recovery !== undefined} onChange={event => state.chooseSkill(event.target.value || null)}><option value="">普通对话</option>{state.skills.data?.items.filter(item => item.runnable && state.assistant.data?.enabledSkillIds.includes(item.id)).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label htmlFor={inputId}>回答基于项目资料，请核对引用</label>
      <div className="knowledge-search-controls"><textarea id={inputId} aria-label="向项目知识提问" rows={3} value={state.draft} placeholder="向当前项目提问…" onChange={event => state.setDraft(event.target.value)} />
        <span className="knowledge-composer-context" title={projectName}><FileText size={15} aria-hidden="true" />{projectName}</span>
        <div className="knowledge-search-actions"><button type="submit" aria-label="生成回答" disabled={!state.canSend}><Send size={18} aria-hidden="true" /></button>{state.busy ? <button type="button" className="secondary-action" onClick={state.cancel}><X size={18} aria-hidden="true" />停止等待</button> : null}</div>
      </div>
      {state.recovery === undefined || state.busy ? null : <p className="conversation-recovery-hint">发送结果尚未确认，请先重新读取会话。</p>}
    </form>
  </section>;
}
