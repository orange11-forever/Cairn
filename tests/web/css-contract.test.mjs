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

test('page exposes stable layout and document-state hooks', async () => {
  const document = await readPage();

  assert.ok(document.querySelector('.documents-panel'));
  assert.ok(document.querySelector('.assistant-panel'));
  assert.ok(document.querySelector('.question-form'));

  // 列表现在是运行时渲染目标：必须存在且必须是空的。
  // 留任何硬编码 <li> 都会在真实数据到达前一闪而过，是 Day 4 六态之外的第七种假状态。
  const list = document.querySelector('#document-list.document-list');
  assert.ok(list, 'missing #document-list render target');
  assert.equal(list.querySelectorAll('li').length, 0, 'render target must start empty');

  assert.equal(document.querySelectorAll('[style]').length, 0);
});

test('status region is announced to assistive tech, not only colored', async () => {
  const document = await readPage();
  const status = document.querySelector('#status-bar');

  assert.ok(status, 'missing #status-bar');
  assert.equal(status.getAttribute('role'), 'status');
  assert.equal(status.getAttribute('aria-live'), 'polite');
});

test('stylesheet styles every document status the data layer can produce', async () => {
  const css = await readFile(cssUrl, 'utf8');
  const { DOCUMENT_STATUSES } = await import(
    new URL('../../apps/web/src/lib/documents.js', import.meta.url)
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

test('primary navigation exposes the current page semantically', async () => {
  const document = await readPage();
  const current = document.querySelector(
    'nav[aria-label="主导航"] a[aria-current="page"]',
  );

  assert.ok(current, 'missing current-page navigation state');
  assert.equal(current.text.trim(), '知识文档');
});
