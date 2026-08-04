// 用真实无头 Chromium 把 apps/web 的六态跑一遍，并断言零控制台错误。
// 静态测试（tests/web/）只看 HTML/CSS 文本，证明不了模块能加载、fetch 能通、状态机能转。
//
// 运行：node scripts/verify-web.mjs
//
// Day 7 起前端由 Vite 提供：源码里有 .ts，浏览器读不懂类型语法（Day 6 实测），
// 必须经过 Vite 的转换才能加载。这里起的是 dev server，因为它是开发时的真实路径；
// 生产构建路径由 `pnpm build` 单独覆盖。

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

import { spawnInvocation } from "../../../scripts/spawn-command.mjs";

import {
  assertPortAvailable,
  settleCleanupTasks,
  stopProcessTree,
  waitForChildSpawn,
  waitForServer,
} from "./process-utils.mjs";
import { checkResponsiveFoundation } from "./verify-responsive.mjs";

const WEB_ROOT = fileURLToPath(new URL("..", import.meta.url));
const ROOT = join(WEB_ROOT, "../..");
const SHOT_DIR = join(ROOT, "apps/web/screenshots");
mkdirSync(SHOT_DIR, { recursive: true });

function readPort(name, fallback) {
  const raw = process.env[name] ?? String(fallback);
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be an integer between 1 and 65535, received ${raw}`);
  }
  return port;
}

const WEB_PORT = readPort("CAIRN_VERIFY_WEB_PORT", 5500);
const MOCK_PORT = readPort("CAIRN_VERIFY_MOCK_PORT", 8787);
const WEB = `http://localhost:${WEB_PORT}`;
const MOCK_ORIGIN = `http://localhost:${MOCK_PORT}`;
const MOCK_HEALTH = `${MOCK_ORIGIN}/health`;

// Vite dev server。
//
// macOS/Linux 把子进程放进独立进程组，结束时杀整组；Windows 使用 taskkill
// 递归结束 pnpm、Vite 及其子进程。shell 保持关闭，避免平台 shell 差异。
const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const managedOptions = {
  cwd: WEB_ROOT,
  stdio: "ignore",
  shell: false,
  detached: process.platform !== "win32",
};
const mockOptions = {
  ...managedOptions,
  env: { ...process.env, CAIRN_MOCK_PORT: String(MOCK_PORT) },
};
const webOptions = {
  ...managedOptions,
  env: { ...process.env, VITE_API_URL: MOCK_ORIGIN },
};

let mock = null;
let web = null;
let browser = null;
let page = null;

// 「控制台零错误」是 Day 5 的硬验收项，但要分清两类：
//
// 1. JS 层错误（未捕获异常、Promise rejection、模块加载失败）——必须为零。
//    这类代表代码有 bug。
// 2. 网络层日志（"Failed to load resource: 500" / ERR_CONNECTION_REFUSED）——预期存在。
//    浏览器对每个失败请求都会记一条，应用代码无法抑制。我们本来就在故意制造
//    500 和断网场景，这两条恰恰证明请求真的发出去并真的失败了。
const jsErrors = [];
const networkNotices = [];

const frames = [];

async function snapshot(label) {
  const status = await page.$eval("#status-bar", (el) => ({
    tone: el.dataset.tone,
    text: el.textContent.trim(),
  }));
  const rows = await page.$$eval("#document-list li", (els) => els.length);
  const buttons = await page.evaluate(() => ({
    load: document.getElementById("load-btn").disabled,
    cancel: document.getElementById("cancel-btn").disabled,
  }));
  await page.screenshot({ path: join(SHOT_DIR, `${label}.png`), fullPage: true });
  frames.push({ label, ...status, rows, ...buttons });
}

async function loadWith(scenario) {
  await page.selectOption("#scenario", scenario);
  await page.click("#load-btn");
  await waitForStatus(/加载中/);
}

const waitForStatus = (pattern) =>
  page.waitForFunction(
    (src) => new RegExp(src).test(document.querySelector("#status-bar").textContent),
    pattern.source,
    { timeout: 8000 },
  );

/**
 * 结构关卡（Day 8 加）。
 *
 * 这些断言原来读 index.html 的静态文本。React 接管后结构由组件在运行时生成，
 * 静态文件里只剩一个空壳，于是检查跟着搬到结构真正存在的地方——渲染后的 DOM。
 *
 * 有一条因此变强了：「渲染目标必须初始为空」原来是查静态 HTML 里没硬编码 <li>，
 * React 下那个查法失去意义（壳里当然没有）。现在它查的是首帧真的是 0 行，
 * 那才是这条断言当初想防的东西：真实数据到达前闪一下假状态。
 */
async function checkLoginPage() {
  console.log("\n=== 登录页关卡（Day 9）===\n");

  expect(await page.isVisible(".login-card"), "未登录时应当显示登录卡片");
  // 门的另一半：工作台在登录前**必须不存在**。
  // 只查"登录页出现了"是不够的——两个都渲染出来（登录页浮在上面）也能过。
  expect(!(await page.isVisible("main.workspace")), "未登录时不该渲染工作台");
  expect((await page.$("#status-bar")) === null, "未登录时不该渲染文档状态条");

  // 空提交 → 两条可读错误
  await page.click(".login-submit");
  const emptyErrors = await page.$$eval('[role="alert"]', (els) =>
    els.map((el) => el.textContent.trim()),
  );
  expect(
    emptyErrors.length === 2,
    `空提交应报两条错误（邮箱+密码），实际 ${emptyErrors.length} 条：${emptyErrors.join(" / ")}`,
  );
  expect(
    emptyErrors[0] === "请填写邮箱" && emptyErrors[1] === "请填写密码",
    `错误文案不对：${emptyErrors.join(" / ")}`,
  );

  // 出错字段被标记，且错误文案通过 aria-describedby 关联上去
  const emailAria = await page.$eval("#login-email", (el) => ({
    invalid: el.getAttribute("aria-invalid"),
    describedBy: el.getAttribute("aria-describedby"),
  }));
  expect(emailAria.invalid === "true", `出错字段应有 aria-invalid="true"，实际 ${emailAria.invalid}`);
  expect(
    emailAria.describedBy === "login-email-error",
    `错误文案应通过 aria-describedby 关联，实际 ${emailAria.describedBy}`,
  );

  // 焦点落在第一个出错的字段上。
  // 这一条是真浏览器独有的价值：jsdom 里 focus() 只是记一个标记，
  // 真实浏览器里它涉及焦点环、滚动进视野、以及被别的元素抢焦点的可能。
  const focused = await page.evaluate(() => document.activeElement?.id ?? null);
  expect(focused === "login-email", `焦点应在第一个出错字段上，实际在 ${focused}`);

  // 格式错误的文案要说清怎么改
  await page.fill("#login-email", "zhangsan");
  await page.fill("#login-password", "cairn-demo-2026");
  await page.click(".login-submit");
  const formatError = (await page.textContent("#login-email-error")).trim();
  expect(
    formatError === "邮箱缺少 @，例如 name@company.com",
    `邮箱错误应当说清怎么改，实际："${formatError}"`,
  );

  // 服务端错误：密码错 → 401。
  // 这是登录页关卡的核心——它证明真的发出了请求、真的处理了 401，
  // 而且错误显示在表单级别而不是挂在某个字段上。
  await page.fill("#login-email", "demo@cairn.dev");
  await page.fill("#login-password", "wrongpassword");
  await page.click(".login-submit");
  await page.waitForSelector(".form-error", { timeout: 8000 });

  const serverError = await page.textContent(".form-error");
  expect(serverError.includes("邮箱或密码不正确"), `401 文案不对："${serverError.trim()}"`);
  expect(!serverError.includes("可以再试一次"), "401 不该提示重试——密码错了重试一万次还是错");

  // 服务端错误不该把字段标记成无效：真正错的可能是邮箱，
  // 挂到密码上会让用户盯着密码反复改。
  const fieldsAfter401 = await page.evaluate(() => ({
    email: document.getElementById("login-email").getAttribute("aria-invalid"),
    password: document.getElementById("login-password").getAttribute("aria-invalid"),
  }));
  expect(
    fieldsAfter401.email === null && fieldsAfter401.password === null,
    `服务端错误不该标记字段无效，实际 email=${fieldsAfter401.email} password=${fieldsAfter401.password}`,
  );

  await page.screenshot({ path: join(SHOT_DIR, "L0-login-errors.png"), fullPage: true });
}

/**
 * 用演示账号登录，进入工作台。**既有八帧的前置步骤。**
 *
 * 这是 Day 9 对 verify-web.mjs 唯一的侵入式改动，界线要说清楚：
 * 八帧的**断言一行没改**，改的只是到达被测状态的路径。
 * 改断言 = 换裁判（Day 7/Day 8 各学过一次），加前置步骤 = 走真实入口。
 * 登录一坏这八帧全红，那是对的——真实用户也进不去。
 */
async function login() {
  await page.fill("#login-email", "demo@cairn.dev");
  await page.fill("#login-password", "cairn-demo-2026");
  await page.click(".login-submit");
  // 等工作台出现，而不是等固定毫秒数：登录请求有 700ms 延迟，
  // 固定等待会在慢机器上间歇性抢跑，而报出来的错是"找不到 #status-bar"，
  // 看起来像组件没渲染。
  await page.waitForSelector("main.workspace", { timeout: 10000 });
}

async function logout() {
  const menu = page.locator(".account-menu");
  if (!(await menu.getAttribute("open"))) await menu.locator("summary").click();
  await menu.getByRole("button", { name: "退出" }).click();
  await page.waitForSelector(".login-card");
}

async function checkStructure() {
  const found = await page.evaluate(() => ({
    header: !!document.querySelector("header.product-header"),
    nav: !!document.querySelector('nav[aria-label="主导航"]'),
    main: !!document.querySelector("main.workspace"),
    documentsPanel: !!document.querySelector(".documents-panel"),
    assistantPanel: !!document.querySelector(".assistant-panel"),
    questionForm: !!document.querySelector(".question-form"),
    uploadZone: !!document.querySelector(".upload-zone"),
    currentNavLabel:
      document
        .querySelector('nav[aria-label="主导航"] a[aria-current="page"]')
        ?.getAttribute("aria-label") ?? null,
    statusRole: document.querySelector("#status-bar")?.getAttribute("role") ?? null,
    statusLive: document.querySelector("#status-bar")?.getAttribute("aria-live") ?? null,
    inlineStyles: document.querySelectorAll("[style]").length,
    initialRows: document.querySelectorAll("#document-list li").length,
    // Day 9：登录后顶栏要显示当前身份 + 退出入口。
    // 看不到自己是谁，企业环境里会在错误的账号下上传文档。
    currentUser: document.querySelector(".current-user")?.textContent.trim() ?? null,
    hasLogout: !!document.querySelector(".logout-btn"),
    workspaceWidth: document.querySelector("main.workspace")?.getBoundingClientRect().width ?? 0,
    panelWidth: document.querySelector(".documents-panel")?.getBoundingClientRect().width ?? 0,
  }));

  console.log("\n=== 结构关卡 ===\n");
  expect(found.header, "缺少 header.product-header");
  expect(found.nav, "缺少带 aria-label 的主导航");
  expect(found.main, "缺少 main.workspace");
  expect(found.documentsPanel, "缺少 .documents-panel");
  expect(!found.assistantPanel, "文档页不应渲染 .assistant-panel");
  expect(!found.questionForm, "文档页不应渲染 .question-form");
  expect(found.uploadZone, "文档页缺少 .upload-zone");
  expect(found.currentNavLabel === "知识文档",
    `当前页导航项应为「知识文档」，实际 ${found.currentNavLabel}`);
  // 状态区必须被读屏软件播报，不能只靠颜色传达——颜色对色盲用户不存在。
  expect(found.statusRole === "status", `#status-bar 的 role 应为 status，实际 ${found.statusRole}`);
  expect(found.statusLive === "polite", `#status-bar 的 aria-live 应为 polite，实际 ${found.statusLive}`);
  expect(found.inlineStyles === 0, `不应有内联样式，实际 ${found.inlineStyles} 处`);
  expect(found.initialRows === 0, `首帧列表应为 0 行，实际 ${found.initialRows} 行`);

  // ---- Day 9 追加的结构断言 ----
  expect(
    found.currentUser === "演示用户",
    `顶栏应显示当前用户「演示用户」，实际 ${found.currentUser}`,
  );
  expect(found.hasLogout, "顶栏缺少退出按钮");
  expect(
    Math.abs(found.workspaceWidth - found.panelWidth) < 1,
    `文档面板应占满工作区，实际 ${found.panelWidth}px / ${found.workspaceWidth}px`,
  );
}

async function checkAskStructure() {
  await page.evaluate(() => {
    window.__cairnNavigationSentinel = "alive";
  });
  await page.getByRole("link", { name: "知识问答" }).click();
  await page.waitForSelector(".assistant-panel");

  expect(
    (await page.evaluate(() => window.__cairnNavigationSentinel)) === "alive",
    "应用内导航发生了整页刷新",
  );
  expect(new URL(page.url()).pathname === "/ask", "知识问答路由不正确");

  const found = await page.evaluate(() => ({
    documentsPanel: !!document.querySelector(".documents-panel"),
    assistantPanel: !!document.querySelector(".assistant-panel"),
    questionForm: !!document.querySelector(".question-form"),
    currentNavLabel:
      document
        .querySelector('nav[aria-label="主导航"] a[aria-current="page"]')
        ?.getAttribute("aria-label") ?? null,
    workspaceWidth: document.querySelector("main.workspace")?.getBoundingClientRect().width ?? 0,
    panelWidth: document.querySelector(".assistant-panel")?.getBoundingClientRect().width ?? 0,
  }));

  expect(!found.documentsPanel, "问答页不应渲染 .documents-panel");
  expect(found.assistantPanel, "问答页缺少 .assistant-panel");
  expect(found.questionForm, "问答页缺少 .question-form");
  expect(
    found.currentNavLabel === "知识问答",
    `当前页导航项应为「知识问答」，实际 ${found.currentNavLabel}`,
  );
  expect(
    Math.abs(found.workspaceWidth - found.panelWidth) < 1,
    `问答面板应占满工作区，实际 ${found.panelWidth}px / ${found.workspaceWidth}px`,
  );

  await page.getByRole("link", { name: "知识文档" }).click();
  await page.waitForSelector(".documents-panel");
  expect(new URL(page.url()).pathname === "/documents", "知识文档路由不正确");
}

async function checkAuthenticatedUnknownRoute() {
  await page.evaluate(() => {
    history.pushState({}, "", "/unknown");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.waitForURL((url) => url.pathname === "/documents");
  expect(
    new URL(page.url()).pathname === "/documents",
    "已登录未知路径应重定向到文档页",
  );
}

async function logoutAndLogin() {
  await logout();
  await login();
}

async function checkSessionIsolation() {
  console.log("\n=== 会话隔离关卡 ===\n");

  const beforeLogout = await page.$$eval("#document-list li", (items) => items.length);
  expect(beforeLogout === 4, `退出前应有 4 条文档作为缓存清理前置条件，实际 ${beforeLogout}`);

  await logoutAndLogin();
  const afterLogin = await page.evaluate(() => ({
    rows: document.querySelectorAll("#document-list li").length,
    status: document.querySelector("#status-bar")?.textContent.trim() ?? null,
  }));
  expect(afterLogin.rows === 0, `重新登录不应看到上一会话文档，实际 ${afterLogin.rows} 条`);
  expect(
    afterLogin.status === "点击「加载文档」开始",
    `重新登录应回到 idle，实际「${afterLogin.status}」`,
  );
  await page.screenshot({ path: join(SHOT_DIR, "S1-session-cleared.png"), fullPage: true });

  await loadWith("slow");
  await logout();
  await login();
  await page.waitForTimeout(5500);

  const afterSlowResponse = await page.evaluate(() => ({
    rows: document.querySelectorAll("#document-list li").length,
    status: document.querySelector("#status-bar")?.textContent.trim() ?? null,
  }));
  expect(
    afterSlowResponse.rows === 0,
    `旧会话慢请求不应回填下一会话，实际 ${afterSlowResponse.rows} 条`,
  );
  expect(
    afterSlowResponse.status === "点击「加载文档」开始",
    `旧会话慢请求结束后新会话应保持 idle，实际「${afterSlowResponse.status}」`,
  );
  await page.screenshot({ path: join(SHOT_DIR, "S2-slow-session-isolated.png"), fullPage: true });
}

/**
 * 自动滚动帧（Day 9 加）。
 *
 * 这一帧存在的理由是能力边界：jsdom 没有布局引擎，scrollHeight/clientHeight
 * 全返回 0，于是"是否滚到底了"这个断言在组件测试里会 0 === 0 假通过。
 * 它**只能**在真浏览器里验证。tests/react/MessageList.test.tsx 的文件头
 * 记了这条，这里是它的另一半。
 */
async function checkAutoScroll() {
  console.log("\n=== 自动滚动帧（Day 9）===\n");

  // 连问几轮，把内容撑到超过容器高度（max-height: 420px）
  for (let i = 1; i <= 4; i += 1) {
    await page.fill("#question", `第 ${i} 个问题：值班故障如何升级？`);
    await page.click('.question-form button[type="submit"]');
    // 每轮等回答落地（mock 延迟 1500ms）
    await page.waitForFunction(
      (n) => document.querySelectorAll("#message-list > li").length === n,
      i * 2,
      { timeout: 8000 },
    );
  }

  const scroll = await page.$eval(".message-scroll", (el) => ({
    scrollTop: el.scrollTop,
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
  }));

  // 前置条件：内容真的溢出了。不查这个的话，容器没溢出时
  // scrollTop === 0 且距底为 0，下面的断言会假通过。
  expect(
    scroll.scrollHeight > scroll.clientHeight,
    `内容没有溢出容器（${scroll.scrollHeight} vs ${scroll.clientHeight}），这一帧无意义`,
  );

  const distanceFromBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight;
  expect(
    distanceFromBottom <= 40,
    `新消息到达后应当滚到底部，实际距底 ${distanceFromBottom}px`,
  );

  // 反向：用户往上翻之后，新消息**不该**把他弹回底部。
  // 这是 useAutoScroll 里 stickToBottom 那个 ref 的全部意义，
  // 而它是这个 Hook 最容易被写错的地方（无条件滚是最常见的实现）。
  await page.$eval(".message-scroll", (el) => {
    el.scrollTop = 0;
  });
  // 等 scroll 事件被处理（监听器是 passive 的，异步触发）
  await page.waitForTimeout(200);

  await page.fill("#question", "用户正在读历史时来的新消息");
  await page.click('.question-form button[type="submit"]');
  await page.waitForFunction(() => document.querySelectorAll("#message-list > li").length === 10, {
    timeout: 8000,
  });

  const afterScrollUp = await page.$eval(".message-scroll", (el) => el.scrollTop);
  expect(
    afterScrollUp < 40,
    `用户翻到顶部后不该被弹回底部，实际 scrollTop=${afterScrollUp}`,
  );

  await page.screenshot({ path: join(SHOT_DIR, "9-auto-scroll.png"), fullPage: true });
}

/**
 * 取消提问帧（Day 9 加）。
 *
 * 验的是一整条链路：UI 的「停止生成」→ useAsyncAction.cancel →
 * AbortController.abort → 传给 askQuestion 的 signal → request → fetch。
 * 中间任何一环漏传 signal，UI 照样会显示"已停止"而请求还在飞。
 *
 * 判据不是"按钮点了没报错"，是**请求真的终止了**：
 * 用 Playwright 监听 requestfinished 之外还查那条乐观插入的提问被撤掉了。
 */
async function checkCancelQuestion() {
  console.log("\n=== 取消提问帧（Day 9）===\n");

  const before = await page.$$eval("#message-list > li", (els) => els.length);

  const QUESTION = "这个问题会被中途取消";
  await page.fill("#question", QUESTION);
  await page.click('.question-form button[type="submit"]');

  // 等待占位出现，证明请求真的在飞
  await page.waitForSelector('[data-role="pending"]', { timeout: 6000 });
  const duringPending = await page.evaluate(() => ({
    inputDisabled: document.querySelector("#question").disabled,
    hasCancel: !!document.querySelector(".question-actions .cancel-btn"),
    optimisticShown: [...document.querySelectorAll(".message-text")].some((el) =>
      el.textContent.includes("这个问题会被中途取消"),
    ),
  }));

  // 乐观更新：提问在等回答期间就该显示出来
  expect(duringPending.optimisticShown, "等待期间应当已显示用户的提问（乐观更新）");
  expect(duringPending.inputDisabled, "等回答时输入框应当禁用");
  expect(duringPending.hasCancel, "等回答时应当出现「停止生成」按钮");

  await page.screenshot({ path: join(SHOT_DIR, "10-question-pending.png"), fullPage: true });

  await page.click(".question-actions .cancel-btn");

  // 等占位消失
  await page.waitForFunction(() => document.querySelector('[data-role="pending"]') === null, {
    timeout: 6000,
  });

  const after = await page.evaluate(() => ({
    count: document.querySelectorAll("#message-list > li").length,
    stillHasQuestion: [...document.querySelectorAll(".message-text")].some((el) =>
      el.textContent.includes("这个问题会被中途取消"),
    ),
    hasError: !!document.querySelector(".assistant-panel .form-error"),
    inputDisabled: document.querySelector("#question").disabled,
  }));

  // 回滚：那条提问必须撤掉，否则留下一条永远等不到回答的孤儿
  expect(!after.stillHasQuestion, "取消后应当撤掉那条提问，不留孤儿");
  expect(after.count === before, `消息数应回到取消前的 ${before}，实际 ${after.count}`);
  // 取消不是错误（同 documentStore 的判断）
  expect(!after.hasError, "用户主动取消不该弹错误");
  // 回到可以重新提问的状态
  expect(!after.inputDisabled, "取消后输入框应当重新可用");

  // 再等一会儿：mock 的 /api/ask 要 1500ms 才响应。
  // 如果取消没真的生效，那个响应会在这段时间里到达并把回答塞进列表。
  // 这一步是"请求真的终止了"最直接的证据——比查 signal.aborted 更硬，
  // 因为它验的是**结果**而不是中间状态。
  await page.waitForTimeout(2000);
  const afterWait = await page.$$eval("#message-list > li", (els) => els.length);
  expect(
    afterWait === before,
    `取消后 2 秒仍不该有新消息（说明请求没真的终止），实际 ${afterWait} 条`,
  );

  await page.screenshot({ path: join(SHOT_DIR, "11-question-cancelled.png"), fullPage: true });
}

/**
 * 上传表单帧（Day 9 加）。
 *
 * 验的是"每个文件的错误挨着那个文件"以及服务端 415/413 的处理。
 */
async function checkUploadForm() {
  console.log("\n=== 上传表单帧（Day 9）===\n");

  // 选一个合法文件 + 一个不支持的类型。
  // setInputFiles 不受 accept 属性约束（和 userEvent 的默认行为不同），
  // 这里正好模拟"用户在系统选择器里切到所有文件"的真实场景。
  await page.setInputFiles("#upload-input", [
    { name: "需求文档.pdf", mimeType: "application/pdf", buffer: Buffer.from("ok") },
    { name: "virus.exe", mimeType: "application/octet-stream", buffer: Buffer.from("bad") },
  ]);

  const perFile = await page.evaluate(() =>
    [...document.querySelectorAll(".upload-selection li")].map((li) => ({
      name: li.querySelector(".upload-file-name")?.textContent.trim() ?? null,
      error: li.querySelector(".field-error")?.textContent.trim() ?? null,
      invalid: li.dataset.invalid ?? null,
    })),
  );

  expect(perFile.length === 2, `应当列出 2 个已选文件，实际 ${perFile.length}`);
  // 关键：错误挨着出错的那个文件，合法的那个旁边没有错误。
  // 这条断言拦得住"把所有错误堆在表单顶部"那种实现——那种实现下
  // 两个 li 里都没有 .field-error。
  expect(perFile[0]?.error === null, `合法文件旁边不该有错误，实际："${perFile[0]?.error}"`);
  expect(
    perFile[1]?.error?.includes("不支持 .exe 格式") === true,
    `不支持的类型应报在它自己那一行，实际："${perFile[1]?.error}"`,
  );
  expect(perFile[1]?.invalid === "true", "出错的文件项应标记 data-invalid");

  await page.screenshot({ path: join(SHOT_DIR, "12-upload-errors.png"), fullPage: true });

  // 换成两个合法文件，走通真上传
  await page.setInputFiles("#upload-input", [
    { name: "需求文档.pdf", mimeType: "application/pdf", buffer: Buffer.from("ok") },
    { name: "值班流程.md", mimeType: "text/markdown", buffer: Buffer.from("# on-call") },
  ]);
  await page.click('.upload-zone button[type="submit"]');
  await page.waitForSelector(".upload-result", { timeout: 8000 });

  const result = await page.textContent(".upload-result");
  expect(result.includes("已接受 2 个文件"), `上传结果文案不对："${result.trim()}"`);
  // 说的是"加入处理队列"不是"上传成功"——文档还没被解析和索引
  expect(result.includes("加入处理队列"), "应当说明文档还在排队处理，而不是说上传成功");
  expect(!result.includes("上传成功"), "不该说「上传成功」——会让用户立刻去提问然后失望");

  // 成功后清空选择，能接着传下一批
  const clearedCount = await page.$eval(".upload-zone", (el) => el.dataset.selectedCount);
  expect(clearedCount === "0", `成功后应清空选择，实际 data-selected-count="${clearedCount}"`);

  await page.screenshot({ path: join(SHOT_DIR, "13-upload-accepted.png"), fullPage: true });
}

/**
 * 状态筛选帧（Day 9 加）。
 *
 * 验 useMemo 派生出来的筛选结果和角标计数。
 */
async function checkStatusFilter() {
  console.log("\n=== 状态筛选帧（Day 9）===\n");

  const options = await page.$$eval(".status-filter-option", (els) =>
    els.map((el) => el.textContent.trim()),
  );
  // 角标统计的是**全部**文档，不是筛选后的。
  // mock 数据是 2 completed / 1 processing / 1 failed。
  expect(
    options.join(" | ") === "全部 4 | 已就绪 2 | 处理中 1 | 处理失败 1",
    `筛选器角标不对：${options.join(" | ")}`,
  );

  // 筛到"处理中"应当只剩 1 行
  await page.click(".status-filter-option:has-text('处理中')");
  await page.waitForFunction(
    () => document.querySelectorAll("#document-list li").length === 1,
    { timeout: 4000 },
  );

  const filtered = await page.evaluate(() => ({
    rows: document.querySelectorAll("#document-list li").length,
    state: document.querySelector("#document-list .document-status")?.dataset.state ?? null,
    // 角标不该跟着变——否则筛完之后其他角标全是 0，用户没法用它们判断该切到哪
    badges: [...document.querySelectorAll(".status-filter-option")].map((el) =>
      el.textContent.trim(),
    ),
  }));

  expect(filtered.rows === 1, `筛选「处理中」应剩 1 行，实际 ${filtered.rows}`);
  expect(filtered.state === "processing", `剩下那一行应是 processing，实际 ${filtered.state}`);
  expect(
    filtered.badges.join(" | ") === "全部 4 | 已就绪 2 | 处理中 1 | 处理失败 1",
    `角标应统计全部文档而非筛选后，实际：${filtered.badges.join(" | ")}`,
  );

  await page.screenshot({ path: join(SHOT_DIR, "14-status-filter.png"), fullPage: true });

  // 切回全部，别污染后面的帧
  await page.click(".status-filter-option:has-text('全部')");
  await page.waitForFunction(() => document.querySelectorAll("#document-list li").length === 4, {
    timeout: 4000,
  });
}

let failed = false;

// 模块级：结构关卡（首帧后）和帧断言（末尾）都要用它。
// 原来它是 try 块里的 const，结构关卡在前面调用会撞 TDZ。
function expect(cond, message) {
  if (!cond) {
    console.error(`✗ ${message}`);
    failed = true;
  }
}

try {
  await Promise.all([assertPortAvailable(WEB_PORT), assertPortAvailable(MOCK_PORT)]);

  mock = spawn(process.execPath, [join(WEB_ROOT, "mocks/docs-server.mjs")], mockOptions);
  await waitForChildSpawn(mock);
  const viteInvocation = spawnInvocation(pnpm, [
    "exec",
    "vite",
    "--port",
    String(WEB_PORT),
    "--strictPort",
  ]);
  web = spawn(viteInvocation.command, viteInvocation.args, webOptions);
  await waitForChildSpawn(web);
  await Promise.all([waitForServer(WEB), waitForServer(MOCK_HEALTH)]);

  browser = await chromium.launch();
  page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (text.includes("Failed to load resource")) networkNotices.push(text);
    else jsErrors.push(text);
  });
  page.on("pageerror", (err) => jsErrors.push(`pageerror: ${err.message}`));
  page.on("requestfailed", (req) =>
    networkNotices.push(`requestfailed: ${req.url()} ${req.failure()?.errorText ?? ""}`),
  );

  await page.goto(`${WEB}/unknown`, { waitUntil: "networkidle" });
  await page.waitForURL((url) => url.pathname === "/login");
  expect(new URL(page.url()).pathname === "/login", "未登录未知路径应重定向到登录页");
  await page.goto(WEB, { waitUntil: "networkidle" });

  // Day 9：登录门。八帧之前必须先过这一关。
  //
  // 顺序有讲究：登录页关卡里有截图，而截图会污染「无内联样式」的检查
  //（见下面那段注释）。所以登录页关卡跑完之后要重新加载页面，
  // 让结构关卡拿到一个未被任何工具动过的 DOM。
  await checkLoginPage();

  await page.reload({ waitUntil: "networkidle" });
  await login();

  // 必须在第一次截图之前查结构。
  // Playwright 的 fullPage 截图会临时往页面注入样式，跑完留下内联样式残留——
  // 于是「不应有内联样式」会被测量工具自己弄脏。查未被任何工具动过的初始 DOM。
  await checkStructure();
  await checkAskStructure();
  await checkAuthenticatedUnknownRoute();

  await checkResponsiveFoundation({
    page,
    expect,
    screenshotDir: SHOT_DIR,
    login,
    logout,
  });
  expect(new URL(page.url()).pathname === "/documents", "响应式验收后应回到文档页");
  expect(
    (await page.locator("html").getAttribute("data-theme")) === "light",
    "响应式验收后应恢复日间主题",
  );
  expect(
    (await page.viewportSize())?.width === 1280 && (await page.viewportSize())?.height === 900,
    "响应式验收后应恢复 1280 x 900 视口",
  );

  await snapshot("0-idle");

  await loadWith("success");
  await waitForStatus(/已加载/);
  await snapshot("1-success");

  await loadWith("empty");
  await waitForStatus(/还没有文档/);
  await snapshot("2-empty");

  await loadWith("error");
  await waitForStatus(/服务器出错/);
  await snapshot("3-http-500");

  await loadWith("slow");
  await waitForStatus(/加载中/);
  await snapshot("4-loading");

  await page.click("#cancel-btn");
  await waitForStatus(/点击「加载文档」/);
  await snapshot("5-cancelled");

  await loadWith("slow");
  await waitForStatus(/请求超过/);
  await snapshot("6-timeout");

  // ---- 第九帧：文档查询重渲染不丢已选文件 ----
  //
  // 文档远端状态变化会触发整页重渲染，UploadZone 的本地文件选择不能因此丢失。
  await page.setInputFiles("#upload-input", {
    name: "污染测试.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("day8"),
  });

  const readLocalState = () =>
    page.evaluate(() => ({
      // 已选文件渲染成 .upload-selection 里的列表项；同时读 data-selected-count，
      // 那是 UploadZone 把自己的 state 直接暴露出来的属性。
      files: [...document.querySelectorAll(".upload-selection li")].map((li) =>
        li.textContent.trim(),
      ),
      selectedCount: document.querySelector(".upload-zone")?.dataset.selectedCount ?? null,
    }));

  const beforeLoad = await readLocalState();

  await loadWith("success");
  await waitForStatus(/已加载/);
  await snapshot("8-document-state-preserved");

  const afterLoad = await readLocalState();
  const afterRows = await page.$$eval("#document-list li", (els) => els.length);

  console.log("\n=== 第九帧：文档页本地状态 ===\n");
  // 先证明前置条件成立，否则后面全是 null === null 的假通过。
  expect(beforeLoad.files.length === 1,
    `选文件在加载前就没生效（实际 ${beforeLoad.files.length} 项），这一帧无意义`);

  expect(afterLoad.files.join("|") === beforeLoad.files.join("|"),
    `文档加载后已选文件变了：加载前 [${beforeLoad.files}]，加载后 [${afterLoad.files}]`);
  expect(afterLoad.selectedCount === "1",
    `UploadZone 的 state 应仍是 1 个文件，实际 data-selected-count="${afterLoad.selectedCount}"`);
  // 反向也要成立：本地 state 存在不该阻止服务端 state 正常更新。
  expect(afterRows === 4, `服务端状态应正常更新到 4 行，实际 ${afterRows} 行`);

  // 清掉已选文件，别污染后面的截图。
  await page.setInputFiles("#upload-input", []);

  // ---- Day 9 追加的四帧 ----
  //
  // 位置在「网络失败」帧**之前**：那一帧会 kill 掉 mock 后端，
  // 之后所有请求都失败，登录/提问/上传全都跑不了。
  //
  // 顺序也有依赖：状态筛选要求列表里有 4 行数据（上一帧刚加载完 success），
  // 所以它排在最前；上传成功后不影响列表（Day 10 才做自动刷新），所以位置自由；
  // 自动滚动和取消都动消息列表，取消排在自动滚动后面是因为它要断言
  // "消息数回到取消前"，前面有多少条不重要，只要数得准。
  await checkStatusFilter();
  await checkUploadForm();

  await page.getByRole("link", { name: "知识问答" }).click();
  await page.waitForSelector(".assistant-panel");
  await checkAutoScroll();
  await checkCancelQuestion();

  await page.getByRole("link", { name: "知识文档" }).click();
  await page.waitForSelector(".documents-panel");

  await checkSessionIsolation();

  mock.kill();
  await new Promise((r) => setTimeout(r, 400));
  await loadWith("success");
  await waitForStatus(/无法连接服务器/);
  await snapshot("7-network-down");

  console.log("\n=== 八帧结果 ===\n");
  console.log("帧".padEnd(18), "tone".padEnd(9), "rows", " load/cancel disabled", " 文案");
  for (const f of frames) {
    console.log(
      `[${f.label}]`.padEnd(18),
      String(f.tone).padEnd(9),
      String(f.rows).padEnd(5),
      `${f.load}/${f.cancel}`.padEnd(22),
      `"${f.text}"`,
    );
  }

  // ---- 断言 ----
  const byLabel = Object.fromEntries(frames.map((f) => [f.label, f]));
  expect(byLabel["1-success"].rows === 4, "success 应渲染 4 行");
  expect(byLabel["2-empty"].rows === 0 && byLabel["2-empty"].tone === "empty",
    "空数据应为 empty 语气且 0 行，而不是报错");
  expect(byLabel["5-cancelled"].tone === "idle",
    "用户取消应回到 idle，不该弹错误");
  expect(byLabel["4-loading"].cancel === false && byLabel["4-loading"].load === true,
    "加载中：取消按钮可用、加载按钮禁用");
  expect(byLabel["6-timeout"].tone === "error" && byLabel["7-network-down"].tone === "error",
    "超时与网络失败都应是 error 语气");
  expect(byLabel["6-timeout"].text !== byLabel["7-network-down"].text,
    "超时和网络失败的文案必须不同——否则 ApiError.kind 白分类了");

  if (jsErrors.length > 0) {
    console.error(`\n✗ JS 层错误 ${jsErrors.length} 条（必须为零）：`);
    for (const e of jsErrors) console.error(`   ${e}`);
    failed = true;
  } else {
    console.log("\n✓ JS 层零错误（无未捕获异常、无模块加载失败）");
  }

  // 网络层日志只报数不判失败。但要它 > 0——一条都没有反而说明
  // 500 和断网两帧根本没真的发出请求，那是测试自己失效了。
  console.log(`ⓘ 网络层失败日志 ${networkNotices.length} 条（预期存在，来自故意制造的 500 / 断网）：`);
  for (const n of new Set(networkNotices)) console.log(`   ${n}`);
  expect(networkNotices.length > 0, "网络层日志为 0 说明失败场景没真的发出请求");

  console.log(failed ? "\n✗ 验证未通过" : "\n✓ 八帧全部通过");
  console.log(`截图：${SHOT_DIR}`);
} catch (error) {
  console.error("验证异常：", error instanceof Error ? error.message : String(error));
  failed = true;
} finally {
  const cleanupFailures = await settleCleanupTasks([
    { name: "Chromium", run: () => browser?.close() },
    { name: "Mock API", run: () => stopProcessTree(mock) },
    { name: "Vite", run: () => stopProcessTree(web) },
  ]);
  for (const failure of cleanupFailures) {
    console.error(`${failure.name} 清理失败：`, failure.reason);
  }
  if (cleanupFailures.length > 0) failed = true;
  process.exitCode = failed ? 1 : 0;
}
