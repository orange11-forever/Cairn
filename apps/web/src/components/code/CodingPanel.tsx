import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, Check, FileDiff, Play, RefreshCw, Square, Terminal } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { fetchAssistants, fetchSkillCatalog, selectAssistant, type AssistantSettings } from '../../api/assistantSkills.ts';
import { cancelCodingRun, decideCodingCommand, fetchCodingRun, fetchCodingRuns, startCodingRun, type CodingChange, type CodingRun } from '../../api/workspace.ts';
import { useSession } from '../../session/SessionContext.tsx';

export const running = (run: Pick<CodingRun, 'status'>) => ['queued', 'running', 'awaiting_approval', 'cancelling'].includes(run.status);
export const statuses: Record<CodingRun['status'], string> = { queued: '排队中', blocked: '前置任务未成功', running: '正在执行', awaiting_approval: '等待命令确认', cancelling: '正在停止', cancelled: '已停止', succeeded: '已完成 · 已确认检查退出码 0', failed: '执行失败', interrupted: '运行已中断' };
export type AgentComparison = CodingChange & { label: string };
type Props = {
  projectId: string; workspaceId?: string; localPath: string; assistant?: AssistantSettings;
  modelName?: string; dirty: boolean;
  onCompare: (change: AgentComparison) => void; onFinished?: (runId: string) => void;
};

export function CodingPanel({ projectId, workspaceId, localPath, assistant, modelName, dirty, onCompare, onFinished }: Props) {
  const { session } = useSession();
  const client = useQueryClient();
  const [search] = useSearchParams();
  const [dependsOn, setDependsOn] = useState('');
  const [selecting, setSelecting] = useState(false);
  const [task, setTask] = useState('');
  const [consent, setConsent] = useState(false);
  const [skillId, setSkillId] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(search.get('run'));
  useEffect(() => { setSelectedId(search.get('run')); }, [search]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'steps' | 'output'>('steps');
  const [verifiedEvent, setVerifiedEvent] = useState<string | null>(null);
  const observed = useRef<string | null>(null);
  const key = ['coding-runs', session!.generation, projectId];
  const runs = useQuery({ queryKey: key, retry: false, gcTime: 0,
    queryFn: ({ signal }) => fetchCodingRuns(projectId, AbortSignal.any([signal, session!.signal])),
    refetchInterval: query => query.state.error ? false : 1000 });
  const skills = useQuery({ queryKey: ['coding-skills', session!.generation, projectId], retry: false,
    enabled: Boolean(assistant?.enabledSkillIds.length),
    queryFn: ({ signal }) => fetchSkillCatalog({ projectId, signal: AbortSignal.any([signal, session!.signal]) }) });
  const agents = useQuery({ queryKey: ['code-agents', session!.generation, projectId], retry: false,
    queryFn: ({ signal }) => fetchAssistants({ projectId, signal: AbortSignal.any([signal, session!.signal]) }) });
  const selectedRun = useQuery({ queryKey: ['coding-run', session!.generation, projectId, selectedId], retry: false, gcTime: 0,
    enabled: Boolean(selectedId && runs.data && !runs.data.items.some(item => item.id === selectedId)),
    queryFn: ({ signal }) => fetchCodingRun(projectId, selectedId!, AbortSignal.any([signal, session!.signal])) });
  const run = selectedId ? runs.data?.items.find(item => item.id === selectedId) ?? selectedRun.data : runs.data?.items[0];
  const busy = pending || selecting;
  const currentRuns = runs.data?.items.filter(running) ?? [];
  const canWrite = session!.identity.membership.role !== 'viewer';
  useEffect(() => {
    if (run && !running(run) && observed.current !== run.id) {
      observed.current = run.id;
      onFinished?.(run.id);
      void client.invalidateQueries({ queryKey: ['editor-tree', session!.generation, projectId] });
      void client.invalidateQueries({ queryKey: ['editor-changes', session!.generation, projectId] });
      void client.invalidateQueries({ queryKey: ['code-sources', session!.generation, projectId] });
    }
  }, [run, client, projectId, session, onFinished]);
  async function action(operation: () => Promise<CodingRun>) {
    if (pending) return;
    setPending(true); setError(null);
    try {
      const updated = await operation();
      if (session!.signal.aborted) return;
      setSelectedId(updated.id);
      client.setQueryData(key, (previous: { items: CodingRun[] } | undefined) => ({ items: [updated, ...(previous?.items ?? []).filter(item => item.id !== updated.id)] }));
      void client.invalidateQueries({ queryKey: ['coding-overview', session!.generation] });
    } catch (failure) {
      if (!session!.signal.aborted) setError(failure instanceof Error ? failure.message : '执行请求失败，请刷新运行记录');
    } finally { setPending(false); }
  }
  async function chooseAgent(id: string) {
    if (!assistant || !id || id === assistant.id || selecting) return;
    setSelecting(true); setError(null);
    try {
      const updated = await selectAssistant({ projectId, assistantId: id, expectedRevision: assistant.revision,
        csrfToken: session!.identity.csrfToken, signal: session!.signal });
      if (!session!.signal.aborted) {
        client.setQueryData(['code-assistant', session!.generation, projectId], updated);
        setSkillId('');
      }
    } catch (failure) {
      if (!session!.signal.aborted) setError(failure instanceof Error ? failure.message : '切换 Agent 失败');
    } finally { setSelecting(false); }
  }
  const command = run?.pendingCommand;
  const startDisabled = busy || !canWrite || !workspaceId || !assistant || !modelName || !consent || !task.trim() || runs.isPending || Boolean(runs.error);
  return <aside className="coding-panel" aria-label="编程 Agent">
    <header className="coding-heading"><h2><Bot size={18} aria-hidden="true" />编程 Agent</h2><button type="button" aria-label="刷新运行记录" disabled={runs.isFetching} onClick={() => void runs.refetch()}><RefreshCw size={15} aria-hidden="true" /></button></header>
    <div className="coding-agent"><label>分配给 Agent<select aria-label="分配给 Agent" value={assistant?.id ?? ''} disabled={busy || !assistant || !canWrite} onChange={event => void chooseAgent(event.target.value)}>{!assistant?.id && <option value="">{assistant?.name ?? '正在读取 Agent…'}</option>}{agents.data?.items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><span>{modelName ?? '尚未配置模型'}</span><Link to={`/projects/${projectId}/knowledge`}>配置 Agent 与模型</Link></div>
    <form className="coding-task" onSubmit={event => { event.preventDefault(); if (!startDisabled) void action(() => startCodingRun(projectId, { workspaceId: workspaceId!, task: task.trim(), assistantId: assistant!.id ?? null, assistantRevision: assistant!.revision, skillId: skillId || null, dependsOn: dependsOn || null, allowWrites: true }, session!.identity.csrfToken, session!.signal)); }}>
      <label htmlFor="coding-task">交给 Agent 的任务</label>
      <textarea id="coding-task" rows={3} maxLength={6000} placeholder="描述一个具体修改，以及怎样验证它…" value={task} onChange={event => setTask(event.target.value)} disabled={busy || !canWrite} />
      {assistant?.enabledSkillIds.length ? <label>本次 Skill<select value={skillId} disabled={busy} onChange={event => setSkillId(event.target.value)}><option value="">不使用 Skill</option>{skills.data?.items.filter(skill => skill.runnable && assistant.enabledSkillIds.includes(skill.id)).map(skill => <option key={skill.id} value={skill.id}>{skill.name}</option>)}</select></label> : null}
      <label className="coding-consent"><input type="checkbox" checked={consent} disabled={busy || !canWrite} onChange={event => setConsent(event.target.checked)} /><span>允许此 Agent 将读取的源码和命令输出发送给所选模型，并修改本次独立工作区中的文件。命令另行逐条确认。</span></label>
      <label>前置任务<select aria-label="前置任务" value={dependsOn} disabled={busy} onChange={event => setDependsOn(event.target.value)}><option value="">无 · 独立推进</option>{runs.data?.items.filter(item => running(item) || item.status === 'succeeded').map(item => <option key={item.id} value={item.id}>{item.assistantName} · {item.task.slice(0, 32)}</option>)}</select></label>
      <p className="coding-hint">从当前已提交的 Git HEAD 建立独立分支，未提交修改留在原目录。{dependsOn && '等待前置任务成功后，提供其摘要和差异供 Agent 参考；代码不会自动合并。'}</p>
      {dirty && <p className="coding-hint" role="status">未保存草稿会保留在编辑器中，不会发送给 Agent。</p>}
      <button type="submit" className="code-analyze-button" disabled={startDisabled}><Play size={14} aria-hidden="true" />开始任务</button>
    </form>
    {(error || runs.error || skills.error || agents.error || selectedRun.error) && <p className="code-notice code-notice-error" role="alert">{error ?? runs.error?.message ?? skills.error?.message ?? agents.error?.message ?? selectedRun.error?.message}</p>}
    {(runs.isPending || (selectedId && !run && selectedRun.isPending)) && <p role="status" className="coding-hint">正在读取运行记录…</p>}
    {currentRuns.length > 0 && <p className="coding-hint" role="status">此项目 {currentRuns.filter(item => item.status !== 'queued').length} 个运行中 · {currentRuns.filter(item => item.status === 'queued').length} 个排队中</p>}
    {(runs.data?.items.length ?? 0) > 0 && <label className="coding-history">选择运行记录<select aria-label="选择运行记录" value={selectedId ?? run?.id ?? ''} onChange={event => { setSelectedId(event.target.value); setVerifiedEvent(null); }}>{selectedId && !runs.data?.items.some(item => item.id === selectedId) && <option value={selectedId}>{selectedRun.data ? `${selectedRun.data.assistantName} · ${selectedRun.data.task.slice(0, 32)}` : selectedRun.error ? '所选记录读取失败' : '正在读取所选记录…'}</option>}{runs.data?.items.map(item => <option key={item.id} value={item.id}>{statuses[item.status]} · {item.assistantName} · {item.task.slice(0, 32)}</option>)}</select></label>}
    {run ? <section className="coding-run" aria-label="运行详情">
      <div className="coding-run-heading"><strong role="status">{statuses[run.status]}</strong>{running(run) && <button type="button" disabled={pending || run.status === 'cancelling'} onClick={() => void action(() => cancelCodingRun(projectId, run.id, session!.identity.csrfToken, session!.signal))}><Square size={13} aria-hidden="true" />{run.status === 'queued' ? '取消排队' : '停止执行'}</button>}</div>
      <p className="coding-run-task">{run.task}</p><p className="coding-meta">{run.assistantName} · {run.model.name} · {new Date(run.createdAt).toLocaleString('zh-CN')}</p>
      {run.branch && <div className="coding-location"><span>独立分支 <code>{run.branch}</code></span><span>基于提交 <code>{run.baseHead?.slice(0, 8)}</code> · 配置版本 {run.assistantRevision}</span><code>{run.localPath}</code><span>成果保留在此目录，尚未集成到项目分支。</span></div>}
      {run.dependsOn && <p className="coding-hint">前置任务：<button type="button" onClick={() => setSelectedId(run.dependsOn!)}>查看前置任务结果</button></p>}
      {(run.overlaps?.length ?? 0) > 0 && <div className="coding-overlaps" role="status"><strong>文件修改重叠，可能产生合并冲突</strong><p>各自成果已保留，请分别审阅后再集成。</p>{run.overlaps?.map(other => <button key={other.runId} type="button" onClick={() => setSelectedId(other.runId)}>{other.assistantName} · {other.paths.join('、')}</button>)}</div>}
      {command && run.status === 'awaiting_approval' && <div className="coding-approval">
        <h3><Terminal size={16} aria-hidden="true" />确认本机命令</h3>
        <p>参数数组，每项独立传递：</p><pre>{JSON.stringify(command.argv, null, 2)}</pre>
        <p>工作目录：<code>{run.localPath}</code></p><p>最长 {command.timeoutSeconds} 秒 · {command.purpose === 'test' ? '测试' : '命令'}</p>
        <p>命令以当前系统用户权限运行，可访问该用户有权限的文件和网络；工作目录不是系统沙箱。</p>
        {command.purpose === 'test' && <label className="coding-consent"><input type="checkbox" checked={verifiedEvent === `${run.id}:${command.eventId}`} onChange={event => setVerifiedEvent(event.target.checked ? `${run.id}:${command.eventId}` : null)} /><span>我确认此命令可以验证本次任务的结果。</span></label>}<div className="coding-actions"><button type="button" disabled={pending || !canWrite} onClick={() => void action(() => decideCodingCommand(projectId, run.id, { eventId: command.eventId, approved: true, verify: verifiedEvent === `${run.id}:${command.eventId}` }, session!.identity.csrfToken, session!.signal))}><Check size={14} aria-hidden="true" />批准此命令</button><button type="button" disabled={pending} onClick={() => void action(() => decideCodingCommand(projectId, run.id, { eventId: command.eventId, approved: false }, session!.identity.csrfToken, session!.signal))}>拒绝并停止</button></div>
      </div>}
      {run.summary && <p className={`coding-summary${run.status === 'failed' ? ' code-notice-error' : ''}`}>{run.summary}{run.errorCode && <small>错误代码：{run.errorCode}</small>}</p>}
      {run.changes.length > 0 && <div className="coding-changes"><h3>本次运行的源码改动</h3>{run.changes.map(change => <button key={change.path} type="button" onClick={() => onCompare({ ...change, label: `${run.assistantName} · ${change.origin === 'command' ? '命令期间的变化' : '文件工具写入前后'}` })}><FileDiff size={14} aria-hidden="true" />{change.path}<span>查看差异</span></button>)}</div>}
      <div className="coding-output-tabs" aria-label="运行记录视图"><button type="button" aria-pressed={view === 'steps'} onClick={() => setView('steps')}>执行步骤</button><button type="button" aria-pressed={view === 'output'} onClick={() => setView('output')}><Terminal size={13} aria-hidden="true" />命令输出</button></div>
      {view === 'steps' ? <ol className="coding-steps">{run.events.filter(event => event.kind !== 'output').map(event => <li key={event.id}><time>{new Date(event.at).toLocaleTimeString('zh-CN')}</time><span>{event.message}{event.path && <code>{event.path}</code>}</span></li>)}</ol> : <pre className="coding-output" tabIndex={0} aria-label="命令输出">{run.events.filter(event => event.kind === 'output' || event.kind === 'command_result').map(event => event.message).join('') || '尚无命令输出。批准命令后，实际输出会显示在这里。'}</pre>}
    </section> : !selectedId && !runs.isPending && <p className="coding-empty">从一个小任务开始。Agent 的每一步、文件修改和测试结果都会留在这里。</p>}
    <footer className="coding-footer"><code title={localPath}>{localPath}</code><span>显示全部运行与排队任务及最近 20 次结果。运行记录加密保存在本机；重启后不会自动继续。</span></footer>
  </aside>;
}
