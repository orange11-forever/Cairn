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
const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

let web = null;
let browser = null;
let page = null;
let failed = false;
const jsErrors = [];
const requests = [];

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
  page.on("request", (request) => requests.push(request.url()));
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

  await page.reload({ waitUntil: "networkidle" });
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
