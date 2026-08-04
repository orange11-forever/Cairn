import { join } from "node:path";

const VIEWPORTS = [
  { name: "mobile", width: 360, height: 800 },
  { name: "tablet", width: 768, height: 900 },
  { name: "desktop", width: 1280, height: 900 },
];

async function chooseTheme(page, label) {
  const menu = page.locator(".account-menu");
  if (!(await menu.getAttribute("open"))) await menu.locator("summary").click();
  await menu.getByRole("radio", { name: label }).check();
  await menu.locator("summary").click();
}

async function readLayout(page) {
  return page.evaluate(() => {
    const nav = document.querySelector(".primary-nav");
    const workspace = document.querySelector("main.workspace");
    const panel = document.querySelector(".documents-panel, .assistant-panel");
    const navRect = nav?.getBoundingClientRect();
    const workspaceStyle = workspace === null ? null : getComputedStyle(workspace);

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
      undersizedTargets: [
        ...document.querySelectorAll(
          ".product-brand, .primary-nav a, .account-menu summary, button, select, input:not([type='radio']):not([type='checkbox'])",
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

async function readAssistantContentLayout(page) {
  return page.evaluate(() => {
    const image = document.querySelector(
      ".mascot-assistant-body .mascot-art > img, .mascot-assistant-body .mascot-image-fallback",
    );
    const copy = document.querySelector(".mascot-assistant-body > p");
    const imageRect = image?.getBoundingClientRect();
    const copyRect = copy?.getBoundingClientRect();
    return {
      imageRight: imageRect?.right ?? null,
      copyLeft: copyRect?.left ?? null,
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
    (image) => image.alt?.includes("看板娘") || image.alt?.includes("助手"),
  );
  expect(mascots.length > 0, `${context} 应渲染看板娘缩略图`);
  for (const mascot of mascots) {
    expect(
      mascot.currentSrc.endsWith("/cairn-mascot-avatar.png"),
      `${context} 应使用缩略图，实际为 ${mascot.currentSrc}`,
    );
    expect(
      mascot.naturalWidth === 256 && mascot.naturalHeight === 256,
      `${context} 缩略图尺寸错误：${mascot.naturalWidth}x${mascot.naturalHeight}`,
    );
    expect(mascot.cornerAlpha === 0, `${context} 缩略图圆角外必须透明`);
  }
}

function expectLoginMascot(images, viewport, expect) {
  const mascot = images.find((image) => image.alt === "Cairn 看板娘");
  const expectedAsset = viewport.width < 600
    ? "/cairn-mascot-avatar.png"
    : "/cairn-mascot.png";
  expect(
    mascot?.currentSrc.endsWith(expectedAsset),
    `${viewport.name} 登录页素材选择错误：${mascot?.currentSrc ?? "未渲染"}`,
  );
}

export async function checkResponsiveFoundation({ page, expect, screenshotDir, login, logout }) {
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
        documents.undersizedTargets.length === 0,
        `${viewport.name} 文档页存在小于 44px 的交互目标：${documents.undersizedTargets.join(" / ")}`,
      );
      expect(
        await page.getByRole("button", { name: "打开看板娘助手" }).isVisible(),
        `${viewport.name} 看板娘助手入口不可见`,
      );
      const documentImages = await readImageHealth(page);
      expectHealthyImages(documentImages, expect, `${viewport.name} 文档页`);
      expectThumbnailMascots(documentImages, expect, `${viewport.name} 文档页`);

      await page.screenshot({
        path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}-documents.png`),
        fullPage: true,
      });

      const assistantTrigger = page.getByRole("button", { name: "打开看板娘助手" });
      await assistantTrigger.click();
      expect(
        await page.getByRole("dialog", { name: "看板娘助手" }).isVisible(),
        `${viewport.name} 看板娘助手面板未打开`,
      );
      const assistantLayout = await readAssistantContentLayout(page);
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
        !(await page.getByRole("dialog", { name: "看板娘助手" }).isVisible()),
        `${viewport.name} Escape 后看板娘助手仍可见`,
      );
      expect(
        await assistantTrigger.evaluate((element) => document.activeElement === element),
        `${viewport.name} Escape 后焦点应返回助手入口`,
      );

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
      const loginImages = await readImageHealth(page);
      expectHealthyImages(loginImages, expect, `${viewport.name} 登录页`);
      expectLoginMascot(loginImages, viewport, expect);
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
  expect(
    (await page.locator("html").getAttribute("data-theme")) === "light",
    "手动日间主题应在刷新后保留",
  );
  await login();

  await chooseTheme(page, "跟随系统");
  expect(
    (await page.evaluate(() => localStorage.getItem("cairn-theme"))) === null,
    "跟随系统应清除本地覆盖",
  );
  await page.emulateMedia({ colorScheme: "light" });
  await page.waitForFunction(() => document.documentElement.dataset.theme === "light");
  await page.setViewportSize({ width: 1280, height: 900 });
}
