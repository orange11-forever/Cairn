import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { CodingDeliveryPanel } from '../../src/components/code/CodingDeliveryPanel.tsx';
import { SessionProvider } from '../../src/session/SessionContext.tsx';
import type { CodingRun, RemoteTarget } from '../../src/api/workspace.ts';

const identity = { user: { id: '00000000-0000-4000-8000-000000001001', email: 'author@example.com', displayName: '作者' }, organization: { id: '00000000-0000-4000-8000-000000002001', name: 'Cairn', slug: 'cairn' }, membership: { id: '00000000-0000-4000-8000-000000003001', role: 'owner' as const }, csrfToken: 'csrf' };
const project = '00000000-0000-4000-8000-000000004001';
const id = '00000000-0000-4000-8000-000000005001';
const branch = 'cairn/agent-' + id;
const sha = 'b'.repeat(40);
const target: RemoteTarget = { repositoryId: 11, fullName: 'test-owner/fixture', private: false, accountId: 7, accountLogin: 'test-owner', baseBranch: 'main', baseSha: 'a'.repeat(40), headBranch: branch, headSha: sha };
const baseRun: CodingRun = { id, userId: identity.user.id, projectId: project, workspaceId: 'a'.repeat(64), localPath: '/tmp/task', task: '修复 value', assistantId: null, assistantRevision: 0, assistantName: 'Agent', model: { id: 'default', name: '模型', model: 'test', protocol: 'openai-compatible' }, skillId: null, status: 'succeeded', createdAt: '2026-11-01T00:00:00Z', updatedAt: '2026-11-01T00:00:10Z', events: [], changes: [{ path: 'main.py', before: 'value=0', after: 'value=1', revision: 'c'.repeat(64), origin: 'file_tool' }], branch, baseHead: 'a'.repeat(40), repositoryPath: '/tmp/main', summary: '验证完成' };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function mount(unknown = false) {
  let current: CodingRun = { ...baseRun, delivery: { phase: unknown ? 'pr_unknown' : 'uncommitted', ...(unknown ? { commitSha: sha, target, error: '响应丢失，请先核对' } : {}) } };
  const requests: { path: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (path.endsWith('/repository')) return json({ binding: { localPath: '/tmp/main', branch: 'main', account: { id: 7, login: 'test-owner' }, repository: { id: 11, fullName: target.fullName, private: false, defaultBranch: 'main', canPush: true, url: 'https://github.com/test-owner/fixture' } }, gitAvailable: true, repositoryStatus: 'available', message: null });
    if (request.method === 'GET') return json({ snapshotId: 'd'.repeat(64), files: ['main.py'], excludedPaths: ['__pycache__/main.pyc'], suggestedMessage: '修复 value', suggestedTitle: '修复 value', suggestedBody: '实际检查退出码 0', delivery: current.delivery });
    const body = path.endsWith('/reconcile') ? null : await request.json();
    requests.push({ path, body });
    if (path.endsWith('/target')) return json(target);
    if (path.endsWith('/commit')) current = { ...current, delivery: { phase: 'committed', commitSha: sha, message: '修复 value' } };
    else if (path.endsWith('/push')) current = { ...current, delivery: { phase: 'pushed', commitSha: sha, target } };
    else if (path.endsWith('/pull-request') || path.endsWith('/reconcile')) current = { ...current, delivery: { phase: 'pr_created', commitSha: sha, target, prNumber: 17, prUrl: 'https://github.com/test-owner/fixture/pull/17', prState: 'open', prDraft: true } };
    return json(current);
  }));
  function Panel() { const [run, setRun] = useState(current); return <CodingDeliveryPanel run={run} onUpdated={setRun} />; }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><SessionProvider restoredIdentity={identity}><Panel /></SessionProvider></QueryClientProvider></MemoryRouter>);
  return { client, requests };
}

test('commit snapshot and explicit target consent gate push and PR creation', async () => {
  const fixture = mount();
  await userEvent.click(screen.getByText('提交与 PR'));
  const commit = await screen.findByRole('button', { name: '创建本地提交' });
  expect(screen.getByLabelText('作者邮箱')).toHaveValue('author@example.com');
  await userEvent.click(commit);
  expect(fixture.requests[0]?.body).toEqual({ snapshotId: 'd'.repeat(64), message: '修复 value', authorName: '作者', authorEmail: 'author@example.com' });
  await userEvent.click(await screen.findByRole('button', { name: '核对 GitHub 目标' }));
  expect(await screen.findByText('test-owner/fixture · 公开仓库')).toBeVisible();
  const push = screen.getByRole('button', { name: '推送已确认的提交' });
  expect(push).toBeDisabled();
  await userEvent.click(screen.getByLabelText(/允许将此提交及其可达历史/));
  await userEvent.click(push);
  expect(fixture.requests.at(-1)?.body).toEqual({ target, allowPush: true });
  const create = await screen.findByRole('button', { name: '创建草稿 PR' });
  expect(create).toBeDisabled();
  await userEvent.click(screen.getByLabelText(/允许将以上标题和正文/));
  await userEvent.click(create);
  expect(fixture.requests.at(-1)?.body).toEqual({ target, title: '修复 value', body: '实际检查退出码 0', allowCreate: true, draft: true });
  const link = await screen.findByRole('link', { name: /打开 GitHub PR #17/ });
  expect(link).toHaveAttribute('href', 'https://github.com/test-owner/fixture/pull/17');
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  fixture.client.clear();
});

test('uncertain PR offers reconciliation and never retries creation', async () => {
  const fixture = mount(true);
  await userEvent.click(screen.getByText('提交与 PR'));
  expect(screen.queryByRole('button', { name: '创建草稿 PR' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '核对操作结果' }));
  await waitFor(() => expect(screen.getByRole('link', { name: /打开 GitHub PR #17/ })).toBeVisible());
  expect(fixture.requests).toHaveLength(1);
  expect(fixture.requests[0]?.path).toMatch(/\/reconcile$/);
  fixture.client.clear();
});
