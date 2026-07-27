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

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SHOT_DIR = join(ROOT, "apps/web/screenshots");
mkdirSync(SHOT_DIR, { recursive: true });

const WEB = "http://localhost:5500";

// mock 后端用子进程起，这样「网络失败」那帧可以直接 kill 掉它
let mock = spawn("node", [join(ROOT, "mocks/docs-server.mjs")], { stdio: "ignore" });

// Vite dev server。
//
// detached:true 不是随手加的：shell:true 会让 spawn 返回的 pid 是那个 shell，
// web.kill() 只杀 shell，Vite 变孤儿进程继续占着 5500。下一次 verify 因为
// strictPort 直接失败，而报出来的错看起来像端口配置问题。
// detached 把子进程放进独立进程组，结束时用 -pid 杀整组。
const web = spawn("pnpm", ["exec", "vite"], {
  cwd: ROOT,
  stdio: "ignore",
  shell: true,
  detached: true,
});

/** 杀掉整个进程组（Vite 及其 shell 父进程）。 */
function killWebTree() {
  if (web.pid === undefined) return;
  try {
    process.kill(-web.pid, "SIGTERM");
  } catch {
    // 进程组可能已经不在了，忽略
  }
}

// 等端口真的可连，而不是盲等固定毫秒数。
// Vite 冷启动比静态服务器慢且不稳定，固定 900ms 会间歇性地在 CI 上抢跑。
async function waitForServer(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      // 还没起来，继续等
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`前端在 ${timeoutMs}ms 内没起来：${url}`);
}

await waitForServer(WEB);

const browser = await chromium.launch();
const page = await browser.newPage();

// 「控制台零错误」是 Day 5 的硬验收项，但要分清两类：
//
// 1. JS 层错误（未捕获异常、Promise rejection、模块加载失败）——必须为零。
//    这类代表代码有 bug。
// 2. 网络层日志（"Failed to load resource: 500" / ERR_CONNECTION_REFUSED）——预期存在。
//    浏览器对每个失败请求都会记一条，应用代码无法抑制。我们本来就在故意制造
//    500 和断网场景，这两条恰恰证明请求真的发出去并真的失败了。
const jsErrors = [];
const networkNotices = [];

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
}

const waitForStatus = (pattern) =>
  page.waitForFunction(
    (src) => new RegExp(src).test(document.querySelector("#status-bar").textContent),
    pattern.source,
    { timeout: 6000 },
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
async function checkStructure() {
  const found = await page.evaluate(() => ({
    header: !!document.querySelector("header.product-header"),
    nav: !!document.querySelector('nav[aria-label="主导航"]'),
    main: !!document.querySelector("main.workspace"),
    documentsPanel: !!document.querySelector(".documents-panel"),
    assistantPanel: !!document.querySelector(".assistant-panel"),
    questionForm: !!document.querySelector(".question-form"),
    currentNavLabel:
      document
        .querySelector('nav[aria-label="主导航"] a[aria-current="page"]')
        ?.textContent.trim() ?? null,
    statusRole: document.querySelector("#status-bar")?.getAttribute("role") ?? null,
    statusLive: document.querySelector("#status-bar")?.getAttribute("aria-live") ?? null,
    inlineStyles: document.querySelectorAll("[style]").length,
    initialRows: document.querySelectorAll("#document-list li").length,
  }));

  console.log("\n=== 结构关卡 ===\n");
  expect(found.header, "缺少 header.product-header");
  expect(found.nav, "缺少带 aria-label 的主导航");
  expect(found.main, "缺少 main.workspace");
  expect(found.documentsPanel, "缺少 .documents-panel");
  expect(found.assistantPanel, "缺少 .assistant-panel");
  expect(found.questionForm, "缺少 .question-form");
  expect(found.currentNavLabel === "知识文档",
    `当前页导航项应为「知识文档」，实际 ${found.currentNavLabel}`);
  // 状态区必须被读屏软件播报，不能只靠颜色传达——颜色对色盲用户不存在。
  expect(found.statusRole === "status", `#status-bar 的 role 应为 status，实际 ${found.statusRole}`);
  expect(found.statusLive === "polite", `#status-bar 的 aria-live 应为 polite，实际 ${found.statusLive}`);
  expect(found.inlineStyles === 0, `不应有内联样式，实际 ${found.inlineStyles} 处`);
  expect(found.initialRows === 0, `首帧列表应为 0 行，实际 ${found.initialRows} 行`);
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
  await page.goto(WEB, { waitUntil: "networkidle" });

  // 必须在第一次截图之前查结构。
  // Playwright 的 fullPage 截图会临时往页面注入样式，跑完留下内联样式残留——
  // 于是「不应有内联样式」会被测量工具自己弄脏。查未被任何工具动过的初始 DOM。
  await checkStructure();

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

  // ---- 第九帧：状态污染（Day 8 加）----
  //
  // React 引入的新失败模式，手写 DOM 时代不存在：一次远端状态变化触发重渲染，
  // 如果组件树接错（输入框的 state 被提到公共祖先、或 key 不稳定导致组件卸载重建），
  // 用户正在打的字和已选的文件会凭空消失。
  //
  // 这一帧证明本地 state（草稿、已选文件、场景选择）和服务端 state（文档列表）
  // 各自独立：后者整轮变化，前者一个字符都不能丢。
  const DRAFT = "这批文档里关于计费的部分怎么说的？";
  await page.fill("#question", DRAFT);
  await page.setInputFiles("#upload-input", {
    name: "污染测试.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("day8"),
  });

  const readLocalState = () =>
    page.evaluate(() => ({
      draft: document.querySelector("#question").value,
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
  await snapshot("8-no-cross-contamination");

  const afterLoad = await readLocalState();
  const afterRows = await page.$$eval("#document-list li", (els) => els.length);

  console.log("\n=== 第九帧：状态污染 ===\n");
  // 先证明前置条件成立，否则后面全是 null === null 的假通过。
  expect(beforeLoad.draft === DRAFT, "草稿在加载前就没写进去，这一帧无意义");
  expect(beforeLoad.files.length === 1,
    `选文件在加载前就没生效（实际 ${beforeLoad.files.length} 项），这一帧无意义`);

  expect(afterLoad.draft === DRAFT,
    `文档加载后草稿被清空/篡改：期望 "${DRAFT}"，实际 "${afterLoad.draft}"`);
  expect(afterLoad.files.join("|") === beforeLoad.files.join("|"),
    `文档加载后已选文件变了：加载前 [${beforeLoad.files}]，加载后 [${afterLoad.files}]`);
  expect(afterLoad.selectedCount === "1",
    `UploadZone 的 state 应仍是 1 个文件，实际 data-selected-count="${afterLoad.selectedCount}"`);
  // 反向也要成立：本地 state 存在不该阻止服务端 state 正常更新。
  expect(afterRows === 4, `服务端状态应正常更新到 4 行，实际 ${afterRows} 行`);

  // 清掉草稿和已选文件，别污染后面两帧的截图。
  await page.fill("#question", "");
  await page.setInputFiles("#upload-input", []);

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
  console.error("验证异常：", error.message);
  failed = true;
} finally {
  await browser.close();
  mock.kill();
  killWebTree();
  process.exitCode = failed ? 1 : 0;
}
