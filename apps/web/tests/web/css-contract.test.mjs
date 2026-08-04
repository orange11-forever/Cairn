import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parse } from 'node-html-parser';

const htmlUrl = new URL('../../index.html', import.meta.url);
const cssUrl = new URL('../../styles/main.css', import.meta.url);

async function readPage() {
  return parse(await readFile(htmlUrl, 'utf8'));
}

test('page loads the external Cairn stylesheet', async () => {
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
    '.app-shell',
    '.product-header',
    '.primary-nav',
    '.account-menu',
    '.mascot-assistant',
    '.header-utilities',
    '.workspace',
    '.workspace-header',
    '.documents-panel',
    '.assistant-panel',
    '.question-form',
    '.document-list',
    // Day 9 新增的钩子。每一条都对应一个"没有样式就会静默坏掉"的东西：
    '.login-page', // 登录页整体布局，缺了它表单会贴在左上角
    '.form-field', // 字段的 label/input/错误三行间距
    '.field-error', // 错误文案的红色。它不是唯一信号（文案本身说清了问题），但缺了会很难注意到
    '.form-error', // 表单级错误的边框和底色，用来和字段级错误区分开
    '.status-filter', // 状态筛选器
    '.upload-selection', // 已选文件列表
    // 最关键的一条：.message-scroll 没有 max-height + overflow 时，
    // 容器会随内容无限长高，scrollHeight === clientHeight，自动滚动代码照跑
    // 但什么都不会发生。这是"JS 完全正确、CSS 缺一条"的失效。
    '.message-scroll',
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
  // Day 9：出错字段的红边同样走 data-* 而不是拼 class
  assert.match(css, /\[data-invalid=/, 'stylesheet lost the [data-invalid] form hook');
});

test('stylesheet defines semantic light and dark theme tokens', async () => {
  const css = await readFile(cssUrl, 'utf8');
  assert.match(css, /:root\[data-theme=['"]dark['"]\]/);
  for (const token of [
    '--color-canvas',
    '--color-surface',
    '--color-ink',
    '--color-border',
    '--color-idle-bg',
    '--color-loading-bg',
    '--color-success-bg',
    '--color-empty-bg',
    '--color-danger-bg',
    '--color-focus',
    '--color-mineral',
    '--color-jade',
    '--color-amber',
    '--color-coral',
  ]) {
    assert.match(css, new RegExp(`${token}:`), `missing theme token ${token}`);
  }
});

test('stylesheet covers every interactive surface rendered by current components', async () => {
  const css = await readFile(cssUrl, 'utf8');

  for (const hook of [
    '.login-card',
    '.field-hint',
    '.account-menu-panel',
    '.status-filter-option',
    '.upload-zone',
    '.upload-actions',
    '.question-actions',
    '.question-counter',
  ]) {
    assert.match(
      css,
      new RegExp(hook.replace('.', '\\.')),
      `stylesheet lost the rule for ${hook}`,
    );
  }
});

test('question form keeps action buttons aligned without stretching them', async () => {
  const css = await readFile(cssUrl, 'utf8');

  const formRule = css.match(/\.question-form\s*\{([^}]*)\}/);
  assert.ok(formRule, 'missing .question-form rule');
  assert.match(formRule[1], /align-items:\s*end/, '.question-form must align compact actions');

  const fieldRule = css.match(/\.question-form \.form-field\s*\{([^}]*)\}/);
  assert.ok(fieldRule, 'missing .question-form .form-field rule');
  assert.match(fieldRule[1], /margin-bottom:\s*0/, 'question field must not enlarge its grid row');
});

test('upload form keeps the native file input inside narrow panels', async () => {
  const css = await readFile(cssUrl, 'utf8');

  const uploadRule = css.match(/\.upload-zone\s*\{([^}]*)\}/);
  assert.ok(uploadRule, 'missing .upload-zone rule');
  assert.match(
    uploadRule[1],
    /grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    '.upload-zone needs a shrinkable grid track',
  );

  const inputRule = css.match(/\.upload-zone input\[type=['"]file['"]\]\s*\{([^}]*)\}/);
  assert.ok(inputRule, 'missing constrained upload file input rule');
  assert.match(inputRule[1], /min-width:\s*0/, 'file input must be allowed to shrink');
  assert.match(inputRule[1], /width:\s*100%/, 'file input must use the available track width');
});

// Day 9：自动滚动的 CSS 前提。
//
// 单独一个测试而不是并进上面那串 class 检查：那串只查"选择器还在"，
// 而这里要查的是**规则的内容**——.message-scroll 存在但没有 max-height，
// 自动滚动就完全不工作，而选择器检查会照样通过。
test('scroll container keeps the properties auto-scroll depends on', async () => {
  const css = await readFile(cssUrl, 'utf8');

  const rule = css.match(/\.message-scroll\s*\{([^}]*)\}/);
  assert.ok(rule, 'missing .message-scroll rule');

  // 没有 max-height：容器随内容长高，scrollHeight === clientHeight，
  // scrollTop 永远是 0。hooks/useAutoScroll.ts 里那行赋值照跑，什么都不会发生。
  assert.match(rule[1], /max-height:/, '.message-scroll needs max-height or it never scrolls');
  // 没有 overflow-y：内容溢出但不产生滚动条，同样没有可滚动的距离。
  assert.match(rule[1], /overflow-y:\s*auto/, '.message-scroll needs overflow-y: auto');
});

test('stylesheet styles every document status the data layer can produce', async () => {
  const css = await readFile(cssUrl, 'utf8');
  const { DOCUMENT_STATUSES } = await import(
    new URL('../../src/lib/documents.ts', import.meta.url)
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
  assert.match(css, /@media \(max-width: 1023px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(css, /!important/);
  assert.doesNotMatch(css, /outline:\s*none/);
});

test('stylesheet defines the approved tablet and mobile application-shell transitions', async () => {
  const css = await readFile(cssUrl, 'utf8');

  assert.match(css, /@media \(max-width:\s*1023px\)/);
  assert.match(css, /@media \(max-width:\s*599px\)/);
  assert.match(css, /min-height:\s*44px/, 'touch targets must be at least 44px high');
  assert.match(css, /env\(safe-area-inset-bottom\)/, 'mobile nav must reserve the safe area');

  const mobile = css.match(/@media \(max-width:\s*599px\)\s*\{([\s\S]*)\}\s*$/);
  assert.ok(mobile, 'missing final mobile media query');
  assert.match(mobile[1], /\.primary-nav[\s\S]*position:\s*fixed/);
  assert.match(mobile[1], /\.document-list li[\s\S]*grid-template-columns:\s*1fr/);
  assert.match(mobile[1], /\.question-form[\s\S]*grid-template-columns:\s*1fr/);
});

test('mascot thumbnails stay square and circular at every compact size', async () => {
  const css = await readFile(cssUrl, 'utf8');

  assert.match(css, /\.mascot-art\s*>\s*img/);
  assert.match(css, /border-radius:\s*50%/, 'thumbnail imagery must be circular');

  const assistantImage = css.match(
    /\.mascot-assistant-body \.mascot-figure\[data-variant=['"]half['"]\] \.mascot-art\s*>\s*img,\s*\.mascot-assistant-body \.mascot-figure\[data-variant=['"]half['"]\] \.mascot-image-fallback\s*\{([^}]*)\}/,
  );
  assert.ok(assistantImage, 'missing assistant thumbnail rule');
  assert.match(assistantImage[1], /width:\s*92px/);
  assert.match(assistantImage[1], /height:\s*92px/);

  const mobile = css.match(/@media \(max-width:\s*599px\)\s*\{([\s\S]*)\}\s*$/);
  assert.ok(mobile, 'missing mobile media query');
  assert.match(mobile[1], /width:\s*82px/);
  assert.match(mobile[1], /height:\s*82px/);
});

// 导航当前项、status region 的 role/aria-live、语义 landmark
// 都搬到 verify-web.mjs 的结构关卡了（同上：结构进了组件，检查跟着进浏览器）。
