import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronRight, FileCode2, FilePlus2, Folder, GitBranch, GitCompareArrows, RefreshCw, Save, X } from 'lucide-react';
import { lazy, Suspense, useState } from 'react';
import { fetchFileDiff, fetchFileTree, fetchWorkspaceChanges, readWorkspaceFile, saveWorkspaceFile, type FileDocument } from '../../api/workspace.ts';
import { useSession } from '../../session/SessionContext.tsx';
import { isDirty, useEditorSession, type EditorDraft } from './editorSession.ts';
const MonacoEditor = lazy(() => import('./MonacoEditor.tsx'));

type Comparison = { kind: 'git' | 'conflict'; path: string; original: string; modified: string; draftId?: string; disk?: FileDocument };
function FileTree({ paths, prefix = '', selected, open }: { paths: string[]; prefix?: string; selected?: string; open: (path: string) => void }) {
  const groups = new Map<string, string[]>();
  const files: string[] = [];
  for (const path of paths) {
    const rest = path.slice(prefix.length), slash = rest.indexOf('/');
    if (slash < 0) files.push(path);
    else { const name = rest.slice(0, slash); groups.set(name, [...(groups.get(name) ?? []), path]); }
  }
  return <ul className="code-tree">{[...groups].map(([name, children]) => <li key={name}><details open={prefix === ''}><summary><ChevronRight size={12} aria-hidden="true" /><Folder size={14} aria-hidden="true" />{name}</summary><FileTree paths={children} prefix={`${prefix}${name}/`} selected={selected} open={open} /></details></li>)}{files.map(path => <li key={path}><button type="button" className={selected === path ? 'is-selected' : ''} title={path} onClick={() => open(path)}><FileCode2 size={14} aria-hidden="true" /><span>{path.slice(prefix.length)}</span></button></li>)}</ul>;
}

export function RepositoryEditorPanel({ projectId, localPath, onConnection }: { projectId: string; localPath: string; onConnection: () => void }) {
  const { session } = useSession();
  const state = useEditorSession(session!.signal, projectId);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('');
  const [newPath, setNewPath] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [sidebar, setSidebar] = useState<'files' | 'changes'>('files');
  const [closeId, setCloseId] = useState<string | null>(null);
  const writable = session!.identity.membership.role !== 'viewer';
  const combine = (signal: AbortSignal) => AbortSignal.any([signal, session!.signal]);
  const tree = useQuery({ queryKey: ['editor-tree', session!.generation, projectId, localPath], retry: false,
    queryFn: ({ signal }) => fetchFileTree(projectId, combine(signal)) });
  const changes = useQuery({ queryKey: ['editor-changes', session!.generation, projectId, localPath], retry: false,
    queryFn: ({ signal }) => fetchWorkspaceChanges(projectId, combine(signal)) });
  const draft = state.tabs.find(item => item.id === state.active);
  const stale = Boolean(draft && tree.data && draft.document.workspaceId !== tree.data.workspaceId);
  const log = (message: string) => state.update(current => ({ ...current, events: [`${new Date().toLocaleTimeString('zh-CN')}  ${message}`, ...current.events].slice(0, 40) }));
  async function action(run: () => Promise<void>) {
    if (pending) return;
    setPending(true); setError(null); setCloseId(null);
    try { await run(); } catch (failure) {
      if (!session!.signal.aborted) { const message = failure instanceof Error ? failure.message : '操作失败'; setError(message); log(message); }
    } finally { setPending(false); }
  }
  const select = (id: string) => { state.update(current => ({ ...current, active: id })); setComparison(null); setError(null); setCloseId(null); };
  function opened(document: EditorDraft['document']) {
    const id = `${document.workspaceId}:${document.path}`;
    state.update(current => ({ ...current, active: id, tabs: current.tabs.some(item => item.id === id) ? current.tabs : [...current.tabs, { id, document, content: document.content }] }));
    setComparison(null);
  }
  function open(path: string) {
    if (pending) return;
    const existing = state.tabs.find(item => item.document.workspaceId === tree.data?.workspaceId && item.document.path === path);
    if (existing) { select(existing.id); return; }
    void action(async () => { opened(await readWorkspaceFile(projectId, path, session!.signal)); });
  }
  function create() {
    if (!newPath?.trim() || !tree.data) return;
    const path = newPath.trim();
    if (tree.data.paths.includes(path)) { setError('同名文件已存在，请从文件树打开。'); return; }
    opened({ path, workspaceId: tree.data.workspaceId, content: '', revision: null });
    setNewPath(null);
  }
  async function refresh() {
    setComparison(null);
    await Promise.all([tree.refetch(), changes.refetch()]);
  }
  function save() {
    if (!draft || !writable || stale || !tree.data || pending || !isDirty(draft)) return;
    const current = draft;
    void action(async () => {
      const document = await saveWorkspaceFile(projectId, { workspaceId: current.document.workspaceId, path: current.document.path, revision: current.document.revision, content: current.content }, session!.identity.csrfToken, session!.signal);
      state.update(value => ({ ...value, tabs: value.tabs.map(item => item.id === current.id ? { ...item, document, savedRevision: document.revision } : item) }));
      log(`已手动保存 ${document.path}`);
      await Promise.all([tree.refetch(), changes.refetch(), queryClient.invalidateQueries({ queryKey: ['code-sources', session!.generation, projectId] })]);
    });
  }
  function showDiff(path: string) {
    void action(async () => {
      const diff = await fetchFileDiff(projectId, path, session!.signal);
      const current = state.tabs.find(item => item.document.workspaceId === diff.workspaceId && item.document.path === path);
      setComparison({ kind: 'git', path, original: diff.original, modified: current?.content ?? diff.modified, draftId: current?.id });
    });
  }
  function compareDisk() {
    if (!draft || stale) return;
    const current = draft;
    void action(async () => {
      const disk = await readWorkspaceFile(projectId, current.document.path, session!.signal);
      if (disk.workspaceId !== current.document.workspaceId) throw new Error('仓库或分支已变化，请刷新文件树；原草稿已保留。');
      setComparison({ kind: 'conflict', path: disk.path, original: disk.content, modified: current.content, draftId: current.id, disk });
    });
  }
  function acceptBase() {
    if (!comparison?.disk || !comparison.draftId) return;
    const { disk, draftId } = comparison;
    state.update(current => ({ ...current, tabs: current.tabs.map(item => item.id === draftId ? { ...item, document: disk } : item) }));
    setComparison(null); setError(null);
    log(`已核对 ${disk.path} 的磁盘版本，草稿尚未保存`);
  }
  function close(id: string, discard = false) {
    const current = state.tabs.find(item => item.id === id);
    if (current && isDirty(current) && !discard) { setCloseId(id); return; }
    state.update(value => { const tabs = value.tabs.filter(item => item.id !== id); return { ...value, tabs, active: value.active === id ? tabs.at(-1)?.id ?? null : value.active }; });
    setCloseId(null); setComparison(null);
  }
  const visiblePaths = tree.data?.paths.filter(path => path.toLowerCase().includes(filter.toLowerCase())) ?? [];
  return <div className="code-editor-layout">
    <aside className="code-editor-explorer" aria-label="项目文件">
      <div className="code-explorer-heading"><span>资源管理器</span><div><button type="button" aria-label="新建文件" disabled={!writable || !tree.data || pending} onClick={() => setNewPath('')}><FilePlus2 size={15} /></button><button type="button" aria-label="刷新文件与差异" disabled={pending || tree.isFetching} onClick={() => void action(refresh)}><RefreshCw size={15} /></button></div></div>
      <div className="code-repository-info"><span><GitBranch size={14} />{tree.data?.branch ?? '工作目录'}</span><code title={localPath}>{localPath}</code><button type="button" onClick={onConnection}>管理仓库关联</button></div>
      <div className="code-explorer-switch" aria-label="文件列表视图"><button type="button" aria-pressed={sidebar === 'files'} onClick={() => setSidebar('files')}>文件</button><button type="button" aria-pressed={sidebar === 'changes'} onClick={() => setSidebar('changes')}>变更 {changes.data?.files.length ?? ''}</button></div>
      {newPath !== null && <form className="code-new-file" onSubmit={event => { event.preventDefault(); create(); }}><label htmlFor="new-code-path">新文件相对路径</label><input id="new-code-path" autoFocus placeholder="src/example.ts" value={newPath} onChange={event => setNewPath(event.target.value)} /><div><button type="submit">创建草稿</button><button type="button" onClick={() => setNewPath(null)}>取消</button></div><small>父目录需已存在；保存后写入磁盘。</small></form>}
      {sidebar === 'files' ? <><label className="code-file-filter"><span className="workbench-sr-only">搜索项目文件</span><input placeholder="搜索文件…" value={filter} onChange={event => setFilter(event.target.value)} /></label><div className="code-tree-scroll">{filter ? <ul className="code-tree">{visiblePaths.map(path => <li key={path}><button type="button" title={path} onClick={() => open(path)}><FileCode2 size={14} /><span>{path}</span></button></li>)}</ul> : <FileTree paths={visiblePaths} selected={draft?.document.path} open={open} />}</div>{tree.isPending ? <p className="code-explorer-empty" role="status">正在读取文件…</p> : !visiblePaths.length && <p className="code-explorer-empty">没有匹配的文件</p>}</> : <div className="code-tree-scroll"><p className="code-explorer-empty">点击文件，对照 HEAD 查看差异。来源未记录的改动显示为工作目录变更。</p><ul className="code-tree">{changes.data?.files.map(file => <li key={file.path}><button type="button" onClick={() => showDiff(file.path)} title={file.path}><code>{file.status.trim()}</code><span>{file.path}</span></button></li>)}</ul>{changes.data?.files.length === 0 && <p className="code-explorer-empty">工作目录没有变更</p>}</div>}
      {(tree.error || changes.error) && <p className="code-notice code-notice-error" role="alert">{(tree.error ?? changes.error)?.message}</p>}
    </aside>
    <div className="code-editor-main">
      <div className="code-document-tabs" role="tablist" aria-label="打开的文件">{state.tabs.map(item => <div key={item.id} className={state.active === item.id && !comparison ? 'is-active' : ''}><button type="button" role="tab" id={`file-tab-${state.tabs.indexOf(item)}`} aria-controls="code-document-panel" aria-selected={state.active === item.id && !comparison} tabIndex={state.active === item.id ? 0 : -1} title={item.document.path} onClick={() => select(item.id)} onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const index = event.key === 'Home' ? 0 : event.key === 'End' ? state.tabs.length - 1 : (state.tabs.indexOf(item) + (event.key === 'ArrowLeft' ? -1 : 1) + state.tabs.length) % state.tabs.length; select(state.tabs[index]!.id); document.getElementById(`file-tab-${index}`)?.focus(); } }}><FileCode2 size={14} />{item.document.path.split('/').pop()}{isDirty(item) && <span className="code-dirty" aria-label="未保存" />}</button><button type="button" aria-label={`关闭 ${item.document.path}`} disabled={pending} onClick={() => close(item.id)}><X size={13} /></button></div>)}</div>
      {closeId && <div className="code-inline-confirm" role="alert"><p>此文件有未保存内容。关闭会丢弃该草稿。</p><button type="button" onClick={() => close(closeId, true)}>丢弃草稿并关闭</button><button type="button" onClick={() => setCloseId(null)}>继续编辑</button></div>}
      {error && <div className="code-notice code-notice-error" role="alert">{error}{draft && !stale && <button type="button" disabled={pending} onClick={compareDisk}>对照磁盘版本</button>}</div>}
      {stale && <p className="code-notice" role="status">仓库关联、分支或 HEAD 已变化。此标签保留原草稿，请从文件树重新打开文件核对，再复制需要保留的内容。</p>}
      {pending && <p className="code-operation-status" role="status">正在处理文件…</p>}
      {comparison ? <><div className="code-editor-toolbar"><strong>{comparison.path}</strong><span>{comparison.kind === 'git' ? 'HEAD → 工作目录 / 当前草稿' : '磁盘版本 → 保留的草稿'}</span><button type="button" onClick={() => setComparison(null)}>返回编辑</button></div>{comparison.kind === 'conflict' && <div className="code-inline-confirm"><p>先核对两侧内容。采用磁盘基线会保留右侧草稿，之后仍需手动保存。</p><button type="button" disabled={pending} onClick={acceptBase}>采用磁盘基线，保留草稿</button></div>}<Suspense fallback={<p role="status">正在加载差异编辑器…</p>}><MonacoEditor key={`diff:${comparison.path}`} path={comparison.path} original={comparison.original} value={comparison.modified} readOnly /></Suspense></> : draft ? <div id="code-document-panel" role="tabpanel" aria-labelledby={`file-tab-${state.tabs.indexOf(draft)}`} className="code-document-panel"><div className="code-editor-toolbar"><strong title={draft.document.path}>{draft.document.path}</strong><span>{isDirty(draft) ? '未保存' : draft.savedRevision === draft.document.revision ? '已手动保存' : '磁盘版本'}</span><button type="button" disabled={pending || stale} onClick={compareDisk}>对照磁盘</button><button type="button" disabled={pending || stale} onClick={() => showDiff(draft.document.path)}><GitCompareArrows size={14} />差异</button><button type="button" className="code-save-button" title="保存 (Ctrl/Cmd+S)" disabled={!writable || stale || !tree.data || pending || !isDirty(draft)} onClick={save}><Save size={14} />保存</button></div><Suspense fallback={<p role="status">正在加载代码编辑器…</p>}><MonacoEditor key={draft.id} path={draft.document.path} value={draft.content} readOnly={!writable} onChange={content => state.update(current => ({ ...current, tabs: current.tabs.map(item => item.id === draft.id ? { ...item, content } : item) }))} onSave={save} /></Suspense></div> : <div className="code-editor-empty"><FileCode2 size={38} strokeWidth={1.3} /><h2>打开文件，开始编写</h2><p>从左侧选择文件，或搜索文件路径。<br />保存用 Ctrl / ⌘ + S，差异对照当前 Git HEAD。</p><p>切换项目会保留本次会话的未保存草稿。<br />退出登录或关闭应用前，请先保存。</p></div>}
      <details className="code-operations"><summary>操作记录 <span>{state.events.length}</span></summary>{state.events.length ? <ol>{state.events.map((event, index) => <li key={index}>{event}</li>)}</ol> : <p>当前会话尚无保存记录。Agent 架构解析位于上方标签；命令执行将在编程 Agent 阶段接入。</p>}</details>
    </div>
  </div>;
}
