import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import type { KnowledgeCitation } from '../../src/api/knowledge.ts';
import { KnowledgePage } from '../../src/pages/KnowledgePage.tsx';
const signal = new AbortController().signal;
const citationFixture: KnowledgeCitation = { resourceId: 'first', resourceVersionId: 'version', chunkId: 'chunk', title: '运行手册引用', excerpt: 'synthetic private excerpt', locator: { type: 'pdf', page: 2 }, mediaType: 'application/pdf', score: 0.8 };
const observedReferences: unknown[] = [];
const fixtures = [{ id: 'first', title: '运行手册.md', sourceType: 'uploaded_file', createdAt: '2026-10-01T00:00:00Z', updatedAt: '2026-10-01T00:00:00Z', latestVersion: null }, { id: 'second', title: '架构说明.md', sourceType: 'uploaded_file', createdAt: '2026-10-01T00:00:00Z', updatedAt: '2026-10-01T00:00:00Z', latestVersion: null }];
vi.mock('../../src/session/SessionContext.tsx', () => ({ useSession: () => ({ session: { generation: 1, signal, identity: { organization: { id: 'synthetic-org' }, membership: { role: 'member' }, csrfToken: 'synthetic' } } }) }));
vi.mock('../../src/queries/projects.ts', () => ({ useProjectQuery: () => ({ isSuccess: true, isFetching: false, data: { name: '合成项目' } }) }));
vi.mock('../../src/queries/knowledge.ts', async (original) => ({ ...await original<object>(), useKnowledgeResourcesQuery: () => ({ isPending: false, data: { pages: [{ items: fixtures, capabilities: { canWrite: false } }] }, refetch: vi.fn(), fetchStatus: 'idle' }) }));
vi.mock('../../src/components/knowledge/KnowledgeSearch.tsx', () => ({ KnowledgeSearch: ({ onOpenCitation }: { onOpenCitation: (citation: KnowledgeCitation) => void }) => <><p>搜索控制器</p><button onClick={() => onOpenCitation(citationFixture)}>打开合成引用</button></> }));
vi.mock('../../src/components/knowledge/KnowledgeCitationContext.tsx', () => ({ KnowledgeCitationContext: ({ citation }: { citation: KnowledgeCitation }) => { observedReferences.push(citation); return <p>活动引用：{citation.title}</p>; } }));
vi.mock('../../src/components/knowledge/KnowledgeAnswers.tsx', () => ({ KnowledgeAnswers: () => <p>问答控制器</p> }));
vi.mock('../../src/components/knowledge/KnowledgeDocument.tsx', () => ({ KnowledgeDocument: ({ resourceId, citation }: { resourceId: string; citation?: KnowledgeCitation }) => { if (citation) { observedReferences.push(citation); return <p>活动引用：{citation.title}</p>; } return <p>活动资料：{resourceId}</p>; } }));
function Navigation() { const navigate = useNavigate(); return <button onClick={() => navigate("/projects/beta/knowledge")}>切换合成项目</button>; }
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/projects/alpha/knowledge']}><Navigation /><Routes><Route path='/projects/:projectId/knowledge' element={<KnowledgePage />} /></Routes></MemoryRouter></QueryClientProvider>);
  return Object.assign(userEvent.setup(), { client });
}
test('opens multiple file tabs, activates search, and closes the active file without retaining its controller', async () => {
  const user = mount();
  await user.click(screen.getByRole('button', { name: '查看运行手册.md资料详情' }));
  await user.click(screen.getByRole('button', { name: '查看架构说明.md资料详情' }));
  expect(screen.getByRole('tab', { name: '运行手册.md' })).toHaveAttribute('aria-selected', 'false');
  expect(screen.getByRole('tab', { name: '架构说明.md' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.queryByText('活动资料：first')).toBeNull();
  await user.click(screen.getByRole('tab', { name: '运行手册.md' }));
  expect(await screen.findByText('活动资料：first')).toBeVisible();
  await user.click(screen.getByRole('button', { name: '关闭运行手册.md标签' }));
  await waitFor(() => expect(screen.queryByRole('tab', { name: '运行手册.md' })).toBeNull());
  expect(screen.getByRole('tab', { name: '架构说明.md' })).toHaveAttribute('aria-selected', 'true');
  await user.click(screen.getByRole('tab', { name: '搜索' }));
  expect(screen.getByText('搜索控制器')).toBeVisible();
  expect(screen.queryByText('活动资料：second')).toBeNull();
});
test('always provides reversible explorer and assistant visibility controls', async () => {
  const user = mount();
  const explorer = screen.getByRole('complementary', { name: '项目资料' });
  await user.click(screen.getByRole('button', { name: '收起资料栏' }));
  expect(explorer).not.toBeVisible();
  await user.click(screen.getByRole('button', { name: '展开资料栏' }));
  expect(explorer).toBeVisible();
  const assistant = screen.getByRole('complementary', { name: '岑宁问答面板' });
  await user.click(screen.getByRole('button', { name: '收起助手' }));
  expect(assistant).not.toBeVisible();
  await user.click(screen.getByRole('button', { name: '展开助手' }));
  expect(within(assistant).getByText('问答控制器')).toBeVisible();
});

test('scope changes discard open tabs and the old active controller', async () => {
  const user = mount();
  await user.click(screen.getByRole('button', { name: '查看运行手册.md资料详情' }));
  expect(await screen.findByText('活动资料：first')).toBeVisible();
  await user.click(screen.getByRole('button', { name: '切换合成项目' }));
  expect(screen.queryByRole('tab', { name: '运行手册.md' })).toBeNull();
  expect(screen.queryByText('活动资料：first')).toBeNull();
  expect(screen.getByRole('tab', { name: '搜索' })).toHaveAttribute('aria-selected', 'true');
});
test('supports arrow-key tab activation while retaining the accessible label', async () => {
  const user = mount();
  await user.click(screen.getByRole('button', { name: '查看运行手册.md资料详情' }));
  const tab = screen.getByRole('tab', { name: '运行手册.md' });
  tab.focus();
  await user.keyboard('{ArrowLeft}');
  expect(screen.getByRole('tab', { name: '搜索' })).toHaveFocus();
  expect(screen.getByRole('tab', { name: '搜索' })).toHaveAttribute('aria-selected', 'true');
});

test('scope changes cancel and remove private content caches while preserving other project caches', async () => {
  const user = mount();
  const activeKey = ['project-knowledge', 'synthetic-org', 'alpha', 'citation-context', 'first', 'version', 'chunk'];
  const contentKey = ['project-knowledge', 'synthetic-org', 'alpha', 'content', 'first', 'version', 'chunk'];
  const otherKey = ['project-knowledge', 'synthetic-org', 'other', 'resource', 'retained'];
  user.client.setQueryData(activeKey, { text: 'bounded private content' });
  user.client.setQueryData(contentKey, { content: 'complete private body' });
  user.client.setQueryData(otherKey, { title: 'other authorized scope' });
  await user.click(screen.getByRole('button', { name: '切换合成项目' }));
  expect(user.client.getQueryData(activeKey)).toBeUndefined();
  expect(user.client.getQueryData(contentKey)).toBeUndefined();
  expect(user.client.getQueryData(otherKey)).toBeDefined();
});

test('closes the search tab and provides a working way to reopen it from the empty reader', async () => {
  const user = mount();
  await user.click(screen.getByRole('button', { name: '关闭搜索标签' }));
  expect(screen.queryByRole('tab', { name: '搜索' })).toBeNull();
  expect(screen.queryByText('搜索控制器')).toBeNull();
  await user.click(screen.getByRole('button', { name: '搜索项目资料' }));
  expect(screen.getByRole('tab', { name: '搜索' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByText('搜索控制器')).toBeVisible();
});

test('restores focus after closing a file and refuses an old-scope delayed focus callback', async () => {
  const callbacks: FrameRequestCallback[] = [];
  const frame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { callbacks.push(callback); return callbacks.length; });
  try {
    const user = mount();
    await user.click(screen.getByRole('button', { name: '查看运行手册.md资料详情' }));
    await user.click(screen.getByRole('button', { name: '关闭运行手册.md标签' }));
    act(() => { callbacks.splice(0).forEach(callback => callback(performance.now())); });
    expect(screen.getByRole('tab', { name: '搜索' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: '查看运行手册.md资料详情' }));
    await user.click(screen.getByRole('button', { name: '关闭运行手册.md标签' }));
    await user.click(screen.getByRole('button', { name: '切换合成项目' }));
    (document.activeElement as HTMLElement).blur();
    expect(document.activeElement).toBe(document.body);
    act(() => { callbacks.splice(0).forEach(callback => callback(performance.now())); });
    expect(screen.getByRole('tab', { name: '搜索' })).not.toHaveFocus();
  } finally { frame.mockRestore(); }
});

test('stores only the reference metadata observed by a reactivated citation controller', async () => {
  observedReferences.length = 0;
  const user = mount();
  await user.click(screen.getByRole('button', { name: '打开合成引用' }));
  expect(await screen.findByText('活动引用：运行手册引用')).toBeVisible();
  await user.click(screen.getByRole('button', { name: '查看架构说明.md资料详情' }));
  expect(screen.queryByText('活动引用：运行手册引用')).toBeNull();
  await user.click(screen.getByRole('tab', { name: '运行手册引用 · 引用上下文' }));
  expect(await screen.findByText('活动引用：运行手册引用')).toBeVisible();
  expect(observedReferences.length).toBeGreaterThanOrEqual(2);
  expect(observedReferences.at(-1)).toEqual({ resourceId: 'first', resourceVersionId: 'version', chunkId: 'chunk', title: '运行手册引用' });
  expect(observedReferences.at(-1)).not.toBe(citationFixture);
});
