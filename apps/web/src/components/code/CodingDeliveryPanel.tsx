import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, GitCommitHorizontal } from 'lucide-react';
import { useState } from 'react';
import { commitCodingRun, createCodingPullRequest, fetchDeliveryReview, fetchWorkspace, prepareCodingTarget, pushCodingRun, reconcileCodingDelivery, type CodingRun, type RemoteTarget } from '../../api/workspace.ts';
import { useSession } from '../../session/SessionContext.tsx';

export const deliveryLabels: Record<NonNullable<CodingRun['delivery']>['phase'], string> = {
  uncommitted: '尚未提交', committing: '提交处理中 · 可核对结果', commit_unknown: '提交结果待核对', committed: '已本地提交',
  pushing: '推送处理中 · 可核对结果', push_unknown: '推送结果待核对', pushed: '已确认推送',
  creating_pr: 'PR 创建处理中 · 可核对结果', pr_unknown: 'PR 结果待核对', pr_created: '已有 PR',
};

export function CodingDeliveryPanel({ run, onUpdated }: { run: CodingRun; onUpdated: (run: CodingRun) => void }) {
  const { session } = useSession();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [authorName, setAuthorName] = useState(session!.user.displayName ?? '');
  const [authorEmail, setAuthorEmail] = useState(session!.user.email ?? '');
  const [baseBranch, setBaseBranch] = useState<string | null>(null);
  const [target, setTarget] = useState<RemoteTarget | null>(null);
  const [pushConsent, setPushConsent] = useState(false);
  const [prConsent, setPrConsent] = useState(false);
  const [draft, setDraft] = useState(true);
  const [title, setTitle] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const review = useQuery({ queryKey: ['coding-delivery', session!.generation, run.projectId, run.id], retry: false, gcTime: 0,
    enabled: open, queryFn: ({ signal }) => fetchDeliveryReview(run.projectId, run.id, AbortSignal.any([signal, session!.signal])) });
  const repository = useQuery({ queryKey: ['desktop-workspace', session!.generation, run.projectId], retry: false,
    enabled: open, queryFn: ({ signal }) => fetchWorkspace(run.projectId, AbortSignal.any([signal, session!.signal])) });
  const state = run.delivery ?? review.data?.delivery;
  const phase = state?.phase ?? 'uncommitted';
  const uncertain = ['committing', 'commit_unknown', 'pushing', 'push_unknown', 'creating_pr', 'pr_unknown'].includes(phase);
  const branch = baseBranch ?? state?.target?.baseBranch ?? repository.data?.binding?.repository?.defaultBranch ?? '';
  const canWrite = session!.identity.membership.role !== 'viewer';
  const csrf = session!.identity.csrfToken;
  const signal = session!.signal;
  const commitMessage = message ?? review.data?.suggestedMessage ?? '';
  const prTitle = title ?? review.data?.suggestedTitle ?? '';
  const prBody = body ?? review.data?.suggestedBody ?? '';
  async function act(operation: () => Promise<CodingRun | RemoteTarget>) {
    if (pending) return;
    setPending(true); setError(null);
    try {
      const result = await operation();
      if (signal.aborted) return;
      if ('repositoryId' in result) { setTarget(result); setPushConsent(false); setPrConsent(false); }
      else onUpdated(result);
    } catch (failure) {
      if (!signal.aborted) setError(failure instanceof Error ? failure.message : '操作未完成，请核对状态。');
    } finally {
      setPending(false);
      if (!signal.aborted) {
        void review.refetch();
        void client.invalidateQueries({ queryKey: ['coding-runs', session!.generation, run.projectId] });
        void client.invalidateQueries({ queryKey: ['coding-overview', session!.generation] });
      }
    }
  }
  return <details className="coding-delivery" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><GitCommitHorizontal size={15} aria-hidden="true" />提交与 PR<span>{deliveryLabels[phase]}</span></summary>
    <div className="coding-delivery-body">
      <p>只操作本次任务的独立分支。源码差异和检查结果见本条运行记录；完成 PR 后仍需单独评审和合并。</p>
      {state?.commitSha && <p>提交 <code>{state.commitSha}</code></p>}
      {state?.prUrl && <a className="coding-pr-link" href={state.prUrl} target="_blank" rel="noopener noreferrer">打开 GitHub PR #{state.prNumber}{state.prState === 'closed' ? ' · 已关闭' : ''}<ExternalLink size={14} aria-hidden="true" /></a>}
      {(error || review.error || state?.error || repository.error) && <p className="code-notice code-notice-error" role="alert">{error ?? review.error?.message ?? state?.error ?? repository.error?.message}</p>}
      {pending && <p role="status">正在处理。请等待结果；离开页面后可从本条记录核对，勿重复执行。</p>}
      {review.isPending && open && <p role="status">正在核对任务源码与提交状态…</p>}
      {uncertain && <div className="coding-delivery-reconcile"><p>先核对已有提交、远端分支或 PR。此操作不会重新提交或推送；仅在确认属于本次提交时修复中断的暂存区写入。</p><button type="button" disabled={pending || !canWrite} onClick={() => void act(() => reconcileCodingDelivery(run.projectId, run.id, csrf, signal))}>核对操作结果</button></div>}
      {!uncertain && phase !== 'pr_created' && <button type="button" disabled={pending || review.isFetching} onClick={() => void review.refetch()}>刷新提交预览</button>}
      {phase === 'uncommitted' && review.data && !review.error && <form onSubmit={event => {
        event.preventDefault(); if (!pending && canWrite) void act(() => commitCodingRun(run.projectId, run.id, { snapshotId: review.data!.snapshotId, message: commitMessage, authorName, authorEmail }, csrf, signal));
      }}>
        <p>将提交 {review.data.files.length} 个源码文件：{review.data.files.join('、')}</p>
        {review.data.excludedPaths.length > 0 && <p className="coding-hint">以下未跟踪文件不进入提交：{review.data.excludedPaths.join('、')}</p>}
        <label>提交说明<textarea required maxLength={4000} rows={2} value={commitMessage} onChange={event => setMessage(event.target.value)} disabled={pending || !canWrite} /></label>
        <div className="coding-author"><label>作者名称<input required maxLength={100} value={authorName} onChange={event => setAuthorName(event.target.value)} disabled={pending || !canWrite} /></label><label>作者邮箱<input required type="email" maxLength={254} value={authorEmail} onChange={event => setAuthorEmail(event.target.value)} disabled={pending || !canWrite} /></label></div>
        <p className="coding-hint">署名会写入提交，推送后对仓库访问者可见；可填写你的 GitHub noreply 邮箱。</p>
        <button type="submit" disabled={pending || !canWrite || !commitMessage.trim()}>创建本地提交</button>
      </form>}
      {['committed', 'pushed'].includes(phase) && <div className="coding-remote">
        <label>PR 基础分支<input aria-label="PR 基础分支" value={branch} onChange={event => { setBaseBranch(event.target.value); setTarget(null); setPushConsent(false); setPrConsent(false); }} disabled={pending || !canWrite || Boolean(state?.target)} placeholder="例如 main" /></label>
        <button type="button" disabled={pending || !canWrite || !branch.trim() || Boolean(review.error)} onClick={() => void act(() => prepareCodingTarget(run.projectId, run.id, branch, csrf, signal))}>核对 GitHub 目标</button>
        {target && <div className="coding-target"><strong>{target.fullName} · {target.private ? '私有仓库' : '公开仓库'}</strong><span>GitHub 账号：{target.accountLogin}</span><span><code>{target.headBranch}</code> → <code>{target.baseBranch}</code></span><span>提交 <code>{target.headSha.slice(0, 12)}</code> · 基础 <code>{target.baseSha.slice(0, 12)}</code></span></div>}
        {phase === 'committed' && target && <><label className="coding-consent"><input type="checkbox" checked={pushConsent} onChange={event => setPushConsent(event.target.checked)} disabled={pending || !canWrite} /><span>允许将此提交及其可达历史推送到上述 GitHub 仓库的新任务分支。</span></label><button type="button" disabled={pending || !canWrite || !pushConsent || Boolean(review.error)} onClick={() => void act(() => pushCodingRun(run.projectId, run.id, target, csrf, signal))}>推送已确认的提交</button></>}
        {phase === 'pushed' && target && <form onSubmit={event => { event.preventDefault(); if (prConsent && !pending && canWrite) void act(() => createCodingPullRequest(run.projectId, run.id, { target, title: prTitle, body: prBody, allowCreate: true, draft }, csrf, signal)); }}>
          <label>PR 标题<input required maxLength={200} value={prTitle} onChange={event => { setTitle(event.target.value); setPrConsent(false); }} disabled={pending || !canWrite} /></label>
          <label>PR 正文<textarea required rows={7} maxLength={12000} value={prBody} onChange={event => { setBody(event.target.value); setPrConsent(false); }} disabled={pending || !canWrite} /></label>
          <label className="coding-consent"><input type="checkbox" checked={draft} onChange={event => { setDraft(event.target.checked); setPrConsent(false); }} disabled={pending || !canWrite} /><span>创建为草稿 PR（需要仓库支持此功能）</span></label>
          <label className="coding-consent"><input type="checkbox" checked={prConsent} onChange={event => setPrConsent(event.target.checked)} disabled={pending || !canWrite} /><span>允许将以上标题和正文发布到该仓库，并创建{draft ? '草稿 ' : ''}PR。</span></label>
          <button type="submit" disabled={pending || !canWrite || !prConsent || !prTitle.trim() || !prBody.trim() || Boolean(review.error)}>创建{draft ? '草稿 ' : ''}PR</button>
        </form>}
      </div>}
    </div>
  </details>;
}
