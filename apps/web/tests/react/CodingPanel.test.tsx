import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { CodingPanel } from '../../src/components/code/CodingPanel.tsx';
import { SessionProvider } from '../../src/session/SessionContext.tsx';
import type { CodingRun } from '../../src/api/workspace.ts';

const identity = { user: { id: '00000000-0000-4000-8000-000000001001', email: 'demo@cairn.dev', displayName: '用户' }, organization: { id: '00000000-0000-4000-8000-000000002001', name: 'Cairn', slug: 'cairn' }, membership: { id: '00000000-0000-4000-8000-000000003001', role: 'owner' as const }, csrfToken: 'csrf' };
const project = '00000000-0000-4000-8000-000000004001';
const assistant = { id: null, name: '岑宁', instructions: '', enabledSkillIds: [], revision: 0, modelId: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function mount(dirty = false, additional: CodingRun[] = [], selectedId?: string) {
  let current: CodingRun | null = null;
  const requests: { path: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (path.endsWith('/assistants') && request.method === 'GET') return json({ items: [] });
    if (selectedId && path.endsWith('/' + selectedId)) return new Promise<Response>(() => {});
    if (path.endsWith('/coding-runs') && request.method === 'GET') return json({ items: [...(current ? [current] : []), ...additional] });
    if (request.method === 'POST') {
      const body = path.endsWith('/cancel') ? null : await request.json();
      requests.push({ path, body });
      if (path.endsWith('/coding-runs')) {
        current = { id: '00000000-0000-4000-8000-000000005001', userId: identity.user.id, projectId: project, workspaceId: 'a'.repeat(64), localPath: '/test/repo', task: '修复加法并测试', assistantId: null, assistantRevision: 0, assistantName: '岑宁', model: { id: 'default', name: '测试模型', model: 'test', protocol: 'openai-compatible' }, skillId: null, status: 'awaiting_approval', createdAt: '2026-10-31T10:00:00Z', updatedAt: '2026-10-31T10:00:01Z', events: [], changes: [], pendingCommand: { kind: 'run_command', argv: ['python', '-m', 'unittest'], purpose: 'test', timeoutSeconds: 30, eventId: 1 }, errorCode: null, summary: null };
      } else if (path.endsWith('/decision') && current) {
        current = { ...current, status: 'running', pendingCommand: null };
      } else if (current) current = { ...current, status: 'cancelled', pendingCommand: null, summary: '已停止，修改已保留' };
      return json(current, path.endsWith('/coding-runs') ? 202 : 200);
    }
    return json(current);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter initialEntries={[selectedId ? '/?run=' + selectedId : '/']}><QueryClientProvider client={client}><SessionProvider restoredIdentity={identity}><CodingPanel projectId={project} workspaceId={'a'.repeat(64)} localPath="/test/repo" assistant={assistant} modelName="测试模型" dirty={dirty} onCompare={() => {}} /></SessionProvider></QueryClientProvider></MemoryRouter>);
  return { requests, client };
}

test('drafts stay in the main editor while tasks start from committed code', async () => {
  const fixture = mount(true);
  fireEvent.change(screen.getByLabelText('交给 Agent 的任务'), { target: { value: '修复加法并测试' } });
  await userEvent.click(screen.getByLabelText(/允许此 Agent 将读取的源码/));
  await waitFor(() => expect(screen.getByRole('button', { name: '开始任务' })).toBeEnabled());
  expect(screen.getByText(/未保存草稿会保留/)).toBeVisible();
  expect(fixture.requests).toHaveLength(0);
  fixture.client.clear();
});

test('shows the exact command before approval and preserves a cancelled run', async () => {
  const fixture = mount();
  fireEvent.change(screen.getByLabelText('交给 Agent 的任务'), { target: { value: '修复加法并测试' } });
  await userEvent.click(screen.getByLabelText(/允许此 Agent 将读取的源码/));
  await waitFor(() => expect(screen.getByRole('button', { name: '开始任务' })).toBeEnabled());
  await userEvent.click(screen.getByRole('button', { name: '开始任务' }));
  expect(await screen.findByText(/python/)).toHaveTextContent('unittest');
  expect(screen.getByText(/当前系统用户权限/)).toBeVisible();
  expect(fixture.requests).toHaveLength(1);
  await userEvent.click(screen.getByLabelText('我确认此命令可以验证本次任务的结果。'));
  await userEvent.click(screen.getByRole('button', { name: '批准此命令' }));
  expect(fixture.requests.at(-1)?.body).toEqual({ eventId: 1, approved: true, verify: true });
  await userEvent.click(screen.getByRole('button', { name: '停止执行' }));
  expect(await screen.findByText('已停止，修改已保留')).toBeVisible();
  fixture.client.clear();
});


test('selecting a queued run does not jump to another active run and cancellation targets only it', async () => {
  const base: CodingRun = { id: '00000000-0000-4000-8000-000000005011', userId: identity.user.id, projectId: project, workspaceId: 'a'.repeat(64), localPath: '/repo.cairn-worktrees/a', task: '修复 A', assistantId: null, assistantRevision: 0, assistantName: 'Agent A', model: { id: 'default', name: '测试模型', model: 'test', protocol: 'openai-compatible' }, skillId: null, status: 'awaiting_approval', createdAt: '2026-10-31T10:00:00Z', updatedAt: '2026-10-31T10:00:01Z', events: [], changes: [], pendingCommand: { kind: 'run_command', argv: ['python', '-m', 'unittest'], purpose: 'test', timeoutSeconds: 30, eventId: 1 }, errorCode: null, summary: null };
  const queued = { ...base, id: '00000000-0000-4000-8000-000000005012', task: '后续 B', assistantName: 'Agent B', status: 'queued' as const, pendingCommand: null, dependsOn: base.id };
  const fixture = mount(false, [base, queued]);
  const history = await screen.findByLabelText('选择运行记录');
  expect(history).toBeEnabled();
  await userEvent.selectOptions(history, queued.id);
  expect(screen.getByRole('region', { name: '运行详情' })).toHaveTextContent('后续 B');
  expect(screen.queryByRole('button', { name: '批准此命令' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '取消排队' }));
  expect(fixture.requests.at(-1)?.path).toContain(queued.id + '/cancel');
  fixture.client.clear();
});

test('opening an archived run never offers controls for a different active run while loading', async () => {
  const active: CodingRun = { id: '00000000-0000-4000-8000-000000005021', userId: identity.user.id, projectId: project, workspaceId: 'a'.repeat(64), localPath: '/repo.cairn-worktrees/a', task: '当前任务', assistantId: null, assistantRevision: 0, assistantName: 'Agent A', model: { id: 'default', name: '测试模型', model: 'test', protocol: 'openai-compatible' }, skillId: null, status: 'awaiting_approval', createdAt: '2026-10-31T10:00:00Z', updatedAt: '2026-10-31T10:00:01Z', events: [], changes: [], pendingCommand: { kind: 'run_command', argv: ['python', '-m', 'unittest'], purpose: 'test', timeoutSeconds: 30, eventId: 1 }, errorCode: null, summary: null };
  const fixture = mount(false, [active], '00000000-0000-4000-8000-000000005099');
  await waitFor(() => expect(screen.getByLabelText('选择运行记录')).toBeEnabled());
  expect(screen.queryByRole('button', { name: '批准此命令' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '停止执行' })).not.toBeInTheDocument();
  fixture.client.clear();
});
