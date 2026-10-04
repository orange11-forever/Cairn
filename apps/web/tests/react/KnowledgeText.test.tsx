import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { KnowledgeText } from '../../src/components/knowledge/KnowledgeText.tsx';
test('renders document headings and literal unsafe HTML without loading remote media or unsafe links', () => {
  const { container } = render(<KnowledgeText text={'## 启动步骤\n\n<img src="https://invalid.example/tracker"> [危险](javascript:alert(1))'} />);
  expect(screen.getByRole('heading', { name: '启动步骤' })).toBeVisible();
  expect(container.querySelectorAll('img,a,script')).toHaveLength(0);
  expect(container).toHaveTextContent('<img');
});
test('copies only fenced code and reports a clipboard failure with manual recovery', async () => {
  const user = userEvent.setup();
  const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
  render(<KnowledgeText text={'命令\n\n```sh\npnpm dev:core\n```'} />);
  await user.click(screen.getByRole('button', { name: '复制代码' }));
  expect(write).toHaveBeenCalledWith('pnpm dev:core');
  expect(screen.getByText('已复制')).toBeVisible();
  write.mockRejectedValueOnce(new Error('Clipboard denied'));
  await user.click(screen.getByRole('button', { name: '复制代码' }));
  expect(await screen.findByRole('status')).toHaveTextContent('复制失败，请选中代码手动复制');
});
