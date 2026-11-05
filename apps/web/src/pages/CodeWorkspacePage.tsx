import { useQuery } from '@tanstack/react-query';
import { ChevronRight, Code2, FileCode2, FolderGit2, GitBranch, Layers3, Play, RefreshCw, Settings2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { fetchProject } from '../api/projects.ts';
import { fetchAssistantSettings } from '../api/assistantSkills.ts';
import { fetchKnowledgeAnswerModel } from '../api/knowledgeConversations.ts';
import { analyzeArchitecture, fetchRepositorySources, fetchWorkspace, type ArchitectureAnalysis } from '../api/workspace.ts';
import { ProjectRepository } from '../components/projects/ProjectRepository.tsx';
import { CodingWorkspace } from '../components/code/CodingWorkspace.tsx';
import { ArchitectureGraph } from '../components/code/ArchitectureGraph.tsx';
import { KnowledgeText } from '../components/knowledge/KnowledgeText.tsx';
import { ProjectTrail } from '../components/trail/ProjectTrail.tsx';
import { useAbortableAction } from '../hooks/useAbortableAction.ts';
import { projectKeys } from '../queries/projects.ts';
import { useSession } from '../session/SessionContext.tsx';
import '../../styles/code.css';

export function CodeWorkspacePage() {
  const { projectId } = useParams();
  const { session } = useSession();
  if (!projectId || !session) return null;
  const desktop = Boolean((window as Window & { chrome?: { webview?: unknown } }).chrome?.webview);
  if (!desktop) return <section className="code-page"><h1>代码与架构</h1><p>请在 Cairn 桌面版打开本地代码仓库。</p><Link to="/projects">返回项目</Link></section>;
  return <CodeWorkspace key={`${session.generation}:${projectId}`} projectId={projectId} />;
}

function CodeWorkspace({ projectId }: { projectId: string }) {
  const { session } = useSession();
  const [tab, setTab] = useState<'editor' | 'architecture' | 'connection'>('editor');
  const [storedResult, setResult] = useState<{ value: ArchitectureAnalysis; bindingIdentity: string } | null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const sourcePreview = useRef<HTMLElement>(null);
  const [filter, setFilter] = useState('');
  const combine = (signal: AbortSignal) => AbortSignal.any([signal, session!.signal]);
  const project = useQuery({ queryKey: projectKeys.detail(session!.identity.organization.id, projectId),
    queryFn: ({ signal }) => fetchProject({ projectId, signal: combine(signal) }) });
  const repository = useQuery({ queryKey: ['desktop-workspace', session!.generation, projectId], retry: false,
    queryFn: ({ signal }) => fetchWorkspace(projectId, combine(signal)) });
  const bindingIdentity = JSON.stringify([repository.data?.binding?.localPath, repository.data?.binding?.repository?.id, repository.data?.binding?.account?.id]);
  useEffect(() => { setResult(null); setSourceId(null); }, [bindingIdentity]);
  const assistant = useQuery({ queryKey: ['code-assistant', session!.generation, projectId], retry: false,
    queryFn: ({ signal }) => fetchAssistantSettings({ projectId, signal: combine(signal) }) });
  const models = useQuery({ queryKey: ['code-models', session!.generation, projectId], retry: false,
    queryFn: ({ signal }) => fetchKnowledgeAnswerModel({ projectId, signal: combine(signal) }) });
  const selectedModel = models.data?.models.find(model => model.id === (assistant.data?.modelId ?? models.data?.defaultModelId));
  const sources = useQuery({ queryKey: ['code-sources', session!.generation, projectId, repository.data?.binding?.localPath], retry: false,
    enabled: Boolean(repository.data?.binding), queryFn: ({ signal }) => fetchRepositorySources(projectId, combine(signal)) });
  const result = storedResult?.bindingIdentity === bindingIdentity
    && storedResult.value.snapshot.digest === sources.data?.digest
    && storedResult.value.assistantId === (assistant.data?.id ?? null)
    && storedResult.value.assistantRevision === assistant.data?.revision
    && storedResult.value.model.id === selectedModel?.id
    && !sources.error && !repository.error ? storedResult.value : null;
  useEffect(() => { setSourceId(null); }, [sources.data?.digest]);
  useEffect(() => { if (sourceId) sourcePreview.current?.scrollIntoView?.({ block: 'nearest' }); }, [sourceId]);
  const analyze = useAbortableAction(analyzeArchitecture, session!.signal);
  const snapshot = repository.data?.binding ? result?.snapshot ?? sources.data : undefined;
  const source = snapshot?.sources.find(item => item.id === sourceId);
  const files = snapshot?.sources.filter(item => item.path.toLowerCase().includes(filter.toLowerCase())) ?? [];
  const binding = repository.data?.binding;
  async function run() {
    if (!sources.data || !assistant.data || !session) return;
    setResult(null); setSourceId(null);
    const value = await analyze.run({ projectId, csrfToken: session.identity.csrfToken,
      snapshotDigest: sources.data.digest, assistantId: assistant.data.id ?? null, assistantRevision: assistant.data.revision });
    if (value) setResult({ value, bindingIdentity });
  }
  async function refresh() {
    setResult(null); setSourceId(null); analyze.reset();
    await Promise.all([repository.refetch(), sources.refetch(), assistant.refetch(), models.refetch()]);
  }
  const error = analyze.state.phase === 'error' ? analyze.state.error : sources.error ?? repository.error ?? assistant.error ?? models.error ?? project.error;
  return <section className="code-page" aria-label="项目代码工作台">
    <header className="code-page-header">
      <ProjectTrail organizationId={session!.identity.organization.id} projectId={projectId} trail={[{ label: '代码' }]} />
      <div className="code-project-title"><FolderGit2 size={24} aria-hidden="true" /><div><h1>{project.data?.name ?? '代码工作台'}</h1><p>{binding?.repository?.fullName ?? '本地代码与架构'}</p></div></div>
    </header>
    <div className={`code-workbench${tab === 'editor' ? ' code-workbench-editing' : ''}`}>
      {tab !== 'editor' && <aside className="code-explorer" aria-label="仓库与文件">
        <div className="code-explorer-heading"><span>仓库</span><button type="button" title="刷新源码" aria-label="刷新源码" disabled={analyze.pending || sources.isFetching || !binding} onClick={() => void refresh()}><RefreshCw size={15} aria-hidden="true" /></button></div>
        {binding ? <div className="code-repository-info"><strong>{binding.repository?.fullName ?? project.data?.name}</strong><span><GitBranch size={14} aria-hidden="true" />{sources.data?.branch ?? binding.branch ?? '分离的 HEAD'}</span><code title={binding.localPath}>{binding.localPath}</code></div> : <p className="code-explorer-empty">关联仓库后，查看项目源码与架构。</p>}
        <button className="code-connection-trigger" type="button" onClick={() => setTab('connection')}><Settings2 size={15} aria-hidden="true" />{binding ? '管理仓库关联' : '关联代码仓库'}<ChevronRight size={14} aria-hidden="true" /></button>
        {binding && <>
          <div className="code-explorer-heading"><span>本次分析文件</span><span>{snapshot?.sources.length ?? 0}</span></div>
          <label className="code-file-filter"><span className="workbench-sr-only">筛选分析文件</span><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="筛选文件…" /></label>
          {sources.isFetching && <p className="code-explorer-empty" role="status">正在读取源码…</p>}
          <ul className="code-file-list">{files.map(item => <li key={item.id}><button type="button" className={sourceId === item.id ? 'is-selected' : ''} title={item.path} onClick={() => { setSourceId(item.id); setTab('architecture'); }}><FileCode2 size={15} aria-hidden="true" /><span>{item.path}</span></button></li>)}</ul>
          {snapshot && files.length === 0 && <p className="code-explorer-empty">没有匹配的文件</p>}
        </>}
      </aside>}
      <div className="code-main">
        <div className="code-tabs" role="tablist" aria-label="代码工作区视图" onKeyDownCapture={event => {
          const tabs = ['editor', 'architecture', 'connection'] as const;
          if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
            event.preventDefault(); event.stopPropagation();
            const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (tabs.indexOf(tab) + (event.key === 'ArrowLeft' ? -1 : 1) + 3) % 3]!;
            setTab(next); document.getElementById(`${next}-tab`)?.focus();
          }
        }}>
          <button id="editor-tab" role="tab" tabIndex={tab === 'editor' ? 0 : -1} aria-controls="editor-panel" aria-selected={tab === 'editor'} onClick={() => setTab('editor')}><Code2 size={16} aria-hidden="true" />代码编辑</button>
          <button id="architecture-tab" role="tab" tabIndex={tab === 'architecture' ? 0 : -1} aria-controls="architecture-panel" aria-selected={tab === 'architecture'} onKeyDown={event => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); setTab('connection'); document.getElementById('connection-tab')?.focus(); } }} onClick={() => setTab('architecture')}><Layers3 size={16} aria-hidden="true" />架构解析</button>
          <button id="connection-tab" role="tab" tabIndex={tab === 'connection' ? 0 : -1} aria-controls="connection-panel" aria-selected={tab === 'connection'} onClick={() => setTab('connection')}><GitBranch size={16} aria-hidden="true" />仓库连接</button>
        </div>
        {tab === 'editor' ? <div id="editor-panel" role="tabpanel" aria-labelledby="editor-tab">{binding ? <CodingWorkspace projectId={projectId} localPath={binding.localPath} assistant={assistant.data} modelName={selectedModel?.name} onConnection={() => setTab('connection')} /> : <div className="code-editor-empty"><FolderGit2 size={38} aria-hidden="true" /><h2>连接你的代码仓库</h2><p>关联本地 Git 仓库后，即可搜索、编辑文件和查看差异。</p><button type="button" onClick={() => setTab('connection')}>关联代码仓库</button></div>}</div> : tab === 'connection' ? <div id="connection-panel" role="tabpanel" aria-labelledby="connection-tab" className="code-connection-panel"><ProjectRepository projectId={projectId} canWrite={session!.identity.membership.role !== 'viewer'} initiallyOpen /></div> : <div id="architecture-panel" role="tabpanel" aria-labelledby="architecture-tab" className="code-architecture-panel">
          <div className="code-analysis-heading"><div><h2>读懂项目架构</h2><p>从真实源码出发，梳理技术栈、模块职责与数据流。</p></div><button type="button" className="code-analyze-button" disabled={!sources.data || !assistant.data || !selectedModel || analyze.pending || sources.isFetching} onClick={() => void run()}><Play size={15} aria-hidden="true" />{analyze.pending ? '正在解析…' : result ? '重新解析架构' : '解析项目架构'}</button></div>
          <div className="code-agent-line"><span className="code-agent-indicator" /><span>Agent <strong>{assistant.data?.name ?? '正在读取…'}</strong></span><span>{selectedModel?.name ?? (models.isPending ? '读取模型…' : '未配置可用模型')}</span><span>只读分析</span><Link to={`/projects/${projectId}/knowledge`}>配置 Agent 与模型<ChevronRight size={13} aria-hidden="true" /></Link></div>
          {repository.data?.message && <p className="code-notice" role="status">{repository.data.message}</p>}
          {error && <div className="code-notice code-notice-error" role="alert"><strong>本次解析未完成</strong><p>{error.message}</p><button type="button" disabled={analyze.pending} onClick={() => void refresh()}>刷新源码与配置</button></div>}
          {analyze.pending && <div className="code-analysis-progress" role="status"><span className="code-progress-bar" /><p>Agent 正在对照源码生成架构说明与文件引用…</p></div>}
          {result ? <article className="code-analysis-report"><div className="code-report-meta"><span>{result.assistantName} · {result.model.name}</span><time dateTime={result.generatedAt}>{new Date(result.generatedAt).toLocaleString('zh-CN')}</time></div>
            {result.status === 'answered' && <ArchitectureGraph key={result.generatedAt} graph={result.graph} sources={result.snapshot.sources} onSource={setSourceId} />}
            {result.status === 'insufficient_evidence' ? <p>当前源码片段不足以确认架构，请补充入口或架构说明后重新读取。</p> : result.paragraphs.map((paragraph, index) => <section key={index}><KnowledgeText text={paragraph.text} /><div className="code-citations">{paragraph.citationIds.map(citation => { const item=result.snapshot.sources.find(file=>file.id===citation)!;return <button key={citation} type="button" aria-label={`查看引用 ${citation}：${item.path}`} onClick={() => setSourceId(citation)}><FileCode2 size={12} aria-hidden="true" />{item.path}<span>L{item.startLine}–{item.endLine}</span></button>; })}</div></section>)}
          </article> : !analyze.pending && <div className="code-analysis-empty"><Layers3 size={36} strokeWidth={1.4} aria-hidden="true" /><h3>{binding ? '先看代码，再看结论' : '从关联一个代码仓库开始'}</h3><p>{binding ? 'Agent 会解释项目如何启动、模块如何协作，以及哪些判断仍需进一步确认。左侧可预览本次发送给模型的片段。' : '支持已有本地 Git 仓库，也可以从你授权的 GitHub 仓库克隆。'}</p>{!binding && <button type="button" onClick={() => setTab('connection')}>设置仓库连接</button>}</div>}
          {snapshot && <div className="code-analysis-scope"><span>{snapshot.sources.length} 个文件片段 / {snapshot.eligibleFiles} 个候选文件{snapshot.truncated ? ' · 部分内容已截断' : ''}</span><p>点击解析会将这些片段发送给 Agent 所选模型。默认排除 .env、密钥文件、忽略文件及构建产物；本次不执行项目命令。</p></div>}
          {source && <section ref={sourcePreview} className="code-source-preview" aria-label="源码引用"><header><span><FileCode2 size={15} aria-hidden="true" />{source.path}</span><button type="button" aria-label="关闭源码预览" onClick={() => setSourceId(null)}><X size={16} aria-hidden="true" /></button></header><pre>{source.content.split('\n').map((line, index) => <span className="code-source-line" key={index}><span aria-hidden="true">{index + source.startLine}</span><code>{line || ' '}</code></span>)}</pre>{(source.truncated || source.redacted) && <p>{source.truncated ? '此文件仅展示开头片段。' : ''}{source.redacted ? '识别到的凭据值已隐藏。' : ''}</p>}</section>}
        </div>}
        <footer className="code-status-bar"><span><GitBranch size={12} aria-hidden="true" />{snapshot?.branch ?? binding?.branch ?? '未关联'}</span><span>{snapshot?.head ? snapshot.head.slice(0, 8) : '工作目录'} · {analyze.pending ? 'Agent 解析中' : tab === 'editor' ? '本地编辑 · UTF-8' : '只读分析'}</span></footer>
      </div>
    </div>
  </section>;
}
