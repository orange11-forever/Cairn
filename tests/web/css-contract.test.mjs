import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parse } from 'node-html-parser';

const htmlUrl = new URL('../../apps/web/index.html', import.meta.url);
const cssUrl = new URL('../../apps/web/styles/main.css', import.meta.url);

async function readPage() {
  return parse(await readFile(htmlUrl, 'utf8'));
}

test('page loads the external Tracebase stylesheet', async () => {
  const document = await readPage();
  const stylesheet = document.querySelector(
    'link[rel="stylesheet"][href="styles/main.css"]',
  );

  assert.ok(stylesheet, 'missing external stylesheet link');
  await assert.doesNotReject(readFile(cssUrl, 'utf8'));
});

// Day 8 起，结构断言（面板存在、渲染目标为空、无内联样式、导航当前项）
// 搬到了 verify-web.mjs 的结构关卡——结构由组件在运行时生成，
// 就去它真正存在的地方检查。
//
// 留在这一层的是**另一半契约**：CSS 文件必须仍然持有那些选择器。
// 这个方向同样会坏，而且坏得更隐蔽：组件把 class 改名后页面照样渲染，
// 只是样式静悄悄地不生效了——浏览器不会报错，测试也不会红，
// 只有肉眼看截图才发现布局塌了。所以两个方向都要守。
test('stylesheet keeps the layout hooks the components render', async () => {
  const css = await readFile(cssUrl, 'utf8');

  for (const hook of [
    '.product-header',
    '.workspace',
    '.documents-panel',
    '.assistant-panel',
    '.question-form',
    '.document-list',
  ]) {
    assert.match(
      css,
      new RegExp(hook.replace('.', '\\.')),
      `stylesheet lost the rule for ${hook} — components still render it`,
    );
  }

  // 状态色靠 data-* 属性选择器，不靠拼 class 名。
  // 这条约定是 Day 8 换掉整个渲染层却不用改一行 CSS 的原因。
  assert.match(css, /\[data-tone=/, 'stylesheet lost the [data-tone] status hook');
  assert.match(css, /\[data-state=/, 'stylesheet lost the [data-state] document hook');
});

test('stylesheet styles every document status the data layer can produce', async () => {
  const css = await readFile(cssUrl, 'utf8');
  const { DOCUMENT_STATUSES } = await import(
    new URL('../../apps/web/src/lib/documents.ts', import.meta.url)
  );

  // 数据层能产出的每个状态都必须有样式，包括兜底的 unknown。
  // 少一个，那类文档在页面上就是无色的裸文字——这正是搬迁时发现的 ready/completed 错配。
  for (const status of [...DOCUMENT_STATUSES, 'unknown']) {
    assert.match(
      css,
      new RegExp(`\\[data-state=['"]${status}['"]\\]`),
      `stylesheet has no rule for data-state="${status}"`,
    );
  }
});

test('stylesheet keeps focus visible and avoids priority escape hatches', async () => {
  const css = await readFile(cssUrl, 'utf8');

  assert.match(css, /:focus-visible/);
  assert.match(css, /@media \(max-width: 960px\)/);
  assert.doesNotMatch(css, /!important/);
  assert.doesNotMatch(css, /outline:\s*none/);
});

// 导航当前项、status region 的 role/aria-live、语义 landmark
// 都搬到 verify-web.mjs 的结构关卡了（同上：结构进了组件，检查跟着进浏览器）。
