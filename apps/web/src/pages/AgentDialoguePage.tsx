import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/errors.ts";
import { fetchAssistants } from "../api/assistantSkills.ts";
import { fetchKnowledgeAnswerModel } from "../api/knowledgeConversations.ts";
import { applyAgentDialogue, fetchAgentDialogueOperation, fetchAgentDialogueOperations, previewAgentDialogue, type DialogueAgent, type DialoguePreview, type DialogueRequest } from "../api/agentDialogue.ts";
import type { OperationPage, ProjectOperation } from "../api/projectOperations.ts";
import { projectPath } from "../app/projectRoutes.ts";
import { codingDispatch } from "../components/code/codingDispatch.ts";
import { AssistantAvatar } from "../components/knowledge/AssistantAvatar.tsx";
import { OperationDetails, SavedOperation } from "../components/projects/ProjectOperations.tsx";
import { CairnLoader } from "../components/trail/CairnLoader.tsx";
import { ThinkingStones } from "../components/trail/ThinkingStones.tsx";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { useProjectQuery, useProjectsQuery } from "../queries/projects.ts";
import { useSession } from "../session/SessionContext.tsx";

type Message = { id: string; target: string; projectName: string; role: "user" | "assistant"; text: string; result?: ProjectOperation };

export function AgentDialoguePage() {
  const { projectId, assistantId } = useParams<{projectId: string; assistantId: string}>();
  const { session } = useSession();
  if (!projectId || !assistantId) return <Navigate to="/projects" replace />;
  if (!session) return null;
  return <Dialogue key={`${session.generation}:${session.identity.organization.id}:${session.identity.user.id}:${projectId}:${assistantId}`}
    agent={{originProjectId: projectId, assistantId: assistantId === "builtin" ? null : assistantId}}
    ownerId={session.identity.user.id} organizationId={session.identity.organization.id} csrfToken={session.identity.csrfToken} signal={session.signal} />;
}

function Dialogue({agent, ownerId, organizationId, csrfToken, signal}: {agent: DialogueAgent; ownerId: string; organizationId: string; csrfToken: string; signal: AbortSignal}) {
  const [params, setParams] = useSearchParams();
  const target = params.get("target") || agent.originProjectId;
  const [messages, setMessages] = useState<Message[]>([]);
  const [locked, setLocked] = useState(false);
  const catalog = useQuery({queryKey: ["dialogue-agent", organizationId, ownerId, agent.originProjectId],
    queryFn: ({signal: querySignal}) => fetchAssistants({projectId: agent.originProjectId, signal: AbortSignal.any([signal, querySignal])}), retry: false});
  const models = useQuery({queryKey: ["dialogue-models", organizationId, ownerId, agent.originProjectId],
    queryFn: ({signal: querySignal}) => fetchKnowledgeAnswerModel({projectId: agent.originProjectId, signal: AbortSignal.any([signal, querySignal])}), retry: false});
  const project = useProjectQuery(organizationId, target, signal);
  const projects = useProjectsQuery(organizationId, signal);
  const selected = agent.assistantId === null ? {id: null, name: "岑宁", avatarDataUrl: null, modelId: null} : catalog.data?.items.find(item => item.id === agent.assistantId);
  const model = models.data?.models.find(item => item.id === (selected?.modelId ?? models.data?.defaultModelId));
  const error = catalog.error ?? project.error ?? models.error;
  const changeTarget = (projectId: string) => { setParams(projectId === agent.originProjectId ? {} : {target: projectId}, {replace: true}); };
  function add(role: Message["role"], text: string, result?: ProjectOperation) {
    const projectName = result?.action.type === "create_project" ? result.action.name : project.data?.name ?? target;
    setMessages(values => [...values, {id: crypto.randomUUID(), target: result?.projectId ?? target, projectName, role, text, result}]);
  }
  return <section className="agent-dialogue-page" aria-labelledby="agent-dialogue-title">
    <Link className="agent-dialogue-back" to={projectPath(agent.originProjectId, "agents")}>返回智能体</Link>
    {catalog.isPending || project.isPending || models.isPending ? <CairnLoader label="正在读取智能体对话…" size="sm" /> : error ? <p role="alert">{error.message}</p> : !selected ? <p role="alert">此智能体不存在或不属于当前账号，请返回智能体重新选择。</p> : <>
      <header className="agent-dialogue-header"><AssistantAvatar name={selected.name} avatarDataUrl={selected.avatarDataUrl}/><div><h1 id="agent-dialogue-title">与{selected.name}对话</h1><p>{model?.name ?? selected.modelId ?? "默认模型尚未配置"} · 项目管理 Agent</p></div></header>
      <p className="project-analysis-scope">描述项目目标或任务调整，先预览再确认。未确认的对话仅保留在本页；已确认的操作保存在个人操作记录中。</p>
      <div className="agent-dialogue-target"><label>当前工作项目<select aria-label="当前工作项目" value={target} disabled={locked} onChange={event => changeTarget(event.target.value)}>
        {!projects.data?.pages.some(page => page.items.some(item => item.id === target)) && <option value={target}>{project.data?.name ?? target}</option>}
        {projects.data?.pages.flatMap(page => page.items).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label><Link to={projectPath(target, "tasks")}>打开项目任务</Link>{projects.hasNextPage && <button type="button" disabled={locked || projects.isFetchingNextPage} onClick={() => void projects.fetchNextPage()}>读取更多项目</button>}</div>
      {projects.error && <p role="alert">{projects.error.message}</p>}
      <div className="agent-dialogue-messages" role="log" aria-label="智能体对话消息" aria-live="polite">
        {messages.length === 0 && <p className="agent-dialogue-welcome">我是{selected.name}。可以先告诉我：“创建一个名为网站改版的项目”，或描述当前项目需要处理的任务。</p>}
        {messages.map(message => <article className={`agent-dialogue-message agent-dialogue-message-${message.role}`} key={message.id}><small>{message.role === "user" ? "你" : selected.name} · {message.projectName}</small><p>{message.text}</p>{message.result && <SavedOperation value={message.result}/>}</article>)}
      </div>
      <DialogueComposer key={`${target}:${csrfToken}`} agent={agent} targetProjectId={target} ownerId={ownerId} organizationId={organizationId} csrfToken={csrfToken} signal={signal}
        historyMessages={messages.filter(message => message.target === target).slice(-12).map(({role, text}) => ({role, text}))} onBusy={setLocked} onMessage={add} onCreated={changeTarget}/>
    </>}
  </section>;
}

function DialogueComposer({agent, targetProjectId, ownerId, organizationId, csrfToken, signal, historyMessages, onBusy, onMessage, onCreated}: {
  historyMessages: {role: "user" | "assistant"; text: string}[];
  agent: DialogueAgent; targetProjectId: string; ownerId: string; organizationId: string; csrfToken: string; signal: AbortSignal;
  onBusy: (value: boolean) => void; onMessage: (role: Message["role"], text: string, result?: ProjectOperation) => void; onCreated: (value: string) => void;
}) {
  const queryClient = useQueryClient();
  const [intent, setIntent] = useState("");
  const [preview, setPreview] = useState<DialoguePreview | null>(null);
  const [history, setHistory] = useState<OperationPage | null>(null);
  const [notice, setNotice] = useState("");
  const storageKey = `cairn.pending-agent-operation:${organizationId}:${ownerId}:${agent.originProjectId}:${agent.assistantId ?? "builtin"}:${targetProjectId}`;
  const [storage] = useState(() => { try { return {id: sessionStorage.getItem(storageKey), error: ""}; } catch { return {id: null, error: "会话存储不可用，请启用后刷新页面再确认执行。"}; } });
  const [storageError, setStorageError] = useState(storage.error);
  const [pendingId, setPendingId] = useState<string | null>(storage.id);
  const [uncertain, setUncertain] = useState(storage.id !== null);
  const [submission, setSubmission] = useState<DialogueRequest | null>(null);
  const mounted = useRef(true), inFlight = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const current = () => mounted.current && !signal.aborted;
  const generation = useAbortableAction((text: string, requestSignal: AbortSignal) => previewAgentDialogue({agent, targetProjectId, intent: text, history: historyMessages, csrfToken, signal: requestSignal}), signal);
  const apply = useAbortableAction(async (payload: DialogueRequest, requestSignal: AbortSignal) => {
    try { return await applyAgentDialogue({payload, csrfToken, signal: requestSignal}); }
    catch (error) {
      if (current() && !requestSignal.aborted) {
        const definite = error instanceof ApiError && error.kind === "http" && error.status !== null && error.status < 500 && error.code !== "operation_conflict";
        if (definite) { clearPending(); setSubmission(null); setPreview(null); setNotice("操作未执行。请重新生成建议后确认。"); }
        else { setUncertain(true); setNotice("提交结果尚未确认，请先查询结果。继续复用同一个操作编号，避免重复写入。"); }
      }
      throw error;
    }
  }, signal);
  const lookup = useAbortableAction(async (id: string, requestSignal: AbortSignal) => {
    try { return await fetchAgentDialogueOperation({agent, targetProjectId, operationId: id, signal: requestSignal}); }
    catch (error) { if (error instanceof ApiError && error.status === 404 && error.code === "not_found") return null; throw error; }
  }, signal);
  const records = useAbortableAction((cursor: string | null, requestSignal: AbortSignal) => fetchAgentDialogueOperations({agent, targetProjectId, cursor, signal: requestSignal}), signal);
  const busy = generation.pending || apply.pending || lookup.pending;
  const locked = busy || uncertain || submission !== null || signal.aborted;
  useEffect(() => { onBusy(busy || uncertain || submission !== null); return () => onBusy(false); }, [busy, uncertain, submission, onBusy]);
  function clearPending() {
    try { sessionStorage.removeItem(storageKey); } catch { setStorageError("无法清除本机操作编号，请启用存储后刷新页面。已确认记录仍可查询。"); }
    setPendingId(null); setUncertain(false);
  }
  async function accept(result: ProjectOperation) {
    if (!current()) return;
    clearPending(); setSubmission(null); setPreview(null); apply.reset(); lookup.reset();
    onMessage("assistant", result.action.type === "create_project" ? "项目已创建。我们继续在这个项目里管理任务。" : "操作已确认并执行。", result);
    setNotice("操作已执行并保存记录。");
    void queryClient.invalidateQueries({queryKey: ["projects", organizationId]});
    if (result.action.type === "create_project") onCreated(result.projectId);
  }
  async function generate() {
    if (locked || !intent.trim()) return;
    const text = intent.trim(); setPreview(null); setNotice(""); apply.reset();
    onMessage("user", text); setIntent("");
    const value = await generation.run(text);
    if (value && current()) { setPreview(value); onMessage("assistant", value.preview.suggestion.explanation); }
  }
  async function confirm() {
    if (inFlight.current || busy || uncertain || signal.aborted || storageError || (!preview && !submission)) return;
    const payload: DialogueRequest = submission ?? {operationId: pendingId ?? crypto.randomUUID(), confirmed: true, preview: structuredClone(preview!)};
    try { sessionStorage.setItem(storageKey, payload.operationId); } catch { setStorageError("无法保存操作编号，请启用会话存储后再确认执行。"); return; }
    inFlight.current = true; setPendingId(payload.operationId); setSubmission(payload); setNotice("");
    try { const value = await apply.run(payload); if (value) await accept(value); } finally { inFlight.current = false; }
  }
  async function query() {
    if (!pendingId) return;
    const value = await lookup.run(pendingId);
    if (value) await accept(value);
    else if (value === null && current()) { setUncertain(false); setNotice(submission ? "尚未找到执行记录，可以重新提交同一个操作编号。" : "尚未找到执行记录。请重新生成建议，确认时继续复用原操作编号。"); }
  }
  async function loadHistory(more = false) {
    const page = await records.run(more ? history?.nextCursor ?? null : null);
    if (page && current()) setHistory({items: more ? [...(history?.items ?? []), ...page.items] : page.items, nextCursor: page.nextCursor});
  }
  const operation = preview?.preview;
  const taskPreview = operation && "snapshot" in operation ? operation : undefined;
  const dispatch = taskPreview ? codingDispatch(taskPreview, ownerId) : null;
  const canExecute = operation && ("canExecute" in operation ? operation.canExecute : true);
  return <div className="agent-dialogue-composer">
    <form className="operation-intent" onSubmit={event => { event.preventDefault(); void generate(); }}>
      <label htmlFor="agent-dialogue-intent">给这个 Agent 发消息</label><textarea id="agent-dialogue-intent" value={intent} maxLength={2000} rows={3} disabled={locked} onChange={event => { setIntent(event.target.value); setPreview(null); }} placeholder="例如：创建一个名为网站改版的项目"/>
      <button className="btn-primary" disabled={locked || !intent.trim()} type="submit">{generation.pending ? <ThinkingStones>正在思考…</ThinkingStones> : "发送"}</button>
      {generation.pending && <button type="button" onClick={generation.cancel}>停止生成</button>}
    </form>
    {[generation, apply, lookup, records].map((item, index) => item.state.phase === "error" && <div className="project-analysis-error" role="alert" key={index}><p>{item.state.error.message}</p>{item.state.error.traceId && <small>请求编号：{item.state.error.traceId}</small>}</div>)}
    {storageError && <p role="alert">{storageError}</p>}{notice && <p role="status">{notice}</p>}
    {uncertain && !notice && <p role="status">上次提交结果尚未确认，请先查询操作结果。</p>}
    {pendingId && <div className="project-structure-actions"><button type="button" disabled={busy || signal.aborted} onClick={() => void query()}>查询操作结果</button>{submission && !uncertain && <button type="button" disabled={busy || signal.aborted} onClick={() => void confirm()}>重新提交同一操作</button>}</div>}
    {operation?.suggestion.action && <section className="plan-confirmation" aria-label="确认智能体操作"><h2>待确认操作</h2><p>{operation.suggestion.explanation}</p><OperationDetails action={operation.suggestion.action} snapshot={taskPreview?.snapshot}/><p className="project-analysis-scope">{dispatch ? "到代码工作区核对仓库、模型和任务内容，授权后开始；命令仍需逐条确认。" : "以上变更尚未执行。核对后确认，才会写入真实项目。"}</p>
      {canExecute ? dispatch ? <Link className="btn-primary" to={projectPath(targetProjectId, "code")} state={{codingDispatch: dispatch}}>前往代码工作区确认派发</Link> : <button type="button" className="btn-primary" disabled={locked || Boolean(storageError)} onClick={() => void confirm()}>{apply.pending ? "正在执行…" : "确认执行此操作"}</button> : <p>当前为只读访问，执行需要项目写入权限。</p>}
    </section>}
    <div className="plan-history"><button type="button" disabled={records.pending || signal.aborted} onClick={() => void loadHistory()}>查看此 Agent 在当前项目的已确认记录</button>{history && <div><h3>已确认的操作记录</h3>{history.items.length === 0 && <p>此 Agent 在当前项目还没有已确认操作。</p>}{history.items.map(item => <SavedOperation key={item.operationId} value={item}/>)}{history.nextCursor && <button type="button" disabled={records.pending} onClick={() => void loadHistory(true)}>加载更多操作</button>}</div>}</div>
  </div>;
}
