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
import { checkFeishuHistoryReachability } from "./verify-feishu-history-layout.mjs";
import { checkLongMarkdownCitationBlocks } from "./verify-document-citation.mjs";
import { checkFormattedReaderResponsive } from "./verify-document-responsive.mjs";
import { installSourceFormDiagnostics, waitForSourceResponse } from "./verify-source-diagnostics.mjs";

const WEB_ROOT = fileURLToPath(new URL("..", import.meta.url));
const ROOT = join(WEB_ROOT, "../..");
const SHOT_DIR = join(ROOT, "apps/web/screenshots");
const FEISHU_SHOT_DIR = join(ROOT, "output/playwright/feishu");
const PREVIEW_SHOT_DIR = join(ROOT, "output/playwright/document-preview");
mkdirSync(SHOT_DIR, { recursive: true });
mkdirSync(FEISHU_SHOT_DIR, { recursive: true });
mkdirSync(PREVIEW_SHOT_DIR, { recursive: true });

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
const FEISHU_DOCUMENT_ID = "VerifyDoc2026";
const FEISHU_PHRASE = "青松协定确认飞书跨区域恢复完成";
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
    `核心摄取验收\n${CORE_PHRASE}\nThis bilingual source proves upload, indexing, retrieval, citation, and download.\nTXT_EOF_COMPLETE_20261004\n`,
    "utf8",
  );
  await page.goto(`${WEB}/projects/${CORE_PROJECT_ID}/knowledge`, { waitUntil: "networkidle" });
  await page.waitForSelector(".knowledge-page");
  await page.getByRole("button", { name: "上传资料" }).click();
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
    await page.getByText("处理完成，可用于知识检索", { exact: true }).isVisible(),
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
  const context = page.locator(".knowledge-document");
  await context.waitFor({ timeout: 30_000 });
  await context.getByText("TXT_EOF_COMPLETE_20261004", { exact: false }).waitFor();
  expect(await context.getByText(CORE_PHRASE, { exact: false }).isVisible(), "全文应包含引用命中文本");
  expect(await context.locator('[data-citation-hit="true"]').count() > 0, "引用应突出正文中的可信位置");
  await context.getByRole("button", { name: "回到引用" }).click();
  expect(await context.locator('[data-citation-hit="true"]').evaluateAll(nodes => nodes.some(node => node === document.activeElement)), "返回引用应聚焦实际正文位置");
  expect(/第\s*\d+(?:[–-]\d+)?\s*行/.test(await context.innerText()), "文本引用应显示行号 locator");

  const downloadHref = await context
    .getByRole("link", { name: "下载原文件", exact: true })
    .getAttribute("href");
  expect(downloadHref !== null, "引用上下文应提供授权下载入口");
  const downloadResponse = await page.request.get(new URL(downloadHref, WEB).href);
  expect(downloadResponse.ok(), `授权下载应成功，实际 ${downloadResponse.status()}`);
  expect((await downloadResponse.body()).equals(content), "授权下载应返回刚上传的原始字节");
}

async function checkMarkdownFullPreview() {
  const fileName = "preview-完整文档阅读与跨区域资料核对及引用定位验收运行手册.md";
  const phrase = "松石全文引用确认部署顺序";
  const content = Buffer.from(`# 全文阅读验收\n\n${phrase}\n\n- 配置\n- 启动\n\n\`\`\`sh\necho preview-ready --profile synthetic-preview --region synthetic-zone --notes source-line-preserving-markdown-reader\n\`\`\`\n\n| 步骤 | 状态 |\n| --- | --- |\n| 读取全文并核对来源与引用位置 | 完整且经过授权 |\n\nMARKDOWN_EOF_COMPLETE_20261004\n`, "utf8");
  await page.goto(`${WEB}/projects/${CORE_PROJECT_ID}/knowledge`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "上传资料" }).click();
  await page.getByLabel("上传知识资料", { exact: true }).setInputFiles({ name: fileName, mimeType: "text/markdown", buffer: content });
  await page.getByRole("button", { name: "开始上传" }).click();
  await page.locator('.knowledge-upload-file[data-phase="ready"]').waitFor({ timeout: 120_000 });
  await page.getByRole("button", { name: `查看${fileName}资料详情` }).click();
  const document = page.locator(".knowledge-document");
  await document.getByText("MARKDOWN_EOF_COMPLETE_20261004").waitFor();
  expect(await document.getByRole("heading", { name: "全文阅读验收" }).isVisible(), "Markdown 标题应按语义渲染");
  expect(await document.getByRole("table").isVisible(), "Markdown 表格应真实渲染");
  expect(await document.getByRole("button", { name: "复制代码" }).isVisible(), "代码复制应保留");
  expect(await document.getByText("已到文档末尾 · 正文完整").isVisible(), "全文应有完整 EOF 状态");
  await document.getByRole("button", { name: "资料详情", exact: true }).click();
  await document.getByRole("region", { name: `${fileName} 资料详情` }).waitFor();
  expect(await document.getByRole("button", { name: "删除资料", exact: true }).isVisible(), "正文工具栏应可打开真实资料管理");
  await document.getByRole("button", { name: "资料详情", exact: true }).click();
  await page.getByRole("tab", { name: "搜索", exact: true }).click();
  await page.getByLabel("搜索项目知识", { exact: true }).fill(phrase);
  await page.getByRole("button", { name: "搜索项目知识", exact: true }).click();
  const search = page.getByRole("region", { name: "项目知识检索" });
  await search.locator(".knowledge-search-result").filter({ hasText: phrase }).first().waitFor();
  await search.getByRole("button", { name: "查看引用上下文" }).first().click();
  await document.getByRole("button", { name: "回到引用" }).waitFor();
  expect(await document.locator('[data-citation-hit="true"]').count() > 0, "搜索引用应定位 Markdown 正文");
  await document.getByText("MARKDOWN_EOF_COMPLETE_20261004").scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(PREVIEW_SHOT_DIR, "markdown-full-body-citation.png"), fullPage: true });
  const answers = page.getByRole("region", { name: "项目知识问答" });
  await answers.getByLabel("向项目知识提问", { exact: true }).fill(`按资料说明：${phrase}`);
  await answers.getByRole("button", { name: "生成回答" }).click();
  const generated = answers.getByRole("region", { name: "生成式回答" });
  await generated.waitFor({ timeout: 30_000 });
  await generated.getByRole("button", { name: /查看.*引用上下文/ }).first().click();
  await document.getByRole("button", { name: "回到引用" }).waitFor();
  expect(await document.locator('[data-citation-hit="true"]').count() > 0, "回答引用应定位完整正文");
  await checkFormattedReaderResponsive({ page, expect, screenshotDir: PREVIEW_SHOT_DIR });
}

async function checkFeishuSources() {
  const syncDetailRequests = [];
  page.on("request", (request) => {
    if (request.method() === "GET" && /\/knowledge\/sources\/[^/]+\/syncs\/[^/]+$/.test(request.url())) {
      syncDetailRequests.push(request.url());
    }
  });
  await page.goto(`${WEB}/projects/${CORE_PROJECT_ID}/knowledge`, { waitUntil: "networkidle" });
  await page.getByRole("link", { name: "来源与同步", exact: true }).click();
  await installSourceFormDiagnostics(page, [FEISHU_DOCUMENT_ID, `https://team.feishu.cn/docx/${FEISHU_DOCUMENT_ID}`,
    "verify_feishu", "飞书浏览器验收"]);
  let created;
  if (process.env.CAIRN_VERIFY_FEISHU_REUSE_SOURCE === "1") {
    const existingResponse = await page.request.get(`${IDENTITY_ORIGIN}/api/v1/projects/${CORE_PROJECT_ID}/knowledge/sources`);
    const existingPage = await existingResponse.json();
    created = existingPage.items.find((item) => item.documentId === FEISHU_DOCUMENT_ID &&
      item.credentialRef === "verify_feishu");
    if (!created) throw new Error("reusable synthetic Feishu source is missing");
    await page.getByRole("button", { name: /飞书浏览器验收/ }).click();
    if (created.status === "disabled") {
      await page.getByRole("checkbox", { name: /我确认将此文档共享/ }).check();
      await page.getByRole("button", { name: "恢复来源" }).click();
      await page.getByText(/来源已恢复。请手动同步/).waitFor();
    }
  } else {
    await page.getByRole("button", { name: "添加来源", exact: true }).click();
    const form = page.getByRole("region", { name: "添加飞书来源" });
    await form.getByLabel("来源名称").fill("飞书浏览器验收");
    await form.getByLabel("飞书文档链接或 ID").fill(`https://team.feishu.cn/docx/${FEISHU_DOCUMENT_ID}`);
    await form.getByLabel("凭证别名").fill("verify_feishu");
    expect(await form.getByRole("button", { name: "添加来源" }).isDisabled(), "未确认共享时不得创建来源");
    await form.getByRole("checkbox", { name: /我确认将此文档共享/ }).check();
    const createdResponse = await waitForSourceResponse({ page, label: "feishu-create", screenshotDir: PREVIEW_SHOT_DIR,
      predicate: response => response.request().method() === "POST" && response.url().endsWith("/knowledge/sources/feishu"),
      action: () => form.getByRole("button", { name: "添加来源" }).click() });
    expect(createdResponse.status() === 201, `来源登记应返回201，实际 ${createdResponse.status()}`);
    created = await createdResponse.json();
    await page.getByText("来源已登记。现在可以手动同步文档。").waitFor();
  }
  expect(created.documentId === FEISHU_DOCUMENT_ID && created.credentialRef === "verify_feishu",
    "来源响应应匹配合成文档与凭证别名");
  const queuedResponse = await waitForSourceResponse({ page, label: "feishu-initial-sync", screenshotDir: PREVIEW_SHOT_DIR,
    predicate: response => response.request().method() === "POST" && response.url().endsWith(`/knowledge/sources/${created.id}/syncs`),
    action: () => page.getByRole("button", { name: "立即同步" }).click() });
  expect(queuedResponse.status() === 202, `同步排队应返回202，实际 ${queuedResponse.status()}`);
  const queued = await queuedResponse.json();
  expect(queued.sourceId === created.id && queued.projectId === CORE_PROJECT_ID,
    "同步请求应绑定当前项目与来源");
  let sync;
  const syncUrl = `${IDENTITY_ORIGIN}/api/v1/projects/${CORE_PROJECT_ID}`
    + `/knowledge/sources/${created.id}/syncs/${queued.id}`;
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const syncResponse = await page.request.get(syncUrl);
    expect(syncResponse.status() === 200, "同步详情应可重新授权读取");
    sync = await syncResponse.json();
    if (sync.status === "completed" && sync.resourceStatus === "ready") break;
    if (sync.status === "failed" || sync.resourceStatus === "failed") break;
    await page.waitForTimeout(2_000);
  }
  expect(sync.status === "completed" && sync.resourceStatus === "ready" && sync.resourceId,
    `快照和索引都须完成后才可检索，实际 ${sync?.status}/${sync?.resourceStatus}/${sync?.failureCode}`);
  await page.locator(".feishu-sync-history strong").getByText("可检索", { exact: true })
    .first().waitFor({ timeout: 20_000 });

  for (const theme of ["light", "dark"]) {
    await page.locator(".account-menu summary").click();
    await page.locator(`input[name="theme-preference"][value="${theme}"]`).check();
    await page.locator(".account-menu summary").click();
    for (const width of [360, 768, 1280]) {
      await page.setViewportSize({ width, height: 850 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
        `飞书管理页 ${width}px ${theme} 不应横向溢出`);
      await page.screenshot({ path: join(FEISHU_SHOT_DIR, `sources-${theme}-${width}.png`), fullPage: true });
      if (width === 360) {
        await page.locator(".feishu-sync-history li").last().scrollIntoViewIfNeeded();
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        expect(await page.evaluate(() => {
          const row = document.querySelector(".feishu-sync-history li:last-child")?.getBoundingClientRect();
          const nav = document.querySelector(".primary-nav")?.getBoundingClientRect();
          return row !== undefined && nav !== undefined && row.bottom <= nav.top;
        }), "手机端最后一条同步记录应能滚动到固定导航上方");
        await page.evaluate(() => window.scrollTo(0, 0));
      }
    }
  }
  // The synthetic 50-row fixture exercises the real page/CSS and pager geometry
  // without creating 50 upstream sync jobs or replacing the functional API flow.
  await checkFeishuHistoryReachability(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("link", { name: "返回项目知识" }).click();
  await page.getByLabel("搜索项目知识", { exact: true }).fill(FEISHU_PHRASE);
  await page.getByRole("button", { name: "搜索项目知识" }).click();
  await page.locator(".knowledge-search-result").filter({ hasText: FEISHU_PHRASE })
    .first().waitFor({ timeout: 30_000 });
  await page.getByRole("region", { name: "项目知识检索" }).getByRole("button", { name: "查看引用上下文" }).first().click();
  const snapshot = page.locator(".knowledge-document");
  await snapshot.getByRole("button", { name: "回到引用" }).waitFor();
  await snapshot.locator(".knowledge-document-body").getByText(FEISHU_PHRASE, { exact: false }).first().waitFor();
  expect(await snapshot.locator(".knowledge-document-body").innerText().then(text => text.includes(FEISHU_PHRASE)), "合成飞书快照应从真实全文接口读取");

  await page.getByRole("link", { name: "来源与同步", exact: true }).click();
  await page.getByRole("button", { name: /飞书浏览器验收/ }).click();
  await page.getByRole("button", { name: "编辑设置" }).click();
  const targetInterval = created.syncIntervalSeconds === 900 ? "300" : "900";
  await page.getByLabel("同步周期").selectOption(targetInterval);
  await page.getByRole("button", { name: "保存修改" }).click();
  await page.getByText("来源设置已保存。").waitFor();
  expect(await page.locator(".feishu-facts").getByText(targetInterval === "900" ? "每 15 分钟" : "每 5 分钟").isVisible(),
    "周期修改应反映在来源详情");
  await page.getByRole("button", { name: "停用来源" }).click();
  await page.getByRole("button", { name: "确认停用 飞书浏览器验收" }).click();
  await page.getByText(/来源已停用，项目成员无法再读取/).waitFor();
  const deniedResource = await page.request.get(`${IDENTITY_ORIGIN}/api/v1/projects/${CORE_PROJECT_ID}`
    + `/knowledge/resources/${sync.resourceId}`);
  expect(deniedResource.status() === 404,
    `停用后资源详情应404，实际 ${deniedResource.status()}`);
  await page.getByRole("link", { name: "返回项目知识" }).click();
  await page.getByLabel("搜索项目知识", { exact: true }).fill(FEISHU_PHRASE);
  const stoppedSearch = await waitForSourceResponse({ page, label: "feishu-denied-search", screenshotDir: PREVIEW_SHOT_DIR,
    predicate: response => response.request().method() === "POST" && response.url().endsWith("/knowledge/search"),
    action: () => page.getByRole("button", { name: "搜索项目知识" }).click() });
  expect(stoppedSearch.status() === 200, "停用后搜索仍应返回成功响应");
  const stoppedResults = await stoppedSearch.json();
  expect(stoppedResults.results.every((result) => result.resourceId !== sync.resourceId),
    "停用来源不能出现在新的搜索结果中");
  expect(await page.locator(".knowledge-search-result").filter({ hasText: FEISHU_PHRASE }).count() === 0,
    "旧飞书片段不能留在搜索界面");

  await page.getByRole("link", { name: "来源与同步", exact: true }).click();
  await page.getByRole("button", { name: /飞书浏览器验收/ }).click();
  const restore = page.getByRole("button", { name: "恢复来源" });
  expect(await restore.isDisabled(), "恢复来源必须重新确认共享");
  await page.getByRole("checkbox", { name: /我确认将此文档共享/ }).check();
  await restore.click();
  await page.getByText(/来源已恢复。请手动同步/).waitFor();
  const recoveryQueueResponse = await waitForSourceResponse({ page, label: "feishu-restored-sync", screenshotDir: PREVIEW_SHOT_DIR,
    predicate: response => response.request().method() === "POST" && response.url().endsWith(`/knowledge/sources/${created.id}/syncs`),
    action: () => page.getByRole("button", { name: "立即同步" }).click() });
  expect(recoveryQueueResponse.status() === 202, "恢复后手动同步应返回202");
  const recoveryQueue = await recoveryQueueResponse.json();
  await page.waitForTimeout(2_500);
  expect(syncDetailRequests.some((url) => url.endsWith(`/syncs/${recoveryQueue.id}`)),
    "同步记录应跟踪最新一笔恢复任务，而非旧的已完成记录");
  const recoveryDeadline = Date.now() + 120_000;
  let recovered;
  while (Date.now() < recoveryDeadline) {
    const response = await page.request.get(`${IDENTITY_ORIGIN}/api/v1/projects/${CORE_PROJECT_ID}`
      + `/knowledge/sources/${created.id}/syncs/${recoveryQueue.id}`);
    expect(response.status() === 200, "恢复同步详情应可读取");
    recovered = await response.json();
    if (recovered.status === "completed" && recovered.resourceStatus === "ready") break;
    if (recovered.status === "failed" || recovered.resourceStatus === "failed") break;
    await page.waitForTimeout(2_000);
  }
  expect(recovered?.status === "completed" && recovered?.resourceStatus === "ready",
    `恢复后应重新验证并可检索，实际 ${recovered?.status}/${recovered?.resourceStatus}/${recovered?.failureCode}`);
  await page.getByRole("link", { name: "返回项目知识" }).click();
  await page.getByLabel("搜索项目知识", { exact: true }).fill(FEISHU_PHRASE);
  await page.getByRole("button", { name: "搜索项目知识" }).click();
  await page.locator(".knowledge-search-result").filter({ hasText: FEISHU_PHRASE })
    .first().waitFor({ timeout: 30_000 });
}

try {
  if (process.env.CAIRN_VERIFY_REUSE_WEB !== "1") {
    await assertPortAvailable(WEB_PORT);
    const previewInvocation = spawnInvocation(pnpm, [
      "exec", "vite", "preview", "--port", String(WEB_PORT), "--strictPort",
    ]);
    web = spawn(previewInvocation.command, previewInvocation.args, {
      cwd: WEB_ROOT, stdio: "ignore", shell: false,
      detached: process.platform !== "win32",
    });
    await waitForChildSpawn(web);
  }
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
  await checkMarkdownFullPreview();
  await checkLongMarkdownCitationBlocks({ page, webOrigin: WEB, projectId: CORE_PROJECT_ID,
    expect, screenshotDir: PREVIEW_SHOT_DIR });
  await checkFeishuSources();

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
