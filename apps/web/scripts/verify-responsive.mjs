import { join } from "node:path";

const VIEWPORTS = [
  { name: "mobile", width: 360, height: 800 },
  { name: "tablet", width: 768, height: 900 },
  { name: "desktop", width: 1280, height: 900 },
];

const KNOWLEDGE_PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const RESPONSIVE_PROJECT_B_ID = "00000000-0000-4000-8000-000000004002";

const RESPONSIVE_PROJECTS = [
  {
    id: KNOWLEDGE_PROJECT_ID,
    name: "跨区域知识交付",
    description: "验证项目轨道、任务工作区和长中文内容在各断点稳定呈现。",
    createdAt: "2026-08-01T08:00:00Z",
    updatedAt: "2026-08-22T08:00:00Z",
  },
  {
    id: RESPONSIVE_PROJECT_B_ID,
    name: "搜索体验升级",
    description: "验证选择状态与受控任务区域的可访问关联。",
    createdAt: "2026-08-03T08:00:00Z",
    updatedAt: "2026-08-22T09:00:00Z",
  },
];

const RESPONSIVE_TASKS = {
  [KNOWLEDGE_PROJECT_ID]: [{
    id: "00000000-0000-4000-8000-000000005011",
    projectId: KNOWLEDGE_PROJECT_ID,
    parentTaskId: null,
    stageId: null,
    title: "核对跨区域知识交付清单",
    status: "todo",
    priority: "high",
    dueAt: "2026-09-12T08:00:00Z",
    acceptanceCriteria: "每个交付区域都有负责人、恢复步骤和可核对的验收记录。",
    createdAt: "2026-08-04T08:00:00Z",
    updatedAt: "2026-08-22T09:00:00Z",
  }],
  [RESPONSIVE_PROJECT_B_ID]: [{
    id: "00000000-0000-4000-8000-000000005012",
    projectId: RESPONSIVE_PROJECT_B_ID,
    parentTaskId: null,
    stageId: null,
    title: "复核搜索选择反馈",
    status: "in_progress",
    priority: "medium",
    dueAt: null,
    acceptanceCriteria: "桌面轨道与移动选择器都指向当前任务区域。",
    createdAt: "2026-08-05T08:00:00Z",
    updatedAt: "2026-08-22T10:00:00Z",
  }],
};

const KNOWLEDGE_RESOURCE_PAGE = {
  capabilities: { canWrite: false },
  items: [
    {
      id: "00000000-0000-4000-8000-000000005001",
      title: "跨区域交付与故障恢复架构决策记录（最终评审版）.pdf",
      sourceType: "upload",
      createdAt: "2026-08-21T02:00:00Z",
      updatedAt: "2026-08-22T02:00:00Z",
      latestVersion: {
        id: "00000000-0000-4000-8000-000000006001",
        sourceType: "upload",
        mediaType: "application/pdf",
        sizeBytes: 1536,
        sha256: "a".repeat(64),
        status: "queued",
        errorCode: null,
        retryable: false,
        createdAt: "2026-08-21T02:00:00Z",
        processingStartedAt: null,
        readyAt: null,
      },
    },
    {
      id: "00000000-0000-4000-8000-000000005002",
      title: "上线检查清单.docx",
      sourceType: "upload",
      createdAt: "2026-08-21T02:00:00Z",
      updatedAt: "2026-08-22T02:00:00Z",
      latestVersion: {
        id: "00000000-0000-4000-8000-000000006002",
        sourceType: "upload",
        mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        sizeBytes: 2 * 1024 * 1024,
        sha256: "b".repeat(64),
        status: "processing",
        errorCode: null,
        retryable: false,
        createdAt: "2026-08-21T02:00:00Z",
        processingStartedAt: "2026-08-21T02:01:00Z",
        readyAt: null,
      },
    },
    {
      id: "00000000-0000-4000-8000-000000005003",
      title: "值班说明.txt",
      sourceType: "upload",
      createdAt: "2026-08-21T02:00:00Z",
      updatedAt: "2026-08-22T02:00:00Z",
      latestVersion: {
        id: "00000000-0000-4000-8000-000000006003",
        sourceType: "upload",
        mediaType: "text/plain",
        sizeBytes: 512,
        sha256: "c".repeat(64),
        status: "ready",
        errorCode: null,
        retryable: false,
        createdAt: "2026-08-21T02:00:00Z",
        processingStartedAt: "2026-08-21T02:01:00Z",
        readyAt: "2026-08-21T02:03:00Z",
      },
    },
    {
      id: "00000000-0000-4000-8000-000000005004",
      title: "损坏报告.pdf",
      sourceType: "upload",
      createdAt: "2026-08-21T02:00:00Z",
      updatedAt: "2026-08-22T02:00:00Z",
      latestVersion: {
        id: "00000000-0000-4000-8000-000000006004",
        sourceType: "upload",
        mediaType: "application/pdf",
        sizeBytes: 10 * 1024 * 1024,
        sha256: "d".repeat(64),
        status: "failed",
        errorCode: "parser_failed",
        retryable: true,
        createdAt: "2026-08-21T02:00:00Z",
        processingStartedAt: "2026-08-21T02:01:00Z",
        readyAt: null,
      },
    },
  ],
  nextCursor: "responsive-next-page",
};

const KNOWLEDGE_SEARCH_RESPONSE = {
  retrievalMode: "keyword_fallback",
  results: [{
    resourceId: "00000000-0000-4000-8000-000000005003",
    resourceVersionId: "00000000-0000-4000-8000-000000006003",
    chunkId: "00000000-0000-4000-8000-000000007003",
    title: "跨区域交付与故障恢复架构决策记录（需要在窄屏完整换行）",
    mediaType: "text/markdown",
    excerpt: "这是一段用于验证三种视口、亮暗主题和长中文内容不会造成横向溢出的真实搜索结果摘录。",
    locator: {
      type: "markdown",
      headingPath: ["平台运行", "故障升级与跨区域恢复"],
      lineStart: 128,
      lineEnd: 176,
    },
    score: 0.75,
  }],
};

const KNOWLEDGE_RESOURCE_ID = KNOWLEDGE_SEARCH_RESPONSE.results[0].resourceId;
const KNOWLEDGE_RESOURCE_VERSION_ID =
  KNOWLEDGE_SEARCH_RESPONSE.results[0].resourceVersionId;
const KNOWLEDGE_CHUNK_ID = KNOWLEDGE_SEARCH_RESPONSE.results[0].chunkId;
const KNOWLEDGE_NO_WHITESPACE_TOKEN = "NoWhitespaceOverflowBoundary".repeat(18);
const KNOWLEDGE_CHUNK_CONTEXT = {
  resourceId: KNOWLEDGE_RESOURCE_ID,
  resourceVersionId: KNOWLEDGE_RESOURCE_VERSION_ID,
  before: {
    id: "00000000-0000-4000-8000-000000007002",
    ordinal: 10,
    text: "前文保留第一行\n前文保留第二行",
    locator: {
      type: "markdown",
      headingPath: ["平台运行", "故障升级前置检查"],
      lineStart: 116,
      lineEnd: 127,
    },
  },
  hit: {
    id: KNOWLEDGE_CHUNK_ID,
    ordinal: 11,
    text: `命中片段保留换行\n${KNOWLEDGE_NO_WHITESPACE_TOKEN}`,
    locator: {
      type: "markdown",
      headingPath: ["平台运行", "故障升级与跨区域恢复"],
      lineStart: 128,
      lineEnd: 176,
    },
  },
  after: {
    id: "00000000-0000-4000-8000-000000007004",
    ordinal: 12,
    text: "后文记录恢复后的验证与复盘。",
    locator: {
      type: "markdown",
      headingPath: ["平台运行", "恢复后验证"],
      lineStart: 177,
      lineEnd: 188,
    },
  },
};

const KNOWLEDGE_SEARCH_ERROR_QUERY = "跨区域搜索错误";
const KNOWLEDGE_SEARCH_ERROR_MESSAGE =
  "KnowledgeSearchInfrastructureUnavailableKnowledgeSearchInfrastructureUnavailableKnowledgeSearchInfrastructureUnavailableKnowledgeSearchInfrastructureUnavailable";
const KNOWLEDGE_SEARCH_TRACE_ID =
  "trace-knowledge-search-503-ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff";
const TASK_TRANSITION_TRACE_ID = "trace-responsive-task-transition-503";
const TASK_TRANSITION_ERROR_MESSAGE = "任务状态更新失败，请稍后重试";

async function chooseTheme(page, label) {
  const menu = page.locator(".account-menu");
  if (!(await menu.evaluate((element) => element.open))) await menu.locator("summary").click();
  await menu.getByRole("radio", { name: label }).check();
  await menu.locator("summary").click();
}

function assertUniformFullBoundary(boundary, expect, context) {
  expect(
    boundary.widths.length === 4 &&
      boundary.widths.every((width) => width > 0 && width <= 1) &&
      new Set(boundary.widths).size === 1,
    `${context} 边界宽度必须四边一致、大于 0 且不超过 1px，实际 ${boundary.widths.join("/")}px`,
  );
  expect(
    boundary.styles.length === 4 &&
      boundary.styles.every((style) => style !== "none" && style !== "hidden") &&
      new Set(boundary.styles).size === 1,
    `${context} 边界样式必须四边一致且不能为 none/hidden，实际 ${boundary.styles.join("/")}`,
  );
  expect(
    boundary.colors.length === 4 && new Set(boundary.colors).size === 1,
    `${context} 边界颜色必须四边一致，实际 ${boundary.colors.join("/")}`,
  );
}

async function readLayout(page) {
  return page.evaluate(() => {
    const nav = document.querySelector(".primary-nav");
    const workspace = document.querySelector("main.workspace");
    const panel = document.querySelector(
      ".documents-panel, .assistant-panel, .knowledge-page, .projects-page",
    );
    const brandImage = document.querySelector(".product-brand img");
    const navRect = nav?.getBoundingClientRect();
    const brandImageRect = brandImage?.getBoundingClientRect();
    const workspaceStyle = workspace === null ? null : getComputedStyle(workspace);
    const brandImageStyle = brandImage === null ? null : getComputedStyle(brandImage);

    return {
      theme: document.documentElement.dataset.theme ?? null,
      path: location.pathname,
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      navPosition: nav === null ? null : getComputedStyle(nav).position,
      navBottom: navRect?.bottom ?? null,
      viewportHeight: window.innerHeight,
      workspacePaddingBottom:
        workspaceStyle === null ? 0 : Number.parseFloat(workspaceStyle.paddingBottom),
      workspaceOverflowX: workspaceStyle?.overflowX ?? null,
      navHeight: navRect?.height ?? 0,
      panelInsideViewport:
        panel === null
          ? false
          : panel.getBoundingClientRect().left >= 0 &&
            panel.getBoundingClientRect().right <= window.innerWidth,
      activeLabel:
        document.querySelector('.primary-nav a[aria-current="page"]')?.textContent.trim() ?? null,
      brandImageWidth: brandImageRect?.width ?? null,
      brandImageHeight: brandImageRect?.height ?? null,
      brandImageNaturalWidth:
        brandImage instanceof HTMLImageElement ? brandImage.naturalWidth : null,
      brandImageNaturalHeight:
        brandImage instanceof HTMLImageElement ? brandImage.naturalHeight : null,
      brandImageBorderWidth: brandImageStyle?.borderTopWidth ?? null,
      brandImageObjectFit: brandImageStyle?.objectFit ?? null,
      undersizedTargets: [
        ...document.querySelectorAll(
          ".product-brand, .primary-nav a, .account-menu summary, .knowledge-citation-download, button, select, textarea, input:not([type='radio']):not([type='checkbox'])",
        ),
      ]
        .filter((element) => {
          if (!element.checkVisibility()) return false;
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44);
        })
        .map((element) => {
          const rect = element.getBoundingClientRect();
          const name =
            element.getAttribute("aria-label") ??
            element.getAttribute("id") ??
            element.textContent.trim();
          return `${element.tagName.toLowerCase()}#${name} (${rect.width.toFixed(1)}x${rect.height.toFixed(1)})`;
        }),
    };
  });
}

async function checkKnowledgeResourceLayout(page, expect, screenshotDir, viewport, themeValue) {
  await page.goto(
    `${new URL(page.url()).origin}/projects/${KNOWLEDGE_PROJECT_ID}/knowledge`,
    { waitUntil: "networkidle" },
  );
  await page.waitForSelector(".knowledge-resource-list");

  const layout = await readLayout(page);
  const knowledge = await page.evaluate(() => {
    const list = document.querySelector(".knowledge-resource-list");
    const listRect = list?.getBoundingClientRect();
    return {
      count: document.querySelectorAll(".knowledge-resource").length,
      statusLabels: [...document.querySelectorAll(".knowledge-resource-status")].map(
        (element) => element.textContent.trim(),
      ),
      insideViewport:
        listRect !== undefined && listRect !== null &&
        listRect.left >= 0 && listRect.right <= window.innerWidth,
    };
  });

  expect(layout.overflow <= 0, `${viewport.name} 项目知识页横向溢出 ${layout.overflow}px`);
  expect(layout.panelInsideViewport, `${viewport.name} 项目知识面板超出视口`);
  expect(knowledge.insideViewport, `${viewport.name} 知识资料列表超出视口`);
  expect(knowledge.count === 4, `${viewport.name} 应渲染 4 条知识资料，实际 ${knowledge.count}`);
  expect(
    knowledge.statusLabels.join(" | ") === "等待处理 | 处理中 | 可检索 | 处理失败",
    `${viewport.name} 知识资料状态不完整：${knowledge.statusLabels.join(" | ")}`,
  );
  expect(
    layout.undersizedTargets.length === 0,
    `${viewport.name} 项目知识页存在小于 44px 的交互目标：${layout.undersizedTargets.join(" / ")}`,
  );

  await page.getByLabel("搜索项目知识").fill("跨区域故障恢复");
  await page.getByRole("button", { name: "搜索项目知识" }).click();
  await page.waitForSelector(".knowledge-search-result-list");
  const searchLayout = await page.evaluate(() => {
    const panel = document.querySelector(".knowledge-search");
    const result = document.querySelector(".knowledge-search-result");
    const panelRect = panel?.getBoundingClientRect();
    const resultRect = result?.getBoundingClientRect();
    return {
      fallbackVisible: document.body.textContent.includes("语义检索暂时不可用"),
      panelInsideViewport: panelRect != null && panelRect.left >= 0 && panelRect.right <= innerWidth,
      resultInsideViewport: resultRect != null && resultRect.left >= 0 && resultRect.right <= innerWidth,
    };
  });
  expect(searchLayout.fallbackVisible, `${viewport.name} 应显示关键词降级提示`);
  expect(searchLayout.panelInsideViewport, `${viewport.name} 搜索面板超出视口`);
  expect(searchLayout.resultInsideViewport, `${viewport.name} 搜索结果超出视口`);
  const searchedLayout = await readLayout(page);
  expect(searchedLayout.overflow <= 0, `${viewport.name} 搜索结果横向溢出 ${searchedLayout.overflow}px`);
  expect(
    searchedLayout.undersizedTargets.length === 0,
    `${viewport.name} 搜索页存在小于 44px 的交互目标：${searchedLayout.undersizedTargets.join(" / ")}`,
  );

  await page.getByRole("button", { name: "查看引用上下文" }).click();
  await page.waitForSelector(".knowledge-citation-context");
  await page.waitForSelector('.knowledge-citation-chunk[data-hit="true"]');
  const contextLayout = await page.evaluate((expectedLongToken) => {
    const panel = document.querySelector(".knowledge-citation-context");
    const panelRect = panel?.getBoundingClientRect();
    const hit = document.querySelector('.knowledge-citation-chunk[data-hit="true"]');
    const download = document.querySelector(".knowledge-citation-download");
    const measure = (selector, kind) =>
      [...document.querySelectorAll(selector)].map((element, index) => ({
        kind,
        index,
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }));
    return {
      insideViewport:
        panelRect != null && panelRect.left >= 0 && panelRect.right <= window.innerWidth,
      labels: [...document.querySelectorAll(".knowledge-citation-chunk strong")]
        .map((node) => node.textContent.trim()),
      hitVisible: hit !== null,
      longTokenVisible: hit?.textContent.includes(expectedLongToken) ?? false,
      downloadTarget: download?.getAttribute("target"),
      downloadRel: download?.getAttribute("rel"),
      internalWidths: [
        ...measure(".knowledge-citation-context", "panel"),
        ...measure(".knowledge-citation-chunk", "chunk"),
        ...measure(".knowledge-citation-chunk p", "text"),
        ...measure(".knowledge-citation-chunk-heading span", "locator"),
      ],
    };
  }, KNOWLEDGE_NO_WHITESPACE_TOKEN);
  expect(contextLayout.insideViewport, `${viewport.name} 引用上下文超出视口`);
  expect(
    contextLayout.labels.join(" | ") === "前文 | 命中片段 | 后文",
    `${viewport.name} 引用顺序错误：${contextLayout.labels.join(" | ")}`,
  );
  expect(contextLayout.hitVisible, `${viewport.name} 未显示命中片段层级`);
  expect(contextLayout.longTokenVisible, `${viewport.name} 未完整渲染长 token`);
  expect(
    contextLayout.internalWidths.length === 10,
    `${viewport.name} 引用内部宽度测量不完整：${contextLayout.internalWidths.length}/10`,
  );
  const clippedCitationContent = contextLayout.internalWidths.filter(
    ({ clientWidth, scrollWidth }) => scrollWidth > clientWidth,
  );
  expect(
    clippedCitationContent.length === 0,
    `${viewport.name} 引用内容被内部裁切：${clippedCitationContent
      .map(({ kind, index, clientWidth, scrollWidth }) =>
        `${kind}[${index}] ${scrollWidth}px/${clientWidth}px`)
      .join(" / ")}`,
  );
  expect(contextLayout.downloadTarget === "_blank", `${viewport.name} 下载未打开新标签页`);
  expect(
    contextLayout.downloadRel === "noopener noreferrer",
    `${viewport.name} 下载链接缺少安全 rel`,
  );
  const expandedLayout = await readLayout(page);
  expect(expandedLayout.overflow <= 0, `${viewport.name} 引用上下文横向溢出`);
  expect(
    expandedLayout.undersizedTargets.length === 0,
    `${viewport.name} 引用操作目标小于 44px：${expandedLayout.undersizedTargets.join(" / ")}`,
  );

  await page.screenshot({
    path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-knowledge.png`),
    fullPage: true,
  });

  await page.getByLabel("搜索项目知识").fill(KNOWLEDGE_SEARCH_ERROR_QUERY);
  await page.getByRole("button", { name: "搜索项目知识" }).click();
  await page.waitForSelector(".knowledge-search-error");
  const errorLayout = await page.evaluate(({ expectedMessage, expectedTraceId }) => {
    const panel = document.querySelector(".knowledge-search");
    const error = document.querySelector(".knowledge-search-error");
    const retry = error?.querySelector("button");
    const alert = error?.querySelector('[role="alert"]');
    const requestId = [...(error?.querySelectorAll("p") ?? [])].find(
      (element) => element.textContent.trim() === `请求编号：${expectedTraceId}`,
    );
    const panelRect = panel?.getBoundingClientRect();
    const errorRect = error?.getBoundingClientRect();
    const messageRect = alert?.getBoundingClientRect();
    const requestIdRect = requestId?.getBoundingClientRect();
    const retryRect = retry?.getBoundingClientRect();
    const errorStyle = error === null ? null : getComputedStyle(error);
    const errorPadding = errorStyle === null ? null : {
      top: Number.parseFloat(errorStyle.paddingTop),
      right: Number.parseFloat(errorStyle.paddingRight),
      bottom: Number.parseFloat(errorStyle.paddingBottom),
      left: Number.parseFloat(errorStyle.paddingLeft),
    };
    const errorHorizontalPadding = errorPadding === null ? 0 : errorPadding.left + errorPadding.right;
    const availableButtonWidth = errorRect === undefined
      ? null
      : errorRect.width - errorHorizontalPadding;
    const insideErrorContent = (rect) =>
      rect != null && errorRect != null && errorPadding != null &&
      rect.left >= errorRect.left + errorPadding.left &&
      rect.right <= errorRect.right - errorPadding.right &&
      rect.top >= errorRect.top + errorPadding.top &&
      rect.bottom <= errorRect.bottom - errorPadding.bottom;
    const insideViewportHorizontally = (rect) =>
      rect != null && rect.left >= 0 && rect.right <= innerWidth;
    return {
      messageVisible: alert?.textContent.trim() === expectedMessage,
      traceVisible: requestId !== undefined,
      messageFitsOwnBox: alert != null && alert.scrollWidth <= alert.clientWidth,
      requestIdFitsOwnBox: requestId != null && requestId.scrollWidth <= requestId.clientWidth,
      messageInsideErrorContent: insideErrorContent(messageRect),
      requestIdInsideErrorContent: insideErrorContent(requestIdRect),
      messageInsideViewport: insideViewportHorizontally(messageRect),
      requestIdInsideViewport: insideViewportHorizontally(requestIdRect),
      messageScrollWidth: alert?.scrollWidth ?? null,
      messageClientWidth: alert?.clientWidth ?? null,
      requestIdScrollWidth: requestId?.scrollWidth ?? null,
      requestIdClientWidth: requestId?.clientWidth ?? null,
      errorInsidePanel:
        panelRect != null && errorRect != null &&
        errorRect.left >= panelRect.left && errorRect.right <= panelRect.right,
      errorInsideViewport:
        errorRect != null && errorRect.left >= 0 && errorRect.right <= innerWidth,
      retryInsidePanel:
        panelRect != null && retryRect != null &&
        retryRect.left >= panelRect.left && retryRect.right <= panelRect.right,
      retryInsideViewport:
        retryRect != null && retryRect.left >= 0 && retryRect.right <= innerWidth,
      retryTouchTarget:
        retryRect != null && retryRect.width >= 44 && retryRect.height >= 44,
      mobileRetryFillsAvailableWidth:
        innerWidth !== 360 ||
        (retryRect != null && availableButtonWidth != null &&
          Math.abs(retryRect.width - availableButtonWidth) <= 1),
      retryWidth: retryRect?.width ?? null,
      availableButtonWidth,
    };
  }, {
    expectedMessage: KNOWLEDGE_SEARCH_ERROR_MESSAGE,
    expectedTraceId: KNOWLEDGE_SEARCH_TRACE_ID,
  });
  expect(errorLayout.messageVisible, `${viewport.name} 应显示完整搜索错误`);
  expect(errorLayout.traceVisible, `${viewport.name} 应显示搜索请求编号`);
  expect(
    errorLayout.messageFitsOwnBox,
    `${viewport.name} 搜索错误消息被裁切：scrollWidth ${errorLayout.messageScrollWidth}px / clientWidth ${errorLayout.messageClientWidth}px`,
  );
  expect(
    errorLayout.requestIdFitsOwnBox,
    `${viewport.name} 搜索请求编号被裁切：scrollWidth ${errorLayout.requestIdScrollWidth}px / clientWidth ${errorLayout.requestIdClientWidth}px`,
  );
  expect(errorLayout.messageInsideErrorContent, `${viewport.name} 搜索错误消息超出错误内容区`);
  expect(errorLayout.requestIdInsideErrorContent, `${viewport.name} 搜索请求编号超出错误内容区`);
  expect(errorLayout.messageInsideViewport, `${viewport.name} 搜索错误消息超出视口`);
  expect(errorLayout.requestIdInsideViewport, `${viewport.name} 搜索请求编号超出视口`);
  expect(errorLayout.errorInsidePanel, `${viewport.name} 搜索错误超出面板`);
  expect(errorLayout.errorInsideViewport, `${viewport.name} 搜索错误超出视口`);
  expect(errorLayout.retryInsidePanel, `${viewport.name} 重试按钮超出面板`);
  expect(errorLayout.retryInsideViewport, `${viewport.name} 重试按钮超出视口`);
  expect(errorLayout.retryTouchTarget, `${viewport.name} 重试按钮小于 44px`);
  expect(
    errorLayout.mobileRetryFillsAvailableWidth,
    `${viewport.name} 重试按钮未填满可用宽度：${errorLayout.retryWidth}px / ${errorLayout.availableButtonWidth}px`,
  );
  const erroredLayout = await readLayout(page);
  expect(erroredLayout.overflow <= 0, `${viewport.name} 搜索错误横向溢出 ${erroredLayout.overflow}px`);
  expect(
    erroredLayout.undersizedTargets.length === 0,
    `${viewport.name} 搜索错误页存在小于 44px 的交互目标：${erroredLayout.undersizedTargets.join(" / ")}`,
  );

  await page.screenshot({
    path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-knowledge-error.png`),
    fullPage: true,
  });
  await page.getByRole("link", { name: "知识文档" }).click();
  await page.waitForSelector(".documents-panel");
}

async function checkProjectsLayout({
  page,
  expect,
  screenshotDir,
  viewport,
  themeValue,
  setScenario,
}) {
  setScenario("populated");
  await page.goto(`${new URL(page.url()).origin}/projects`, { waitUntil: "networkidle" });
  await page.waitForSelector(".task-workspace");

  const populatedLayout = await readLayout(page);
  const populated = await page.evaluate((firstId) => {
    const region = document.querySelector(".task-workspace");
    const heading = region?.querySelector("h2");
    const selectedButton = document.querySelector('.project-rail button[aria-pressed="true"]');
    const secondButton = [...document.querySelectorAll(".project-rail button")].find(
      (button) => button.textContent.includes("搜索体验升级"),
    );
    const switcher = document.querySelector("#project-switcher");
    const rail = document.querySelector(".project-rail");
    const mobileSwitcher = document.querySelector(".project-mobile-switcher");
    const acceptance = document.querySelector(".task-acceptance");
    const selectedStyle = selectedButton === null ? null : getComputedStyle(selectedButton);
    const railStyle = rail === null ? null : getComputedStyle(rail);
    const acceptanceStyle = acceptance === null ? null : getComputedStyle(acceptance);
    const readBoundary = (style) => style === null
      ? { widths: [], styles: [], colors: [] }
      : {
          widths: [
            style.borderTopWidth,
            style.borderRightWidth,
            style.borderBottomWidth,
            style.borderLeftWidth,
          ].map(Number.parseFloat),
          styles: [
            style.borderTopStyle,
            style.borderRightStyle,
            style.borderBottomStyle,
            style.borderLeftStyle,
          ],
          colors: [
            style.borderTopColor,
            style.borderRightColor,
            style.borderBottomColor,
            style.borderLeftColor,
          ],
        };
    return {
      expectedFirstRegionId: `project-task-workspace-${firstId}`,
      regionId: region?.id ?? null,
      labelledBy: region?.getAttribute("aria-labelledby") ?? null,
      headingId: heading?.id ?? null,
      selectedControls: selectedButton?.getAttribute("aria-controls") ?? null,
      secondControls: secondButton?.getAttribute("aria-controls") ?? null,
      switcherControls: switcher?.getAttribute("aria-controls") ?? null,
      railVisible: rail?.checkVisibility() ?? false,
      switcherVisible: mobileSwitcher?.checkVisibility() ?? false,
      selectedBackground: selectedStyle?.backgroundColor ?? null,
      railBackground: railStyle?.backgroundColor ?? null,
      selectedBoxShadow: selectedStyle?.boxShadow ?? null,
      selectedBoundary: readBoundary(selectedStyle),
      acceptanceBoundary: readBoundary(acceptanceStyle),
      emptyMascots: document.querySelectorAll(".project-empty-state .mascot-figure").length,
      taskMascots: document.querySelectorAll(".task-workspace .mascot-figure").length,
    };
  }, KNOWLEDGE_PROJECT_ID);

  expect(populatedLayout.overflow <= 0, `${viewport.name} 项目页横向溢出`);
  expect(populatedLayout.panelInsideViewport, `${viewport.name} 项目页超出视口`);
  expect(populatedLayout.activeLabel?.includes("项目"), `${viewport.name} 项目导航未激活`);
  expect(
    populatedLayout.undersizedTargets.length === 0,
    `${viewport.name} 项目页存在小于 44px 的交互目标：${populatedLayout.undersizedTargets.join(" / ")}`,
  );
  expect(
    populated.regionId === populated.expectedFirstRegionId &&
      populated.labelledBy === populated.headingId &&
      populated.headingId === `${populated.expectedFirstRegionId}-heading`,
    `${viewport.name} 当前任务区域缺少稳定 id/标题关联`,
  );
  expect(
    populated.selectedControls === populated.regionId &&
      populated.secondControls === populated.regionId &&
      populated.switcherControls === populated.regionId,
    `${viewport.name} 项目选择控件未指向当前任务区域`,
  );
  expect(
    populated.railVisible === (viewport.width >= 768) &&
      populated.switcherVisible === (viewport.width < 768),
    `${viewport.name} 项目轨道/选择器断点错误`,
  );
  expect(
    populated.selectedBackground !== populated.railBackground &&
      populated.selectedBoxShadow?.includes("inset"),
    `${viewport.name} 选中项目缺少完整表面与稳定内边界`,
  );
  assertUniformFullBoundary(populated.selectedBoundary, expect, `${viewport.name} 选中项目`);
  assertUniformFullBoundary(populated.acceptanceBoundary, expect, `${viewport.name} 验收标准`);
  expect(
    populated.emptyMascots === 0 && populated.taskMascots === 0,
    `${viewport.name} 非顶层空态不应渲染额外岑宁形象`,
  );

  await page.getByRole("button", { name: "开始任务" }).click();
  await page.waitForSelector('.task-transition-error[role="alert"]');
  const failedTransition = await page.evaluate((expectedMessage) => {
    const error = document.querySelector(".task-transition-error");
    const style = error === null ? null : getComputedStyle(error);
    const boundary = style === null
      ? { widths: [], styles: [], colors: [] }
      : {
          widths: [
            style.borderTopWidth,
            style.borderRightWidth,
            style.borderBottomWidth,
            style.borderLeftWidth,
          ].map(Number.parseFloat),
          styles: [
            style.borderTopStyle,
            style.borderRightStyle,
            style.borderBottomStyle,
            style.borderLeftStyle,
          ],
          colors: [
            style.borderTopColor,
            style.borderRightColor,
            style.borderBottomColor,
            style.borderLeftColor,
          ],
        };
    const action = [...document.querySelectorAll(".task-actions button")].find(
      (button) => button.textContent.includes("开始任务"),
    );
    const selectedProject = document.querySelector(
      '.project-rail button[aria-pressed="true"]',
    );
    const switcher = document.querySelector("#project-switcher");
    return {
      messageVisible: error?.textContent.trim() === expectedMessage,
      boundary,
      actionEnabled: action instanceof HTMLButtonElement && !action.disabled,
      selectedProjectEnabled:
        selectedProject instanceof HTMLButtonElement && !selectedProject.disabled,
      switcherEnabled: switcher instanceof HTMLSelectElement && !switcher.disabled,
      workspacePresent: document.querySelector(".task-workspace") !== null,
    };
  }, TASK_TRANSITION_ERROR_MESSAGE);
  expect(failedTransition.messageVisible, `${viewport.name} 未显示确定性任务更新错误`);
  assertUniformFullBoundary(
    failedTransition.boundary,
    expect,
    `${viewport.name} 任务更新错误`,
  );
  // Mutation proof: later `border: 0`, `border-left-color: red`, or a 3px left border
  // respectively produce zero/none, unequal colors, or asymmetric widths in computed style.
  // Each mutation fails here even when the earlier static rule still matches the CSS contract.
  expect(
    failedTransition.actionEnabled &&
      failedTransition.selectedProjectEnabled &&
      failedTransition.switcherEnabled &&
      failedTransition.workspacePresent,
    `${viewport.name} 任务更新失败后项目或任务控件不可继续使用`,
  );

  if (viewport.width < 768) {
    await page.selectOption("#project-switcher", RESPONSIVE_PROJECT_B_ID);
  } else {
    await page.getByRole("button", { name: /搜索体验升级/ }).click();
  }
  await page.waitForSelector(`#project-task-workspace-${RESPONSIVE_PROJECT_B_ID}`);
  const switched = await page.evaluate((projectId) => {
    const regionId = `project-task-workspace-${projectId}`;
    return {
      regionPresent: document.getElementById(regionId) !== null,
      selectedControls: document.querySelector('.project-rail button[aria-pressed="true"]')
        ?.getAttribute("aria-controls") ?? null,
      switcherControls: document.querySelector("#project-switcher")
        ?.getAttribute("aria-controls") ?? null,
      announcement: document.querySelector(".project-selection-announcement")?.textContent ?? null,
    };
  }, RESPONSIVE_PROJECT_B_ID);
  expect(switched.regionPresent, `${viewport.name} 选择项目后未切换受控区域`);
  expect(
    switched.selectedControls === `project-task-workspace-${RESPONSIVE_PROJECT_B_ID}` &&
      switched.switcherControls === `project-task-workspace-${RESPONSIVE_PROJECT_B_ID}`,
    `${viewport.name} 选择项目后 aria-controls 未更新`,
  );
  expect(
    switched.announcement === "已选择项目：搜索体验升级",
    `${viewport.name} 项目选择播报错误：${switched.announcement}`,
  );

  const populatedImages = await readImageHealth(page);
  expectHealthyImages(populatedImages, expect, `${viewport.name} 项目页`);
  expectThumbnailMascots(populatedImages, expect, `${viewport.name} 项目页`);
  await page.screenshot({
    path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-projects.png`),
    fullPage: true,
  });

  setScenario("empty");
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(".project-empty-state");
  await page.waitForFunction(() => {
    const image = document.querySelector(".project-empty-state .mascot-figure img");
    return image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0;
  });
  const emptyLayout = await readLayout(page);
  const empty = await page.evaluate(() => {
    const mascot = document.querySelector(".project-empty-state .mascot-figure img");
    const heading = document.querySelector(".project-empty-state h2");
    const mascotStyle = mascot === null ? null : getComputedStyle(mascot);
    const mascotRect = mascot?.getBoundingClientRect();
    const headingRect = heading?.getBoundingClientRect();
    const headingStyle = heading === null ? null : getComputedStyle(heading);
    const cssPixels = (values) => values.map(Number.parseFloat);
    const radius = mascotStyle?.borderTopLeftRadius ?? "";
    const radiusValue = Number.parseFloat(radius);
    const circular = mascotRect != null && Number.isFinite(radiusValue) && (
      radius.endsWith("%")
        ? radiusValue >= 50
        : radiusValue >= Math.min(mascotRect.width, mascotRect.height) / 2
    );
    return {
      emptyMascots: document.querySelectorAll(".project-empty-state .mascot-figure").length,
      taskWorkspacePresent: document.querySelector(".task-workspace") !== null,
      alt: mascot?.getAttribute("alt") ?? null,
      currentSrc: mascot instanceof HTMLImageElement ? mascot.currentSrc : null,
      naturalWidth: mascot instanceof HTMLImageElement ? mascot.naturalWidth : null,
      naturalHeight: mascot instanceof HTMLImageElement ? mascot.naturalHeight : null,
      transparentBackground:
        mascotStyle?.backgroundColor === "transparent" ||
        /^rgba\(.+,\s*0(?:\.0+)?\)$/.test(mascotStyle?.backgroundColor ?? ""),
      borderWidths: mascotStyle === null ? [] : cssPixels([
        mascotStyle.borderTopWidth,
        mascotStyle.borderRightWidth,
        mascotStyle.borderBottomWidth,
        mascotStyle.borderLeftWidth,
      ]),
      paddings: mascotStyle === null ? [] : cssPixels([
        mascotStyle.paddingTop,
        mascotStyle.paddingRight,
        mascotStyle.paddingBottom,
        mascotStyle.paddingLeft,
      ]),
      renderedWidth: mascotRect?.width ?? null,
      renderedHeight: mascotRect?.height ?? null,
      circular,
      headingWidth: headingRect?.width ?? null,
      headingFontSize: headingStyle === null ? null : Number.parseFloat(headingStyle.fontSize),
    };
  });
  expect(emptyLayout.overflow <= 0, `${viewport.name} 项目顶层空态横向溢出`);
  expect(emptyLayout.panelInsideViewport, `${viewport.name} 项目顶层空态超出视口`);
  expect(emptyLayout.activeLabel?.includes("项目"), `${viewport.name} 空态项目导航未激活`);
  expect(
    emptyLayout.undersizedTargets.length === 0,
    `${viewport.name} 项目空态存在小于 44px 的交互目标：${emptyLayout.undersizedTargets.join(" / ")}`,
  );
  expect(
    empty.emptyMascots === 1 && !empty.taskWorkspacePresent && empty.alt?.includes("岑宁"),
    `${viewport.name} 岑宁应只出现在项目顶层空态`,
  );
  expect(
    empty.transparentBackground &&
      empty.borderWidths.length === 4 && empty.borderWidths.every((width) => width === 0) &&
      empty.paddings.length === 4 && empty.paddings.every((padding) => padding === 0),
    `${viewport.name} 项目空态岑宁不应有矩形框：border ${empty.borderWidths.join("/")}px、padding ${empty.paddings.join("/")}px`,
  );
  const expectedEmptyAsset = viewport.width < 600
    ? "/cairn-mascot-chibi.png"
    : "/cairn-mascot-transparent.png";
  const expectedEmptyDimensions = viewport.width < 600 ? [512, 512] : [1024, 1536];
  expect(
    empty.currentSrc?.endsWith(expectedEmptyAsset) &&
      empty.naturalWidth === expectedEmptyDimensions[0] &&
      empty.naturalHeight === expectedEmptyDimensions[1],
    `${viewport.name} 项目空态岑宁素材异常：${empty.currentSrc} (${empty.naturalWidth}x${empty.naturalHeight})`,
  );
  if (viewport.width < 600) {
    expect(
      Number.isFinite(empty.renderedWidth) &&
        Number.isFinite(empty.renderedHeight) &&
        empty.renderedWidth >= 112 && empty.renderedWidth <= 128 &&
        Math.abs(empty.renderedWidth - empty.renderedHeight) < 1 &&
        empty.circular,
      `${viewport.name} 项目空态头像应为 112–128px 的正圆，实际 ${empty.renderedWidth}x${empty.renderedHeight}`,
    );
    expect(
      Number.isFinite(empty.headingWidth) &&
        Number.isFinite(empty.headingFontSize) &&
        empty.headingWidth >= empty.headingFontSize * 3,
      `${viewport.name} 项目空态标题过窄：${empty.headingWidth}px / 字号 ${empty.headingFontSize}px`,
    );
  }
  await page.screenshot({
    path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-projects-empty.png`),
    fullPage: true,
  });
  setScenario("populated");
}

async function readImageHealth(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll(".login-wordmark, .product-brand img, .mascot-figure img")].map(
      (image) => {
        let cornerAlpha = null;
        if (image.complete && image.naturalWidth > 0 && image.naturalHeight > 0) {
          const canvas = document.createElement("canvas");
          canvas.width = 1;
          canvas.height = 1;
          const context = canvas.getContext("2d");
          if (context !== null) {
            context.drawImage(image, 0, 0, 1, 1, 0, 0, 1, 1);
            cornerAlpha = context.getImageData(0, 0, 1, 1).data[3];
          }
        }

        return {
          alt: image.getAttribute("alt"),
          src: image.getAttribute("src"),
          currentSrc: image.currentSrc,
          complete: image.complete,
          naturalWidth: image.naturalWidth,
          naturalHeight: image.naturalHeight,
          cornerAlpha,
        };
      },
    ),
  );
}

async function readProductBrandAppearance(page, screenshot) {
  const brandImage = page.locator(".product-brand img");
  const bounds = await brandImage.boundingBox();
  if (bounds === null) throw new Error("顶栏 wordmark 不可见");

  return page.evaluate(
    async ({ source, backgroundX, imageX, sampleY }) => {
      const rendered = new Image();
      rendered.src = source;
      await rendered.decode();
      const canvas = document.createElement("canvas");
      canvas.width = rendered.naturalWidth;
      canvas.height = rendered.naturalHeight;
      const context = canvas.getContext("2d");
      if (context === null) throw new Error("无法读取顶栏 wordmark 截图");
      context.drawImage(rendered, 0, 0);

      const readPixel = (x, y) =>
        [...context.getImageData(x, y, 1, 1).data].slice(0, 3);
      return {
        backgroundPixel: readPixel(backgroundX, sampleY),
        imageBackgroundPixel: readPixel(imageX, sampleY),
      };
    },
    {
      source: `data:image/png;base64,${screenshot.toString("base64")}`,
      backgroundX: Math.max(0, Math.floor(bounds.x) - 2),
      imageX: Math.round(bounds.x + bounds.width / 2),
      sampleY: Math.floor(bounds.y) + 1,
    },
  );
}

async function waitForLoginBrandScenePaint(page) {
  await page.waitForFunction(
    () => {
      const images = [
        document.querySelector(".login-wordmark"),
        document.querySelector(
          ".login-brand-scene .mascot-figure[data-variant='full'] .mascot-art > img",
        ),
      ];
      return images.every(
        (image) => image instanceof HTMLImageElement &&
          image.complete &&
          image.naturalWidth > 0 &&
          image.naturalHeight > 0,
      );
    },
    undefined,
    { timeout: 5_000 },
  );
  await page.evaluate(async () => {
    const images = [
      document.querySelector(".login-wordmark"),
      document.querySelector(
        ".login-brand-scene .mascot-figure[data-variant='full'] .mascot-art > img",
      ),
    ];
    if (!images.every((image) => image instanceof HTMLImageElement)) {
      throw new Error("登录品牌图片在绘制前离开了 DOM");
    }
    await Promise.all(images.map((image) => image.decode()));
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
  });
}

async function readLoginBrandScene(page) {
  return page.evaluate(() => {
    const scene = document.querySelector(".login-brand-scene");
    const state = document.querySelector(".login-brand-scene .mascot-state");
    if (scene === null) return null;
    const chip = document.querySelector(".login-wordmark-chip");
    const mascot = document.querySelector(
      ".login-brand-scene .mascot-figure[data-variant='full'] .mascot-art > img, " +
        ".login-brand-scene .mascot-figure[data-variant='full'] .mascot-image-fallback",
    );
    const card = document.querySelector(".login-card");
    const mascotFigure = mascot?.closest(".mascot-figure");
    const sceneStyle = getComputedStyle(scene);
    const chipRect = chip?.getBoundingClientRect();
    const mascotRect = mascot?.getBoundingClientRect();
    const stateRect = state?.getBoundingClientRect();
    return {
      backgroundImage: sceneStyle.backgroundImage,
      overflow: sceneStyle.overflow,
      position: sceneStyle.position,
      // 状态文字压在深色渐变上，必须是纯白。
      // 设计阶段实测：#ffffff 在渐变最亮处 #3a6fb0 上是 5.15:1（AA 要求 4.5:1）；
      // 原来的 --color-muted #596675 只有 1.14:1，等于看不见。
      // 这里断言颜色值而不是算对比度：渐变背景取不到"文字底下那一点的实际颜色"，
      // 断言一个已经算过的确定值比在运行时近似计算更可靠。
      stateColor: state === null ? null : getComputedStyle(state).color,
      // 三角装饰用 ::before / ::after 的 border 画法。
      // borderBottomWidth 非 0 说明三角形真的画出来了。
      decorTopWidth: getComputedStyle(scene, "::before").borderBottomWidth,
      decorBottomWidth: getComputedStyle(scene, "::after").borderBottomWidth,
      decorTopZIndex: getComputedStyle(scene, "::before").zIndex,
      decorBottomZIndex: getComputedStyle(scene, "::after").zIndex,
      wordmarkChipPresent: chip !== null,
      wordmarkChipVisible: chip?.checkVisibility() ?? false,
      wordmarkChipBackground:
        chip === null ? null : getComputedStyle(chip).backgroundColor,
      wordmarkChipRadius:
        chip === null ? null : getComputedStyle(chip).borderRadius,
      wordmarkChipWidth: chipRect?.width ?? null,
      wordmarkChipHeight: chipRect?.height ?? null,
      wordmarkChipZIndex:
        chip === null ? null : getComputedStyle(chip).zIndex,
      mascotVisible: mascot?.checkVisibility() ?? false,
      mascotWidth: mascotRect?.width ?? null,
      mascotHeight: mascotRect?.height ?? null,
      mascotBorderWidth:
        mascot === null ? null : getComputedStyle(mascot).borderTopWidth,
      mascotFilter:
        mascot === null ? null : getComputedStyle(mascot).filter,
      mascotTransform:
        mascot === null ? null : getComputedStyle(mascot).transform,
      mascotZIndex:
        mascotFigure === null || mascotFigure === undefined
          ? null
          : getComputedStyle(mascotFigure).zIndex,
      stateVisible: state?.checkVisibility() ?? false,
      stateWidth: stateRect?.width ?? null,
      stateHeight: stateRect?.height ?? null,
      cardHairlineHeight:
        card === null ? null : getComputedStyle(card, "::before").height,
      cardHairlineBackground:
        card === null ? null : getComputedStyle(card, "::before").backgroundImage,
    };
  });
}

async function readAssistantContentLayout(page) {
  return page.evaluate(() => {
    const image = document.querySelector(
      ".mascot-assistant-body .mascot-art > img, .mascot-assistant-body .mascot-image-fallback",
    );
    const copy = document.querySelector(".mascot-assistant-body > p");
    const imageRect = image?.getBoundingClientRect();
    const copyRect = copy?.getBoundingClientRect();
    return {
      currentSrc: image instanceof HTMLImageElement ? image.currentSrc : null,
      imageRight: imageRect?.right ?? null,
      naturalHeight: image instanceof HTMLImageElement ? image.naturalHeight : null,
      naturalWidth: image instanceof HTMLImageElement ? image.naturalWidth : null,
      copyLeft: copyRect?.left ?? null,
      renderedHeight: imageRect?.height ?? null,
      renderedWidth: imageRect?.width ?? null,
    };
  });
}

function expectHealthyImages(images, expect, context) {
  expect(images.length > 0, `${context} 应渲染品牌或看板娘图片`);
  for (const image of images) {
    expect(
      image.complete && image.naturalWidth > 0 && image.naturalHeight > 0,
      `${context} 图片未加载：${image.src} (${image.naturalWidth}x${image.naturalHeight})`,
    );
  }
}

function expectThumbnailMascots(images, expect, context) {
  const mascots = images.filter(
    (image) => image.alt?.includes("岑宁"),
  );
  expect(mascots.length > 0, `${context} 应渲染看板娘缩略图`);
  for (const mascot of mascots) {
    expect(
      mascot.currentSrc.endsWith("/cairn-mascot-chibi.png"),
      `${context} 应使用缩略图，实际为 ${mascot.currentSrc}`,
    );
    expect(
      mascot.naturalWidth === 512 && mascot.naturalHeight === 512,
      `${context} 缩略图尺寸错误：${mascot.naturalWidth}x${mascot.naturalHeight}`,
    );
    expect(mascot.cornerAlpha === 0, `${context} 缩略图圆角外必须透明`);
  }
}

function expectLoginMascot(images, viewport, expect) {
  const mascot = images.find((image) => image.alt === "岑宁，Cairn 知识向导");
  const expectedAsset = viewport.width < 600
    ? "/cairn-mascot-chibi.png"
    : "/cairn-mascot-transparent.png";
  expect(
    mascot?.currentSrc.endsWith(expectedAsset),
    `${viewport.name} 登录页素材选择错误：${mascot?.currentSrc ?? "未渲染"}`,
  );
}

export async function checkResponsiveFoundation({
  page,
  expect,
  screenshotDir,
  login,
  logout,
  waitForAuthenticated,
}) {
  let projectsScenario = "populated";
  await page.route(/\/api\/v1\/projects(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      json: {
        items: projectsScenario === "populated" ? RESPONSIVE_PROJECTS : [],
        nextCursor: null,
      },
    });
  });
  await page.route(/\/api\/v1\/projects\/[^/]+\/tasks(?:\?.*)?$/, async (route) => {
    const projectId = new URL(route.request().url()).pathname.split("/").at(-2);
    await route.fulfill({
      json: {
        items: RESPONSIVE_TASKS[projectId] ?? [],
        nextCursor: null,
      },
    });
  });
  await page.route(/\/api\/v1\/tasks\/[^/]+\/status$/, async (route) => {
    const request = route.request();
    expect(request.method() === "PATCH", "任务状态转换必须使用 PATCH");
    expect(request.headers()["x-csrf-token"], "任务状态转换必须携带 CSRF token");
    expect(
      JSON.stringify(request.postDataJSON()) === JSON.stringify({ status: "in_progress" }),
      `任务状态转换请求体错误：${request.postData()}`,
    );
    await route.fulfill({
      status: 503,
      headers: { "X-Request-ID": TASK_TRANSITION_TRACE_ID },
      json: {
        code: "database_unavailable",
        message: TASK_TRANSITION_ERROR_MESSAGE,
        traceId: TASK_TRANSITION_TRACE_ID,
      },
    });
  });
  await page.route(
    `**/api/v1/projects/${KNOWLEDGE_PROJECT_ID}/knowledge/resources*`,
    (route) => route.fulfill({ json: KNOWLEDGE_RESOURCE_PAGE }),
  );
  await page.route(
    `**/api/v1/projects/${KNOWLEDGE_PROJECT_ID}/knowledge/search`,
    async (route) => {
      const request = route.request();
      expect(request.method() === "POST", "知识搜索必须使用 POST");
      expect(request.headers()["x-csrf-token"], "知识搜索必须携带 CSRF token");
      const body = request.postDataJSON();
      if (body.query === "跨区域故障恢复") {
        expect(
          JSON.stringify(body) === JSON.stringify({ query: "跨区域故障恢复", limit: 10 }),
          `知识搜索请求体错误：${request.postData()}`,
        );
        await route.fulfill({ json: KNOWLEDGE_SEARCH_RESPONSE });
        return;
      }
      expect(
        JSON.stringify(body) === JSON.stringify({ query: KNOWLEDGE_SEARCH_ERROR_QUERY, limit: 10 }),
        `知识搜索错误场景请求体错误：${request.postData()}`,
      );
      await route.fulfill({
        status: 503,
        headers: { "X-Request-ID": KNOWLEDGE_SEARCH_TRACE_ID },
        json: {
          message: KNOWLEDGE_SEARCH_ERROR_MESSAGE,
          code: "database_unavailable",
          traceId: KNOWLEDGE_SEARCH_TRACE_ID,
        },
      });
    },
  );
  await page.route(
    `**/api/v1/projects/${KNOWLEDGE_PROJECT_ID}/knowledge/resources/*/chunks/*`,
    async (route) => {
      const request = route.request();
      expect(request.method() === "GET", "引用上下文必须使用 GET");
      expect(
        new URL(request.url()).pathname ===
          `/api/v1/projects/${KNOWLEDGE_PROJECT_ID}/knowledge/resources/${KNOWLEDGE_RESOURCE_ID}/chunks/${KNOWLEDGE_CHUNK_ID}`,
        `引用上下文路径错误：${request.url()}`,
      );
      await route.fulfill({ json: KNOWLEDGE_CHUNK_CONTEXT });
    },
  );

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });

    await logout();
    await login();
    for (const [themeLabel, themeValue] of [
      ["日间", "light"],
      ["夜间", "dark"],
    ]) {
      await chooseTheme(page, themeLabel);
      await page.getByRole("link", { name: "知识文档" }).click();
      await page.waitForSelector(".documents-panel");

      const documents = await readLayout(page);
      expect(documents.theme === themeValue, `${viewport.name} 应使用 ${themeValue} 主题`);
      expect(documents.overflow <= 0, `${viewport.name} 文档页横向溢出 ${documents.overflow}px`);
      expect(documents.panelInsideViewport, `${viewport.name} 文档面板超出视口`);
      expect(
        documents.workspaceOverflowX !== "scroll",
        `${viewport.name} 文档工作区不应强制横向滚动`,
      );
      expect(documents.activeLabel?.includes("文档"), `${viewport.name} 文档导航未激活`);
      expect(
        Number.isFinite(documents.brandImageWidth) &&
          Number.isFinite(documents.brandImageHeight) &&
          Number.isFinite(documents.brandImageNaturalWidth) &&
          Number.isFinite(documents.brandImageNaturalHeight) &&
          Math.abs(
            documents.brandImageWidth / documents.brandImageHeight -
              documents.brandImageNaturalWidth / documents.brandImageNaturalHeight,
          ) < 0.01 &&
          documents.brandImageBorderWidth === "0px" &&
          documents.brandImageObjectFit === "contain",
        `${viewport.name} 顶栏 wordmark 应保持横向比例且没有控件式边框，实际为 ${documents.brandImageWidth}x${documents.brandImageHeight}、边框 ${documents.brandImageBorderWidth}、适配 ${documents.brandImageObjectFit}`,
      );
      expect(
        documents.undersizedTargets.length === 0,
        `${viewport.name} 文档页存在小于 44px 的交互目标：${documents.undersizedTargets.join(" / ")}`,
      );
      expect(
        await page.getByRole("button", { name: "打开岑宁助手" }).isVisible(),
        `${viewport.name} 看板娘助手入口不可见`,
      );
      const documentImages = await readImageHealth(page);
      expectHealthyImages(documentImages, expect, `${viewport.name} 文档页`);
      expectThumbnailMascots(documentImages, expect, `${viewport.name} 文档页`);
      const documentsScreenshot = await page.screenshot({
        path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-documents.png`),
        fullPage: true,
      });
      const brandAppearance = await readProductBrandAppearance(page, documentsScreenshot);
      expect(
        brandAppearance.imageBackgroundPixel.every(
          (channel, index) =>
            Math.abs(channel - brandAppearance.backgroundPixel[index]) <= 3,
        ),
        `${viewport.name} ${themeValue} 顶栏 wordmark 背景必须融入顶栏，实际图片像素 ${brandAppearance.imageBackgroundPixel.join(",")} / 顶栏 ${brandAppearance.backgroundPixel.join(",")}`,
      );

      const assistantTrigger = page.getByRole("button", { name: "打开岑宁助手" });
      await assistantTrigger.click();
      expect(
        await page.getByRole("dialog", { name: "岑宁助手" }).isVisible(),
        `${viewport.name} 看板娘助手面板未打开`,
      );
      await page.waitForFunction(() => {
        const image = document.querySelector(
          ".mascot-assistant-body .mascot-art > img, .mascot-assistant-body .mascot-image-fallback",
        );
        return image instanceof HTMLImageElement &&
          image.complete && image.naturalWidth > 0 && image.naturalHeight > 0;
      });
      const assistantLayout = await readAssistantContentLayout(page);
      expect(
        assistantLayout.currentSrc?.endsWith("/cairn-mascot-chibi.png") &&
          assistantLayout.naturalWidth === 512 &&
          assistantLayout.naturalHeight === 512,
        `${viewport.name} 助手面板应使用 512px Q 版头像，实际为 ${assistantLayout.currentSrc} (${assistantLayout.naturalWidth}x${assistantLayout.naturalHeight})`,
      );
      expect(
        assistantLayout.renderedWidth !== null &&
          assistantLayout.renderedHeight !== null &&
          Math.abs(assistantLayout.renderedWidth - 92) < 1 &&
          Math.abs(assistantLayout.renderedHeight - 92) < 1,
        `${viewport.name} 助手面板头像应渲染为 92px 正圆，实际为 ${assistantLayout.renderedWidth}x${assistantLayout.renderedHeight}`,
      );
      expect(
        assistantLayout.imageRight !== null &&
          assistantLayout.copyLeft !== null &&
          assistantLayout.imageRight <= assistantLayout.copyLeft,
        `${viewport.name} 看板娘图片与助手说明发生重叠：图片右侧 ${assistantLayout.imageRight}px，文字左侧 ${assistantLayout.copyLeft}px`,
      );
      await page.screenshot({
        path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-assistant.png`),
        fullPage: true,
      });
      await page.keyboard.press("Escape");
      expect(
        !(await page.getByRole("dialog", { name: "岑宁助手" }).isVisible()),
        `${viewport.name} Escape 后看板娘助手仍可见`,
      );
      expect(
        await assistantTrigger.evaluate((element) => document.activeElement === element),
        `${viewport.name} Escape 后焦点应返回助手入口`,
      );

      await checkProjectsLayout({
        page,
        expect,
        screenshotDir,
        viewport,
        themeValue,
        setScenario: (scenario) => {
          projectsScenario = scenario;
        },
      });

      await checkKnowledgeResourceLayout(page, expect, screenshotDir, viewport, themeValue);

      await page.selectOption("#scenario", "empty");
      await page.click("#load-btn");
      await page.waitForFunction(() =>
        document.querySelector("#status-bar")?.textContent.includes("还没有文档"),
      );
      expect(
        await page.getByRole("heading", { name: "建立知识空间" }).isVisible(),
        `${viewport.name} 文档空态缺少看板娘提示`,
      );
      await page.screenshot({
        path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-documents-empty.png`),
        fullPage: true,
      });

      await page.getByRole("link", { name: "知识问答" }).click();
      await page.waitForSelector(".assistant-panel");
      const ask = await readLayout(page);
      expect(ask.overflow <= 0, `${viewport.name} 问答页横向溢出 ${ask.overflow}px`);
      expect(ask.panelInsideViewport, `${viewport.name} 问答面板超出视口`);
      expect(ask.activeLabel?.includes("问答"), `${viewport.name} 问答导航未激活`);
      expect(
        ask.undersizedTargets.length === 0,
        `${viewport.name} 问答页存在小于 44px 的交互目标：${ask.undersizedTargets.join(" / ")}`,
      );
      const askImages = await readImageHealth(page);
      expectHealthyImages(askImages, expect, `${viewport.name} 问答页`);
      expectThumbnailMascots(askImages, expect, `${viewport.name} 问答页`);

      await page.screenshot({
        path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-ask-empty.png`),
        fullPage: true,
      });

      await page.fill("#question", "值班故障如何升级？");
      await page.click('.question-form button[type="submit"]');
      await page.waitForSelector('[data-role="pending"]');
      await page.screenshot({
        path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-ask-pending.png`),
        fullPage: true,
      });
      await page.getByRole("button", { name: "停止生成" }).click();
      await page.waitForSelector('[data-role="pending"]', { state: "detached" });

      if (viewport.width < 600) {
        expect(ask.navPosition === "fixed", "手机导航必须固定在视口底部");
        expect(
          ask.navBottom !== null && Math.abs(ask.navBottom - ask.viewportHeight) < 1,
          "手机导航必须贴合视口底部",
        );
        expect(
          ask.workspacePaddingBottom > ask.navHeight,
          "手机工作区必须为底部导航预留空间",
        );
      } else {
        expect(ask.navPosition !== "fixed", `${viewport.name} 不应使用固定底部导航`);
      }

      await logout();
      await waitForLoginBrandScenePaint(page);
      const loginImages = await readImageHealth(page);
      expectHealthyImages(loginImages, expect, `${viewport.name} 登录页`);
      expectLoginMascot(loginImages, viewport, expect);
      const brandScene = await readLoginBrandScene(page);
      if (brandScene === null) {
        expect(false, `${viewport.name} 登录页缺少品牌场景`);
        await page.screenshot({
          path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-login.png`),
          fullPage: true,
        });
        await login();
        continue;
      }
      expect(
        typeof brandScene.backgroundImage === "string" &&
          brandScene.backgroundImage.includes("gradient"),
        `${viewport.name} 品牌区应使用渐变背景，实际为 ${brandScene.backgroundImage}`,
      );
      expect(
        brandScene.position === "relative",
        `${viewport.name} 品牌区需要 position: relative 作为装饰元素的定位基准`,
      );
      expect(
        brandScene.stateColor === "rgb(255, 255, 255)",
        `${viewport.name} 品牌区状态文字必须为纯白以满足 4.5:1 对比度，实际为 ${brandScene.stateColor}`,
      );
      expect(
        typeof brandScene.decorTopWidth === "string" &&
          typeof brandScene.decorBottomWidth === "string" &&
          Number.parseFloat(brandScene.decorTopWidth) > 0 &&
          Number.parseFloat(brandScene.decorBottomWidth) > 0,
        `${viewport.name} 品牌区应有两个三角装饰，实际 ::before=${brandScene.decorTopWidth} ::after=${brandScene.decorBottomWidth}`,
      );
      const approvedGradientStops = [
        "rgb(58, 111, 176)",
        "rgb(31, 75, 134)",
        "rgb(23, 51, 92)",
      ];
      expect(
        typeof brandScene.backgroundImage === "string" &&
          approvedGradientStops.every((stop) => brandScene.backgroundImage.includes(stop)),
        `${viewport.name} 品牌区渐变不是已审阅的三段配色，实际为 ${brandScene.backgroundImage}`,
      );
      expect(
        brandScene.wordmarkChipPresent &&
          brandScene.wordmarkChipVisible &&
          typeof brandScene.wordmarkChipBackground === "string" &&
          brandScene.wordmarkChipBackground !== "rgba(0, 0, 0, 0)" &&
          typeof brandScene.wordmarkChipRadius === "string" &&
          Number.parseFloat(brandScene.wordmarkChipRadius) > 0,
        `${viewport.name} wordmark 必须由有背景和圆角的胶囊承载`,
      );
      expect(
        Number.isFinite(brandScene.wordmarkChipWidth) &&
          Number.isFinite(brandScene.wordmarkChipHeight) &&
          brandScene.wordmarkChipWidth > brandScene.wordmarkChipHeight,
        `${viewport.name} wordmark 胶囊不应被网格拉伸，实际为 ${brandScene.wordmarkChipWidth}x${brandScene.wordmarkChipHeight}`,
      );
      expect(
        brandScene.mascotVisible &&
          Number.isFinite(brandScene.mascotWidth) &&
          brandScene.mascotWidth > 0 &&
          Number.isFinite(brandScene.mascotHeight) &&
          brandScene.mascotHeight > 0 &&
          brandScene.mascotBorderWidth === "0px",
        `${viewport.name} 看板娘必须去掉控件式边框并保持可见`,
      );
      expect(
        brandScene.stateVisible &&
          Number.isFinite(brandScene.stateWidth) &&
          brandScene.stateWidth > 0 &&
          Number.isFinite(brandScene.stateHeight) &&
          brandScene.stateHeight > 0,
        `${viewport.name} 看板娘状态文字必须可见且占据实际布局空间`,
      );
      expect(
        brandScene.cardHairlineHeight === "4px" &&
          typeof brandScene.cardHairlineBackground === "string" &&
          brandScene.cardHairlineBackground.includes("gradient"),
        `${viewport.name} 登录卡片必须保留 4px 主题渐变细线`,
      );
      const expectedHairlineStops = themeValue === "dark"
        ? ["rgb(133, 179, 238)", "rgb(120, 201, 167)"]
        : ["rgb(40, 91, 159)", "rgb(38, 114, 91)"];
      expect(
        typeof brandScene.cardHairlineBackground === "string" &&
          expectedHairlineStops.every((stop) =>
            brandScene.cardHairlineBackground.includes(stop)),
        `${viewport.name} ${themeValue} 登录卡片细线没有使用对应主题色，实际为 ${brandScene.cardHairlineBackground}`,
      );
      expect(
        brandScene.overflow === "hidden" &&
          brandScene.decorTopZIndex === "0" &&
          brandScene.decorBottomZIndex === "0" &&
          brandScene.wordmarkChipZIndex === "1" &&
          brandScene.mascotZIndex === "1",
        `${viewport.name} 品牌内容必须位于裁切后的三角装饰之上`,
      );

      const expectedDecor = viewport.width < 600
        ? { top: "100px", bottom: "75px" }
        : viewport.width < 1024
          ? { top: "150px", bottom: "112px" }
          : { top: "200px", bottom: "150px" };
      expect(
        brandScene.decorTopWidth === expectedDecor.top &&
          brandScene.decorBottomWidth === expectedDecor.bottom,
        `${viewport.name} 三角装饰尺寸错误，实际为 ${brandScene.decorTopWidth}/${brandScene.decorBottomWidth}`,
      );

      if (viewport.width < 600) {
        expect(
          typeof brandScene.mascotTransform === "string" &&
            brandScene.mascotTransform === "none",
          `mobile 透明头像不应继承桌面旋转，实际为 ${brandScene.mascotTransform}`,
        );
        expect(
          brandScene.mascotFilter === "none",
          `mobile 透明头像不应继承桌面轮廓滤镜，实际为 ${brandScene.mascotFilter}`,
        );
        expect(
          Number.isFinite(brandScene.wordmarkChipHeight) &&
            brandScene.wordmarkChipHeight <= 40,
          `mobile wordmark 胶囊不应被网格拉伸，实际高度为 ${brandScene.wordmarkChipHeight}px`,
        );
      } else {
        expect(
          typeof brandScene.mascotFilter === "string" &&
            brandScene.mascotFilter.includes("drop-shadow"),
          `${viewport.name} 桌面透明全身图应保留轮廓投影，实际为 ${brandScene.mascotFilter}`,
        );
        expect(
          typeof brandScene.mascotTransform === "string" &&
            brandScene.mascotTransform === "none",
          `${viewport.name} 桌面透明全身图不应保留相框旋转，实际为 ${brandScene.mascotTransform}`,
        );
      }
      await page.screenshot({
        path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-login.png`),
        fullPage: true,
      });
      await login();
    }

    await logout();
    expect(
      (await page.locator("html").getAttribute("data-theme")) === "dark",
      `${viewport.name} 注销不应清除夜间主题`,
    );
    await login();
    expect(
      (await page.locator("html").getAttribute("data-theme")) === "dark",
      `${viewport.name} 重新登录后应保留夜间主题`,
    );
  }

  await logout();
  await page.emulateMedia({ colorScheme: "dark" });
  await page.evaluate(() => localStorage.removeItem("cairn-theme"));
  await page.reload({ waitUntil: "networkidle" });
  expect(
    (await page.locator("html").getAttribute("data-theme")) === "dark",
    "无手动偏好时应跟随系统夜间主题",
  );
  await login();

  await chooseTheme(page, "日间");
  await page.reload({ waitUntil: "networkidle" });
  await waitForAuthenticated();
  expect(
    (await page.locator("html").getAttribute("data-theme")) === "light",
    "手动日间主题应在刷新后保留",
  );

  await chooseTheme(page, "跟随系统");
  expect(
    (await page.evaluate(() => localStorage.getItem("cairn-theme"))) === null,
    "跟随系统应清除本地覆盖",
  );
  await page.emulateMedia({ colorScheme: "light" });
  await page.waitForFunction(() => document.documentElement.dataset.theme === "light");
  await page.setViewportSize({ width: 1280, height: 900 });
}
