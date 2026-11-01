import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { CodingOverview } from '../../src/components/code/CodingOverview.tsx';
import { SessionProvider } from '../../src/session/SessionContext.tsx';

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test('overview links each project result and changes the shared concurrency limit', async () => {
  const identity = { user: { id: '00000000-0000-4000-8000-000000001001', email: 'demo@cairn.dev', displayName: '用户' }, organization: { id: '00000000-0000-4000-8000-000000002001', name: 'Cairn', slug: 'cairn' }, membership: { id: '00000000-0000-4000-8000-000000003001', role: 'owner' as const }, csrfToken: 'csrf' };
  const projectId = '00000000-0000-4000-8000-000000004001';
  const id = '00000000-0000-4000-8000-000000005001';
  let limit = 2;
  vi.stubGlobal('chrome', { webview: {} });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === 'PUT') {
      expect(request.headers.get('X-CSRF-Token')).toBe('csrf');
      limit = (await request.json()).limit;
      return new Response(JSON.stringify({ limit }), { headers: { 'Content-Type': 'application/json' } });
    }
    return new Response(JSON.stringify({ concurrency: limit, items: [{ id, projectId, projectName: '后端项目', assistantName: '测试 Agent', task: '修复查询', modelName: '本地测试模型', status: 'queued', updatedAt: '2026-10-31T10:00:00Z', progress: '等待可用名额', changedFiles: 0, dependsOn: null }] }), { headers: { 'Content-Type': 'application/json' } });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><SessionProvider restoredIdentity={identity}><CodingOverview /></SessionProvider></QueryClientProvider></MemoryRouter>);
  await userEvent.click(screen.getByText('Agent 运行', { selector: 'summary span' }));
  expect(await screen.findByText('后端项目 · 测试 Agent')).toBeVisible();
  expect(screen.getByRole('link', { name: '查看运行与差异' })).toHaveAttribute('href', `/projects/${projectId}/code?run=${id}`);
  await userEvent.selectOptions(screen.getByLabelText('本机同时运行'), '1');
  await waitFor(() => expect(screen.getByLabelText('本机同时运行')).toHaveValue('1'));
  expect(screen.getByText('等待可用名额')).toBeVisible();
  client.clear();
});
