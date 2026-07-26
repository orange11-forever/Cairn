import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parse } from 'node-html-parser';

const htmlUrl = new URL('../../apps/web/index.html', import.meta.url);

async function readPage() {
  return parse(await readFile(htmlUrl, 'utf8'));
}

test('page provides the primary semantic landmarks', async () => {
  const document = await readPage();

  assert.ok(document.querySelector('header'), 'missing <header>');
  assert.ok(document.querySelector('nav[aria-label]'), 'missing labeled <nav>');
  assert.ok(document.querySelector('main'), 'missing <main>');
});

test('page loads the app as an ES module', async () => {
  const document = await readPage();
  const script = document.querySelector('script[src]');

  assert.ok(script, 'missing app script');
  // type="module" 不是可选项：src/main.ts 里有 import 语句，
  // 换成普通 <script> 会在第一行直接抛 SyntaxError: Cannot use import statement outside a module。
  assert.equal(script.getAttribute('type'), 'module');
  // Day 7 起入口是 .ts：源 index.html 直接引 src/main.ts，Vite 在 dev 即时转换、
  // build 时替换成 dist 里带 hash 的产物。测试读的是源文件，所以断言 .ts。
  assert.equal(script.getAttribute('src'), 'src/main.ts');
});
