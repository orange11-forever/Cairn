import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import { ProjectSwitcher } from '../../src/components/ProjectSwitcher.tsx';
import { ApiError } from '../../src/api/errors.ts';
const api = vi.hoisted(() => ({ fetchProjects: vi.fn() }));
vi.mock('../../src/api/projects.ts', () => ({ fetchProjects: api.fetchProjects }));
const signal = new AbortController().signal;
const project = { id: 'synthetic-project', name: '运行验收', description: null, createdAt: '2026-10-01T00:00:00Z', updatedAt: '2026-10-01T00:00:00Z' };
function Location() { return <p aria-label='当前路由'>{useLocation().pathname}</p>; }
function mount() {
  api.fetchProjects.mockReset();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={['/projects/previous/knowledge']}><ProjectSwitcher organizationId='synthetic-org' projectId='previous' sessionSignal={signal} /><Location /></MemoryRouter></QueryClientProvider>);
  return userEvent.setup();
}
test('loads the authorized project list on demand, paginates and navigates to the selected real project', async () => {
  const user = mount();
  api.fetchProjects.mockResolvedValueOnce({ items: [project], nextCursor: 'next' }).mockResolvedValueOnce({ items: [{ ...project, id: 'another', name: '搜索验收' }], nextCursor: null });
  expect(api.fetchProjects).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: /切换项目/ }));
  await user.click(await screen.findByRole('button', { name: '加载更多项目' }));
  await user.click(await screen.findByRole('button', { name: '搜索验收' }));
  expect(screen.getByLabelText('当前路由')).toHaveTextContent('/projects/another/knowledge');
  expect(screen.queryByRole('region', { name: '选择项目' })).toBeNull();
  expect(api.fetchProjects.mock.calls[1]?.[0].cursor).toBe('next');
});
test('shows request failure and recovers the list without exposing unavailable cached projects', async () => {
  const user = mount();
  api.fetchProjects.mockRejectedValueOnce(new ApiError('network', '项目连接暂不可用')).mockResolvedValueOnce({ items: [project], nextCursor: null });
  await user.click(screen.getByRole('button', { name: /切换项目/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('项目连接暂不可用');
  await user.click(screen.getByRole('button', { name: '重新加载项目列表' }));
  expect(await screen.findByRole('button', { name: '运行验收' })).toBeVisible();
  await user.keyboard('{Escape}');
  expect(screen.getByRole('button', { name: /切换项目/ })).toHaveFocus();
});
test('keeps a denied project list closed to project choices', async () => {
  const user = mount();
  api.fetchProjects.mockRejectedValueOnce(new ApiError('http', '没有项目访问权限', { status: 403 }));
  await user.click(screen.getByRole('button', { name: /切换项目/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('没有项目访问权限');
  expect(screen.queryByRole('button', { name: '运行验收' })).toBeNull();
  await waitFor(() => expect(api.fetchProjects).toHaveBeenCalledTimes(1));
});
