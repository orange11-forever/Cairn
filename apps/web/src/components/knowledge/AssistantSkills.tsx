import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { importSkill, previewSkill, saveAssistantSettings, fetchAssistantSettings, createAssistant, selectAssistant, type SkillSource } from "../../api/assistantSkills.ts";
import { useProjectConversations } from "./ProjectConversationsContext.tsx";
import { ApiError } from "../../api/errors.ts";

export function AssistantSkills({ projectId, csrfToken, sessionSignal }: { projectId: string; csrfToken: string; sessionSignal: AbortSignal }) {
  const state = useProjectConversations();
  const request = useRef<AbortController | null>(null);
  const [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const operation = useMutation({ mutationFn: (run: () => Promise<void>) => run(), retry: false, networkMode: "always", gcTime: 0 });
  useEffect(() => () => request.current?.abort(), []);
  if (state === null) return null;
  const config = state.assistant.data;
  const defaultModel = state.model.data?.models.find(item => item.id === state.model.data?.defaultModelId);
  const editing = state.assistantDraft ?? (config === undefined ? null : { assistantId: config.id ?? null, expectedRevision: config.revision, name: config.name, instructions: config.instructions, enabledSkillIds: config.enabledSkillIds, modelId: config.modelId ?? null });
  const changedAssistant = editing !== null && editing.assistantId !== (config?.id ?? null);
  const switchingDisabled = operation.isPending || state.busy || state.assistantNeedsReload || state.assistantDraft !== null || config === undefined || state.assistant.isFetching || state.assistants.isFetching || state.assistants.isError;
  const source = state.importSource;
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    const signal = AbortSignal.any([controller.signal, sessionSignal]); setError(null); setNotice(null);
    try { await operation.mutateAsync(() => action(signal)); } catch (failure) { if (!signal.aborted) { if (failure instanceof ApiError && failure.status === 409 && failure.code === "skill_import_changed") state!.setPendingImport(null); setError(failure instanceof Error ? failure.message : "配置暂时无法保存，请重读后恢复。"); } }
  }
  async function fileChanged(file: File | undefined) {
    if (file === undefined) return;
    try {
      const zip = file.name.toLowerCase().endsWith(".zip");
      if (file.size > (zip ? 262144 : 65536)) throw new Error("文件超过技能导入大小限制。");
      const bytes = new Uint8Array(await file.arrayBuffer());
      const selected: SkillSource = zip ? { type: "zip", fileName: file.name, contentBase64: btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join("")) } : { type: "markdown", fileName: file.name, content: new TextDecoder("utf-8", { fatal: true }).decode(bytes) };
      state!.setImportMode(selected.type); state!.setImportSource(selected); state!.setImportPreview(null); setError(null);
    } catch { setError("文件必须是有界 UTF-8 SKILL.md 或单个 ZIP 技能包。"); }
  }
  return <details className="assistant-skills"><summary><span>助手与技能</span><span className="assistant-current-name" title={config?.name}>{config?.name ?? "岑宁"}</span></summary><div className="assistant-skills-content">
    <div className="assistant-profile-controls">
      <label>当前助手<select aria-label="当前助手" value={config?.id ?? ""} disabled={switchingDisabled} onChange={event => { const assistantId = event.target.value; if (!assistantId || config === undefined) return; void run(async signal => { state.setAssistantNeedsReload(true); const saved = await selectAssistant({ projectId, assistantId, expectedRevision: config.revision, csrfToken, signal }); signal.throwIfAborted(); state.applyAssistant(saved); void state.assistants.refetch(); state.setAssistantNeedsReload(false); setNotice(`已切换到${saved.name}，后续回答使用该助手。`); }); }}>
        {config?.id == null ? <option value="">{config?.name ?? "岑宁"}</option> : !state.assistants.data?.items.some(item => item.id === config.id) ? <option value={config.id}>{config.name}</option> : null}
        {state.assistants.data?.items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <button type="button" disabled={switchingDisabled || (state.assistants.data?.items.length ?? 0) >= 20} onClick={() => void run(async signal => { state.setAssistantNeedsReload(true); const saved = await createAssistant({ projectId, csrfToken, signal, body: { expectedRevision: config!.revision, name: `助手 ${Math.max(state.assistants.data?.items.length ?? 0, 1) + 1}`, instructions: "", enabledSkillIds: [], modelId: null } }); signal.throwIfAborted(); state.applyAssistant(saved); void state.assistants.refetch(); state.setAssistantNeedsReload(false); setNotice("新助手已创建并选用，可继续编辑名称、模型、行为和技能。"); })}>新建助手</button>
    </div>
    {state.assistantDraft !== null ? <p>请先保存或取消编辑，再切换或新建助手。</p> : null}
    {state.assistantNeedsReload && !operation.isPending ? <p role="status">助手切换或创建结果尚未确认，请先重新读取助手与技能。</p> : null}
    {changedAssistant ? <p role="alert">当前助手已在别处切换，未保存编辑仍保留。请取消编辑后再选择要修改的助手。</p> : null}
    <p>技能只提供只读指导，不执行脚本、工具或项目写入。</p>
    {editing === null ? <p role="status">正在读取助手配置…</p> : <form onSubmit={event => { event.preventDefault(); void run(async signal => { const { assistantId, ...body } = editing; if (assistantId !== (config?.id ?? null)) return; const saved = await saveAssistantSettings({ projectId, csrfToken, signal, body }); signal.throwIfAborted(); state.applyAssistant(saved); void state.assistants.refetch(); state.setAssistantDraft(null); setNotice("助手配置已保存。"); }); }}>
      <fieldset disabled={operation.isPending || state.busy || state.assistantNeedsReload}>
      <label>助手名称<input aria-label="助手名称" maxLength={60} value={editing.name} onChange={event => state.setAssistantDraft({ ...editing, name: event.target.value })} /></label>
      <label>回答模型<select aria-label="回答模型" value={editing.modelId ?? ""} disabled={state.model.isPending || state.model.isError} onChange={event => state.setAssistantDraft({ ...editing, modelId: event.target.value || null })}>
        <option value="">服务端默认{defaultModel ? `（${defaultModel.name}）` : "（尚未配置）"}</option>
        {editing.modelId && !state.model.data?.models.some(item => item.id === editing.modelId) ? <option value={editing.modelId}>已不可用（{editing.modelId}）</option> : null}
        {state.model.data?.models.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select><small>保存后用于下一轮回答，已有回答保留原模型记录。</small></label>
      <label>行为说明<textarea aria-label="行为说明" maxLength={2000} rows={3} value={editing.instructions} onChange={event => state.setAssistantDraft({ ...editing, instructions: event.target.value })} /></label>
      <fieldset><legend>启用只读技能</legend>{state.skills.data?.items.map(item => <label className="assistant-skill-option" key={item.id}><input type="checkbox" aria-label={`启用：${item.name}`} disabled={!item.runnable} checked={editing.enabledSkillIds.includes(item.id)} onChange={event => state.setAssistantDraft({ ...editing, enabledSkillIds: event.target.checked ? [...editing.enabledSkillIds, item.id] : editing.enabledSkillIds.filter(id => id !== item.id) })} /><span>{item.name}<small>{item.description}{!item.runnable ? ` · ${item.warnings.join("；")}` : ""}</small></span></label>)}</fieldset>
      <div className="assistant-skill-actions"><button disabled={operation.isPending || changedAssistant} type="submit">保存助手配置</button><button type="button" onClick={() => state.setAssistantDraft(null)}>取消编辑</button></div>
      </fieldset>
    </form>}
    <button type="button" disabled={operation.isPending} onClick={() => void run(async signal => { const current = await fetchAssistantSettings({ projectId, signal }); signal.throwIfAborted(); state.applyAssistant(current); if (state.assistantDraft !== null && state.assistantDraft.assistantId === (current.id ?? null)) state.setAssistantDraft({ ...state.assistantDraft, expectedRevision: current.revision }); await Promise.all([state.skills.refetch(), state.model.refetch(), state.assistants.refetch({ throwOnError: true })]); signal.throwIfAborted(); state.setAssistantNeedsReload(false); setNotice("配置已重新读取，未保存编辑仍保留。"); })}>重新读取助手与技能</button>
    {state.skills.isError || state.assistant.isError || state.assistants.isError ? <p role="alert">助手配置或技能目录暂时无法读取，请重读后再发送。</p> : null}
    <fieldset disabled={operation.isPending || state.pendingImport !== null}><legend>导入外部技能</legend>
      <label>导入来源<select aria-label="导入来源" value={state.importMode} onChange={event => { state.setImportMode(event.target.value as SkillSource["type"]); state.setImportSource(event.target.value === "github" ? { type: "github", url: "" } : null); state.setImportPreview(null); }}><option value="markdown">SKILL.md 文件</option><option value="zip">ZIP 技能包</option><option value="github">GitHub 链接</option></select></label>
      {source?.type === "github" ? <><label>GitHub 地址<input aria-label="GitHub 地址" value={source.url} onChange={event => { state.setImportSource({ ...source, url: event.target.value }); state.setImportPreview(null); }} /></label><label>文件路径（可选）<input aria-label="文件路径（可选）" value={source.path ?? ""} onChange={event => { state.setImportSource({ ...source, path: event.target.value || undefined }); state.setImportPreview(null); }} /></label><label>分支或提交（可选）<input aria-label="分支或提交（可选）" value={source.ref ?? ""} onChange={event => { state.setImportSource({ ...source, ref: event.target.value || undefined }); state.setImportPreview(null); }} /></label></> : <label>选择 SKILL.md 或 ZIP<input aria-label="选择 SKILL.md 或 ZIP" type="file" accept=".md,.zip" onChange={event => void fileChanged(event.target.files?.[0])} /></label>}
      <button type="button" disabled={source === null || (source.type === "github" && !source.url.trim())} onClick={() => void run(async signal => { const result = await previewSkill({ projectId, csrfToken, signal, source: source! }); signal.throwIfAborted(); state.setImportPreview(result); setNotice("预览完成；导入后仍须手动启用。"); })}>预览技能</button>
    </fieldset>
    {state.importPreview === null ? null : <section className="skill-import-preview" aria-label="技能导入预览"><h3>{state.importPreview.name}</h3><p>{state.importPreview.description}</p><p>来源：{state.importPreview.sourceType} · {state.importPreview.runnable ? "可作为只读指导启用" : "依赖不受支持，不能启用"}</p>{state.importPreview.warnings.map(warning => <p key={warning}>{warning}</p>)}<details><summary>查看技能正文与参考资源</summary><pre>{state.importPreview.body}</pre>{state.importPreview.resources.map(item => <pre key={item.path}>{item.path}{"\n"}{item.content}</pre>)}</details></section>}
    {state.importPreview === null && state.pendingImport === null ? null : <button type="button" disabled={operation.isPending} onClick={() => void run(async signal => {
      const input = state.pendingImport ?? { id: crypto.randomUUID(), source: state.importSource!, expectedDigest: state.importPreview!.digest };
      state.setPendingImport(input);
      await importSkill({ projectId, csrfToken, signal, body: input }); signal.throwIfAborted();
      state.setPendingImport(null); state.setImportPreview(null); await state.skills.refetch(); setNotice("技能已导入，尚未启用。请勾选并保存助手配置。");
    })}>{state.pendingImport === null ? "确认导入技能" : "重新确认导入结果（同一请求）"}</button>}
    {operation.isPending ? <p role="status">正在处理助手配置或技能…</p> : null}{error === null ? null : <p role="alert">{error}</p>}{notice === null ? null : <p role="status">{notice}</p>}
  </div></details>;
}
