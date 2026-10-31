import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, ExternalLink } from 'lucide-react';
import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchCodingOverview, setCodingConcurrency } from '../../api/workspace.ts';
import { useSession } from '../../session/SessionContext.tsx';
import { running, statuses } from './CodingPanel.tsx';
import '../../../styles/coding-overview.css';

export function CodingOverview() {
  const { session } = useSession();
  const desktop = Boolean((window as Window & { chrome?: { webview?: unknown } }).chrome?.webview);
  if (!session || !desktop) return null;
  return <Overview key={session.generation} />;
}

function Overview() {
  const { session } = useSession();
  const client = useQueryClient();
  const details = useRef<HTMLDetailsElement>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = ['coding-overview', session!.generation];
  const query = useQuery({ queryKey: key, retry: false, gcTime: 0,
    queryFn: ({ signal }) => fetchCodingOverview(AbortSignal.any([signal, session!.signal])),
    refetchInterval: query => query.state.error ? false : 2000 });
  const items = query.data?.items ?? [];
  const canConfigure = ['owner', 'admin'].includes(session!.identity.membership.role);
  async function changeLimit(limit: number) {
    setPending(true); setError(null);
    try {
      await setCodingConcurrency(limit, session!.identity.csrfToken, session!.signal);
      await client.invalidateQueries({ queryKey: key });
    } catch (failure) {
      if (!session!.signal.aborted) setError(failure instanceof Error ? failure.message : '调整并发上限失败');
    } finally { setPending(false); }
  }
  return <details className="coding-overview" ref={details} onKeyDown={event => {
    if (event.key === 'Escape' && details.current) { details.current.open = false; details.current.querySelector('summary')?.focus(); }
  }}>
    <summary><Bot size={16} aria-hidden="true" /><span>Agent 运行</span><span className="coding-overview-count">{items.filter(running).length}</span></summary>
    <section className="coding-overview-body" aria-label="跨项目 Agent 运行">
      <header><h2>Agent 运行</h2><span>当前账号 · 全部项目</span></header>
      <div className="coding-concurrency"><label>本机同时运行<select aria-label="本机同时运行" value={query.data?.concurrency ?? 2} disabled={!query.data || pending || !canConfigure} onChange={event => void changeLimit(Number(event.target.value))}>{[1, 2, 3, 4].map(limit => <option value={limit} key={limit}>{limit} 个任务</option>)}</select></label><p>本次应用会话生效。等待命令确认也占用名额；降低上限后，已运行任务继续完成。</p></div>
      {(error || query.error) && <p className="coding-overview-error" role="alert">{error ?? query.error?.message}<button type="button" onClick={() => void query.refetch()}>刷新运行概览</button></p>}
      {query.isPending ? <p role="status">正在读取运行…</p> : items.length === 0 && !query.error ? <p>还没有编程任务。进入项目的代码工作区，为 Agent 分配任务。</p> : <ul>{items.map(run => <li key={run.id}>
        <div className="coding-overview-title"><strong>{run.projectName} · {run.assistantName}</strong><span>{statuses[run.status]}</span></div>
        <p className="coding-overview-task">{run.task}</p>
        <p className="coding-overview-progress">{run.progress}</p>
        <div className="coding-overview-meta"><span>{run.modelName} · {run.changedFiles} 个文件{run.dependsOn ? ' · 有前置任务' : ''}</span><Link to={`/projects/${run.projectId}/code?run=${run.id}`} onClick={() => { if (details.current) details.current.open = false; }}>查看运行与差异<ExternalLink size={12} aria-hidden="true" /></Link></div>
      </li>)}</ul>}
    </section>
  </details>;
}
