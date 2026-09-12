// Verify the built Web application against real Identity and deterministic
// project/knowledge fixtures. The Worker-backed ingestion slice belongs to Task 20.

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

function readOrigin(name) {
  const raw = process.env[name];
  if (raw === undefined) throw new Error(`${name} is required`);
  const url = new URL(raw);
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${name} must be an origin without credentials, path, query, or fragment`);
  }
  return url.origin;
}

const WEB_PORT = readPort("CAIRN_VERIFY_WEB_PORT", 5500);
const WEB = `http://localhost:${WEB_PORT}`;
const IDENTITY_ORIGIN = readOrigin("CAIRN_VERIFY_IDENTITY_ORIGIN");
const IDENTITY_READY = `${IDENTITY_ORIGIN}/ready`;
const OBJECT_STORE_ORIGIN = readOrigin("CAIRN_OBJECT_STORE_PUBLIC_ENDPOINT_URL");
const CORE_PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const CORE_PHRASE = "松针协议确认跨区域恢复完成";
const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

let web = null;
let browser = null;
let page = null;
let failed = false;
const jsErrors = [];
const requests = [];
const objectStorePuts = [];

function expect(condition, message) {
  if (condition) return;
  console.error(`✗ ${message}`);
  failed = true;
}

async function login() {
  await page.waitForSelector(".login-card");
  await page.fill("#login-email", "demo@cairn.dev");
  await page.fill("#login-password", "cairn-demo-2026");
  await page.click(".login-submit");
  await waitForAuthenticated();
}

async function logout() {
  await page.locator(".account-menu summary").click();
  await page.getByRole("button", { name: "退出" }).click();
  await page.waitForURL((url) => url.pathname === "/login");
}

async function waitForAuthenticated() {
  await page.waitForURL((url) => url.pathname === "/projects");
  await page.waitForSelector(".projects-page");
}

async function checkLoginBoundary() {
  expect(await page.isVisible(".login-card"), "匿名访问应显示登录页");
  await page.click(".login-submit");
  const errors = await page.$$eval('[role="alert"]', (elements) =>
    elements.map((element) => element.textContent.trim()),
  );
  expect(
    errors.join("|") === "请填写邮箱|请填写密码",
    `登录空提交应显示两个可恢复的字段错误，实际 ${errors.join(" / ")}`,
  );
  expect(
    (await page.evaluate(() => document.activeElement?.id)) === "login-email",
    "登录校验失败后焦点应回到邮箱字段",
  );
}

async function checkAuthenticatedShell() {
  expect(new URL(page.url()).pathname === "/projects", "成功登录应进入 /projects");
  expect(
    (await page.getByRole("link", { name: "Cairn" }).getAttribute("href")) === "/projects",
    "Cairn wordmark 应返回项目工作台",
  );
  expect(
    await page.getByRole("link", { name: "项目任务" }).isVisible(),
    "主导航应暴露真实项目工作台",
  );
  expect(
    (await page.getByRole("navigation", { name: "主导航" }).getByRole("link").count()) === 1,
    "主导航不应保留通用文档或生成式问答入口",
  );
  await page.locator(".account-menu summary").click();
  expect(await page.getByText("Cairn Demo").isVisible(), "账户菜单应显示当前组织");
  await page.locator(".account-menu summary").click();
}

async function checkCompatibilityRoutes() {
  for (const path of ["/documents", "/ask", "/unknown"]) {
    await page.goto(`${WEB}${path}`, { waitUntil: "networkidle" });
    await waitForAuthenticated();
    expect(new URL(page.url()).pathname === "/projects", `${path} 应 replace 到 /projects`);
  }
}

async function checkCoreKnowledgeIngestion() {
  const fileName = "task20-核心摄取验收.txt";
  const content = Buffer.from(
    `核心摄取验收\n${CORE_PHRASE}\nThis bilingual source proves upload, indexing, retrieval, citation, and download.\n`,
    "utf8",
  );
  await page.goto(`${WEB}/projects/${CORE_PROJECT_ID}/knowledge`, { waitUntil: "networkidle" });
  await page.waitForSelector(".knowledge-page");
  await page.getByLabel("上传知识资料", { exact: true }).setInputFiles({
    name: fileName,
    mimeType: "text/plain",
    buffer: content,
  });
  await page.getByRole("button", { name: "开始上传" }).click();
  await page.locator('.knowledge-upload-file[data-phase="ready"]').waitFor({
    timeout: 120_000,
  });
  const signedPut = objectStorePuts.find((request) => request.method() === "PUT");
  expect(signedPut !== undefined, "浏览器应向配置的 MinIO origin 发出真实 PUT");
  if (signedPut !== undefined) {
    const signedUrl = new URL(signedPut.url());
    const headers = await signedPut.allHeaders();
    expect(signedUrl.origin === OBJECT_STORE_ORIGIN, "上传 PUT 应只发往配置的 MinIO origin");
    expect(signedUrl.searchParams.has("X-Amz-Signature"), "上传 PUT 应使用签名查询参数");
    expect(headers.cookie === undefined, "对象存储 PUT 不应携带 Identity Cookie");
    expect(headers.authorization === undefined, "对象存储 PUT 不应携带 Identity Authorization");
  }
  expect(
    await page.getByText("Worker 处理完成，可用于知识检索", { exact: true }).isVisible(),
    "真实上传应由 Worker 处理为 ready",
  );

  const answers = page.getByRole("region", { name: "项目知识问答" });
  await answers.getByLabel("向项目知识提问", { exact: true }).fill(`资料里提到了什么：${CORE_PHRASE}`);
  await answers.getByRole("button", { name: "生成回答" }).click();
  const generated = answers.getByRole("region", { name: "生成式回答" });
  await generated.waitFor({ timeout: 30_000 });
  expect(
    await generated.locator(".knowledge-answer-paragraphs").getByText(CORE_PHRASE, { exact: false }).isVisible(),
    "生成回答应包含上传资料中的依据",
  );
  expect(await generated.getByText(/S1 · task20-核心摄取验收\.txt/).isVisible(), "生成回答应显示核验后的来源");
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: join(SHOT_DIR, "knowledge-answer-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 360, height: 800 });
  await page.screenshot({ path: join(SHOT_DIR, "knowledge-answer-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });

  await page.getByLabel("搜索项目知识", { exact: true }).fill(CORE_PHRASE);
  await page.getByRole("button", { name: "搜索项目知识" }).click();
  await page.getByText("混合检索", { exact: true }).waitFor({ timeout: 30_000 });
  expect(
    await page.locator(".knowledge-search-result").filter({ hasText: CORE_PHRASE }).count() > 0,
    "真实搜索应返回上传文件中的精确短语",
  );
  const search = page.getByRole("region", { name: "项目知识检索" });
  await search.getByRole("button", { name: "查看引用上下文" }).first().click();
  const context = search.locator(".knowledge-citation-context-success");
  await context.waitFor({ timeout: 30_000 });
  expect(await context.getByText(CORE_PHRASE, { exact: false }).isVisible(), "引用上下文应包含命中文本");
  expect(/第\s*\d+(?:[–-]\d+)?\s*行/.test(await context.innerText()), "文本引用应显示行号 locator");

  const downloadHref = await context
    .getByRole("link", { name: "下载原文件（新标签页）" })
    .getAttribute("href");
  expect(downloadHref !== null, "引用上下文应提供授权下载入口");
  const downloadResponse = await page.request.get(new URL(downloadHref, WEB).href);
  expect(downloadResponse.ok(), `授权下载应成功，实际 ${downloadResponse.status()}`);
  expect((await downloadResponse.body()).equals(content), "授权下载应返回刚上传的原始字节");
}

try {
  await assertPortAvailable(WEB_PORT);
  const previewInvocation = spawnInvocation(pnpm, [
    "exec",
    "vite",
    "preview",
    "--port",
    String(WEB_PORT),
    "--strictPort",
  ]);
  web = spawn(previewInvocation.command, previewInvocation.args, {
    cwd: WEB_ROOT,
    stdio: "ignore",
    shell: false,
    detached: process.platform !== "win32",
  });
  await waitForChildSpawn(web);
  await Promise.all([waitForServer(WEB), waitForServer(IDENTITY_READY)]);

  browser = await chromium.launch();
  page = await browser.newPage();
  page.on("request", (request) => {
    requests.push(request.url());
    if (new URL(request.url()).origin === OBJECT_STORE_ORIGIN) objectStorePuts.push(request);
  });
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("Failed to load resource")) {
      jsErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => jsErrors.push(`pageerror: ${error.message}`));

  await page.goto(`${WEB}/unknown`, { waitUntil: "networkidle" });
  await page.waitForURL((url) => url.pathname === "/login");
  await checkLoginBoundary();
  await login();
  await checkAuthenticatedShell();
  await checkCoreKnowledgeIngestion();

  await page.goto(`${WEB}/projects`, { waitUntil: "networkidle" });
  await waitForAuthenticated();
  await checkCompatibilityRoutes();

  await checkResponsiveFoundation({
    page,
    expect,
    screenshotDir: SHOT_DIR,
    login,
    logout,
    waitForAuthenticated,
  });

  const obsoleteRequests = requests.filter((url) =>
    /\/api\/v1\/(?:documents|uploads|ask)(?:\/|\?|$)/.test(url),
  );
  expect(
    obsoleteRequests.length === 0,
    `浏览器不应请求已退役端点，实际 ${obsoleteRequests.join(" / ")}`,
  );
  expect(jsErrors.length === 0, `浏览器出现 JS 错误：${jsErrors.join(" / ")}`);

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: join(SHOT_DIR, "task19-projects-final.png"), fullPage: true });
  console.log(failed ? "\n✗ Task 19 Web 验证未通过" : "\n✓ Task 19 Web 验证通过");
} catch (error) {
  console.error("验证异常：", error instanceof Error ? error.message : String(error));
  failed = true;
} finally {
  const cleanupFailures = await settleCleanupTasks([
    { name: "Chromium", run: () => browser?.close() },
    { name: "Vite preview", run: () => stopProcessTree(web) },
  ]);
  for (const failure of cleanupFailures) {
    console.error(`${failure.name} 清理失败：`, failure.reason);
  }
  if (cleanupFailures.length > 0) failed = true;
  process.exitCode = failed ? 1 : 0;
}
