// index.html 的静态契约。
//
// Day 8 起这个文件断言的东西少了很多，因为页面结构搬进了 React 组件——
// header/nav/main 不再存在于静态 HTML 里，它们由组件在运行时生成。
// 那些断言没有被删掉，而是搬到了 verify-web.mjs 的"结构关卡"，
// 在真实渲染后的 DOM 上检查。断言该待在被断言的东西真正存在的那一层。
//
// 留在这里的是 index.html **仍然真正拥有**的东西：语言、字符集、样式表、挂载点、入口。
// 这些必须在 JS 执行之前就正确，所以它们属于静态文件，也该在静态测试里守住。

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parse } from 'node-html-parser';

const htmlUrl = new URL('../../index.html', import.meta.url);

async function readPage() {
  return parse(await readFile(htmlUrl, 'utf8'));
}

test('page declares language and charset before any script runs', async () => {
  const document = await readPage();

  // lang 决定读屏软件用哪种语音读这一页，必须在静态 HTML 上。
  // 交给组件设置就晚了——JS 执行前的那段时间它是无语言的。
  assert.equal(document.querySelector('html').getAttribute('lang'), 'zh-CN');
  assert.ok(document.querySelector('meta[charset]'), 'missing charset');
  assert.ok(document.querySelector('meta[name="viewport"]'), 'missing viewport');
});

test('stylesheet is linked statically, not injected by script', async () => {
  const document = await readPage();
  const link = document.querySelector('link[rel="stylesheet"]');

  assert.ok(link, 'missing stylesheet link');
  assert.equal(link.getAttribute('href'), 'styles/main.css');
});

test('theme initialization runs before the stylesheet is requested', async () => {
  const source = await readFile(htmlUrl, 'utf8');
  const themeIndex = source.indexOf('localStorage.getItem("cairn-theme")');
  const stylesheetIndex = source.indexOf('rel="stylesheet"');

  assert.ok(themeIndex >= 0, 'missing pre-paint theme initialization');
  assert.ok(stylesheetIndex >= 0, 'missing stylesheet link');
  assert.ok(themeIndex < stylesheetIndex, 'theme must be selected before CSS paint');
});

test('page provides a mount point for the React tree', async () => {
  const document = await readPage();

  assert.ok(document.querySelector('#root'), 'missing #root mount point');

  // 挂载点必须是空的。React 会接管这个节点的全部内容，
  // 里面预先放的任何东西都会在首次渲染时被抹掉——
  // 那种"先放骨架防白屏"的写法在 createRoot 下不成立，只会闪一下然后消失。
  assert.equal(document.querySelector('#root').innerHTML.trim(), '');
});

test('page loads the app as an ES module', async () => {
  const document = await readPage();
  const script = document.querySelector('script[src]');

  assert.ok(script, 'missing app script');
  // type="module" 不是可选项：入口里有 import 语句，
  // 换成普通 <script> 会在第一行直接抛 SyntaxError: Cannot use import statement outside a module。
  assert.equal(script.getAttribute('type'), 'module');
  // Day 8 起入口是 .tsx。浏览器读不懂 JSX，理由和 Day 6 读不懂 .ts 完全相同：
  // 它的解析器看到 <div> 只会看到一个小于号。Vite 在 dev 即时转换、
  // build 时替换成 dist 里带 hash 的 .js。测试读源文件，所以断言 .tsx。
  assert.equal(script.getAttribute('src'), 'src/main.tsx');
});
