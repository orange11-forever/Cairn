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

function mount(dirty = false) {
  let current: CodingRun | null = null;
  const requests: { path: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (path.endsWith('/coding-runs') && request.method === 'GET') return json({ items: current ? [current] : [] });
    if (request.method === 'POST') {
      const body = path.endsWith('/cancel') ? null : await request.json();
      requests.push({ path, body });
      if (path.endsWith('/coding-runs')) {
        current = { id: '00000000-0000-4000-8000-000000005001', userId: identity.user.id, projectId: project, workspaceId: 'a'.repeat(64), localPath: '/test/repo', task: '修复加法并测试', assistantId: null, assistantName: '岑宁', model: { id: 'default', name: '测试模型', model: 'test', protocol: 'openai-compatible' }, skillId: null, status: 'awaiting_approval', createdAt: '2026-10-31T10:00:00Z', updatedAt: '2026-10-31T10:00:01Z', events: [], changes: [], pendingCommand: { kind: 'run_command', argv: ['python', '-m', 'unittest'], purpose: 'test', timeoutSeconds: 30, eventId: 1 }, errorCode: null, summary: null };
      } else if (path.endsWith('/decision') && current) {
        current = { ...current, status: 'running', pendingCommand: null };
      } else if (current) current = { ...current, status: 'cancelled', pendingCommand: null, summary: '已停止，修改已保留' };
      return json(current, path.endsWith('/coding-runs') ? 202 : 200);
    }
    return json(current);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><SessionProvider restoredIdentity={identity}><CodingPanel projectId={project} workspaceId={'a'.repeat(64)} localPath="/test/repo" assistant={assistant} modelName="测试模型" dirty={dirty} onBusyChange={() => {}} onCompare={() => {}} /></SessionProvider></QueryClientProvider></MemoryRouter>);
  return { requests, client };
}

test('dirty drafts block starting an Agent without discarding edits', async () => {
  const fixture = mount(true);
  fireEvent.change(screen.getByLabelText('交给 Agent 的任务'), { target: { value: '修复加法并测试' } });
  await userEvent.click(screen.getByLabelText(/允许此 Agent 将读取的源码/));
  expect(screen.getByRole('button', { name: '开始任务' })).toBeDisabled();
  expect(screen.getByText(/先保存或关闭未保存草稿/)).toBeVisible();
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
