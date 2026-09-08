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
    '.projects-page',
    '.knowledge-page',
    '.knowledge-upload-form',
    '.knowledge-search',
    '.knowledge-resource-list',
    // Day 9 新增的钩子。每一条都对应一个"没有样式就会静默坏掉"的东西：
    '.login-page', // 登录页整体布局，缺了它表单会贴在左上角
    '.form-field', // 字段的 label/input/错误三行间距
    '.field-error', // 错误文案的红色。它不是唯一信号（文案本身说清了问题），但缺了会很难注意到
    '.form-error', // 表单级错误的边框和底色，用来和字段级错误区分开
    '.knowledge-upload-drop-region',
  ]) {
    assert.match(
      css,
      new RegExp(hook.replace('.', '\\.')),
      `stylesheet lost the rule for ${hook} — components still render it`,
    );
  }

  // 状态色靠 data-* 属性选择器，不靠拼 class 名。
  // 这条约定是 Day 8 换掉整个渲染层却不用改一行 CSS 的原因。
  assert.match(css, /\[data-state=/, 'stylesheet lost the [data-state] resource hook');
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
    '--color-selected-surface',
    '--elevation-floating',
    '--motion-feedback',
    '--z-navigation',
    '--z-popover',
  ]) {
    assert.match(css, new RegExp(`${token}:`), `missing theme token ${token}`);
  }
});

test('navigation and project selection expose stable full-surface interaction states', async () => {
  const css = await readFile(cssUrl, 'utf8');

  const navHover = css.match(/\.primary-nav a:hover\s*\{([^}]*)\}/);
  assert.ok(navHover, 'primary navigation needs an explicit hover state');
  assert.match(navHover[1], /background:/, 'navigation hover needs surface feedback');
  assert.match(navHover[1], /text-decoration:\s*none/, 'navigation hover must not underline');

  const selectedNav = css.match(/\.primary-nav a\[aria-current=['"]page['"]\]\s*\{([^}]*)\}/);
  assert.ok(selectedNav, 'primary navigation needs a current-page state');
  assert.match(selectedNav[1], /box-shadow:\s*inset/, 'current navigation needs a stable inset boundary');

  const railButton = css.match(/\.project-rail button\s*\{([^}]*)\}/);
  assert.ok(railButton, 'missing project rail button rule');
  assert.match(railButton[1], /border:\s*1px solid transparent/, 'rail boundary must not shift layout');
  assert.doesNotMatch(railButton[1], /border-left:\s*3px/, 'rail must not use a selection stripe');

  const selectedProject = css.match(
    /\.project-rail button\[aria-pressed=['"]true['"]\]\s*\{([^}]*)\}/,
  );
  assert.ok(selectedProject, 'missing selected project surface');
  assert.match(selectedProject[1], /background:/, 'selected project needs full-surface feedback');
  assert.match(selectedProject[1], /box-shadow:\s*inset/, 'selected project needs an inset boundary');

  for (const selector of ['task-acceptance', 'task-transition-error']) {
    const rule = css.match(new RegExp(`\\.${selector}\\s*\\{([^}]*)\\}`));
    assert.ok(rule, `missing .${selector} rule`);
    assert.match(rule[1], /border:\s*1px solid/, `.${selector} needs a full boundary`);
    assert.doesNotMatch(rule[1], /border-left:\s*3px/, `.${selector} must not use a side stripe`);
  }
});

test('stylesheet covers every interactive surface rendered by current components', async () => {
  const css = await readFile(cssUrl, 'utf8');

  for (const hook of [
    '.login-card',
    '.field-hint',
    '.account-menu-panel',
    '.project-rail',
    '.task-knowledge-link',
    '.knowledge-upload-actions',
    '.knowledge-search-actions',
    '.knowledge-resource-operation-actions',
  ]) {
    assert.match(
      css,
      new RegExp(hook.replace('.', '\\.')),
      `stylesheet lost the rule for ${hook}`,
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

test('login full mascot uses transparent artwork instead of a photo frame', async () => {
  const css = await readFile(cssUrl, 'utf8');
  const rule = css.match(
    /\.login-brand-scene \.mascot-figure\[data-variant=['"]full['"]\] \.mascot-art\s*>\s*img,\s*\.login-brand-scene \.mascot-figure\[data-variant=['"]full['"]\] \.mascot-image-fallback\s*\{([^}]*)\}/,
  );

  assert.ok(rule, 'missing login full mascot rule');
  assert.match(rule[1], /padding:\s*0/);
  assert.match(rule[1], /border:\s*0/);
  assert.match(rule[1], /background:\s*transparent/);
  assert.match(rule[1], /filter:\s*drop-shadow\(/);
  assert.match(rule[1], /transform:\s*none/);
  assert.doesNotMatch(rule[1], /box-shadow:/);
});

test('projects top-level empty mascot stays frameless and compact on mobile', async () => {
  const css = await readFile(cssUrl, 'utf8');
  const full = css.match(
    /\.project-empty-state \.mascot-figure\[data-variant=['"]full['"]\] \.mascot-art\s*>\s*img,\s*\.project-empty-state \.mascot-figure\[data-variant=['"]full['"]\] \.mascot-image-fallback\s*\{([^}]*)\}/,
  );
  assert.ok(full, 'missing frameless Projects empty-state mascot rule');
  assert.match(full[1], /padding:\s*0/);
  assert.match(full[1], /border:\s*0/);
  assert.match(full[1], /background:\s*transparent/);

  const mobile = css.match(/@media \(max-width:\s*599px\)\s*\{([\s\S]*)\}\s*$/);
  assert.ok(mobile, 'missing mobile media query');
  const mobileMascot = mobile[1].match(
    /\.project-empty-state \.mascot-figure\[data-variant=['"]full['"]\] \.mascot-art\s*>\s*img,\s*\.project-empty-state \.mascot-figure\[data-variant=['"]full['"]\] \.mascot-image-fallback\s*\{([^}]*)\}/,
  );
  assert.ok(mobileMascot, 'missing compact mobile Projects mascot rule');
  assert.match(mobileMascot[1], /width:\s*120px/);
  assert.match(mobileMascot[1], /height:\s*120px/);
  assert.match(mobileMascot[1], /border-radius:\s*50%/);
});

// 导航当前项、status region 的 role/aria-live、语义 landmark
// 都搬到 verify-web.mjs 的结构关卡了（同上：结构进了组件，检查跟着进浏览器）。
