import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { IdentityContext } from "../../api/auth.ts";
import { ApiError } from "../../api/errors.ts";
import { applyProjectCreation, fetchProjectCreation, previewProjectCreation, type CreationPreview, type CreationRequest } from "../../api/projectCreation.ts";
import type { ProjectOperation } from "../../api/projectOperations.ts";
import { projectPath } from "../../app/projectRoutes.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";
import { projectKeys } from "../../queries/projects.ts";
import { ThinkingStones } from "../trail/ThinkingStones.tsx";

export function ProjectCreation({ identity, signal, onBusy }: {
  identity: IdentityContext; signal: AbortSignal; onBusy: (busy: boolean) => void;
}) {
  const client = useQueryClient();
  const inputId = useId();
  const [intent, setIntent] = useState("");
  const [preview, setPreview] = useState<CreationPreview | null>(null);
  const [saved, setSaved] = useState<ProjectOperation | null>(null);
  const [submission, setSubmission] = useState<CreationRequest | null>(null);
  const [notice, setNotice] = useState("");
  const [refreshFailed, setRefreshFailed] = useState(false);
  const storageKey = `cairn.pending-creation:${identity.user.id}:${identity.organization.id}`;
  const [stored] = useState(() => {
    try { return { id: sessionStorage.getItem(storageKey), error: "" }; }
    catch { return { id: null, error: "会话存储不可用，请启用后再确认创建。" }; }
  });
  const [pendingId, setPendingId] = useState(stored.id);
  const [uncertain, setUncertain] = useState(stored.id !== null);
  const [storageError, setStorageError] = useState(stored.error);
  const inFlight = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const current = () => mounted.current && !signal.aborted;
  const generation = useAbortableAction((text: string, requestSignal: AbortSignal) => previewProjectCreation({
    organizationId: identity.organization.id, intent: text, csrfToken: identity.csrfToken, signal: requestSignal,
  }), signal);
  const apply = useAbortableAction(async (payload: CreationRequest, requestSignal: AbortSignal) => {
    try { return await applyProjectCreation({ payload, csrfToken: identity.csrfToken, signal: requestSignal }); }
    catch (error) {
      if (current() && !requestSignal.aborted) {
        const definite = error instanceof ApiError && error.kind === "http" && error.status !== null
          && error.status < 500 && error.status !== 408 && error.code !== "operation_conflict";
        if (definite) { clearPending(); setSubmission(null); setNotice("项目未创建。请检查权限并重新生成预览。"); }
        else { setUncertain(true); setNotice("创建结果尚未确认，请先查询结果，避免重复创建项目。"); }
      }
      throw error;
    }
  }, signal);
  const lookup = useAbortableAction(async (operationId: string, requestSignal: AbortSignal) => {
    try { return await fetchProjectCreation({ operationId, signal: requestSignal }); }
    catch (error) { if (error instanceof ApiError && error.status === 404 && error.code === "not_found") return null; throw error; }
  }, signal);
  const busy = apply.pending || lookup.pending;
  const locked = busy || uncertain || submission !== null || signal.aborted;
  useEffect(() => { onBusy(busy || uncertain || submission !== null); return () => onBusy(false); }, [busy, uncertain, submission, onBusy]);

  function clearPending() {
    try { sessionStorage.removeItem(storageKey); }
    catch { setStorageError("无法清除操作编号。结果已保留，请启用会话存储后刷新页面。"); }
    setPendingId(null); setUncertain(false);
  }
  async function refresh() {
    try {
      await client.invalidateQueries({ queryKey: projectKeys.list(identity.organization.id) }, { throwOnError: true });
      if (current()) setRefreshFailed(false);
    } catch { if (current()) setRefreshFailed(true); }
  }
  async function accept(result: ProjectOperation) {
    if (!current()) return;
    clearPending(); setSubmission(null); setPreview(null); setSaved(result); setNotice("项目已创建。");
    apply.reset(); lookup.reset();
    await refresh();
  }
  async function generate() {
    if (locked || !intent.trim()) return;
    setPreview(null); setSaved(null); setNotice(""); apply.reset();
    const result = await generation.run(intent.trim());
    if (result && current()) setPreview(result);
  }
  async function confirm() {
    if (inFlight.current || busy || uncertain || signal.aborted || storageError || (!preview && !submission)) return;
    const payload = submission ?? { operationId: pendingId ?? crypto.randomUUID(), confirmed: true as const, preview: structuredClone(preview!) };
    try { sessionStorage.setItem(storageKey, payload.operationId); }
    catch { setStorageError("无法保存操作编号，请启用会话存储后再创建项目。"); return; }
    inFlight.current = true; setPendingId(payload.operationId); setSubmission(payload); setNotice("");
    try { const result = await apply.run(payload); if (result) await accept(result); }
    finally { inFlight.current = false; }
  }
  async function query() {
    if (!pendingId) return;
    const result = await lookup.run(pendingId);
    if (result) await accept(result);
    else if (result === null && current()) {
      setUncertain(false);
      setNotice(submission ? "尚未找到创建记录。可以重新提交同一个操作。" : "尚未找到创建记录。请重新生成预览，确认时会继续使用原操作编号。");
    }
  }
  const action = preview?.suggestion.action;
  return <section className="project-analysis project-operations" aria-label="助手创建项目">
    <header><div><h3>创建项目</h3><p>告诉岑宁项目名称和用途，核对预览后创建到「{identity.organization.name}」。</p></div></header>
    <form className="operation-intent" onSubmit={event => { event.preventDefault(); void generate(); }}>
      <label htmlFor={inputId}>描述要创建的项目</label>
      <textarea id={inputId} rows={3} maxLength={2000} value={intent} disabled={locked || generation.pending}
        placeholder="例如：创建一个叫“发布验收”的项目，用于跟进测试和发布准备"
        onChange={event => { setIntent(event.target.value); setPreview(null); }} />
      <button className="btn-primary" type="submit" disabled={locked || generation.pending || !intent.trim()}>{generation.pending ? <ThinkingStones>正在整理项目…</ThinkingStones> : "生成项目预览"}</button>
      {generation.pending && <button type="button" onClick={generation.cancel}>停止生成</button>}
    </form>
    {[generation, apply, lookup].map((request, index) => request.state.phase === "error" && <div role="alert" className="project-analysis-error" key={index}>
      <p>{request.state.error.message}</p>{request.state.error.traceId && <small>请求编号：{request.state.error.traceId}</small>}
    </div>)}
    {storageError && <p role="alert">{storageError}</p>}
    {notice && <p role="status">{notice}</p>}
    {uncertain && !notice && <p role="status">上次创建结果尚未确认，请先查询结果。</p>}
    {pendingId && <div className="project-structure-actions">
      <button type="button" disabled={busy || signal.aborted} onClick={() => void query()}>查询创建结果</button>
      {submission && !uncertain && <button type="button" disabled={busy || signal.aborted} onClick={() => void confirm()}>重新提交同一创建</button>}
    </div>}
    {preview && !signal.aborted && <div className="plan-confirmation" role="group" aria-label="确认创建项目">
      <p>{preview.suggestion.explanation}</p>
      {action?.type === "create_project" && <><dl className="operation-details"><dt>项目名称</dt><dd>{action.name}</dd><dt>项目描述</dt><dd>{action.description ?? "未填写"}</dd></dl>
        <p className="project-analysis-scope">组织：{identity.organization.name} · 确认后创建项目，任务可在创建后继续拆分。</p>
        <button className="btn-primary" type="button" disabled={locked || Boolean(storageError)} onClick={() => void confirm()}>确认创建项目</button></>}
    </div>}
    {saved && !signal.aborted && <p><Link to={projectPath(saved.projectId, "tasks")}>打开新项目</Link></p>}
    {refreshFailed && <p role="alert">项目已创建，但列表刷新失败。<button type="button" onClick={() => void refresh()}>刷新项目列表</button></p>}
  </section>;
}
