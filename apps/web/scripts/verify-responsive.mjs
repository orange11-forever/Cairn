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
        .map((element) => element.getAttribute("aria-label") ?? element.textContent.trim()),
    };
  });
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
      expect(documents.activeLabel?.includes("文档"), `${viewport.name} 文档导航未激活`);
      expect(
        documents.undersizedTargets.length === 0,
        `${viewport.name} 文档页存在小于 44px 的交互目标：${documents.undersizedTargets.join(" / ")}`,
      );

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

      await page.screenshot({
        path: join(screenshotDir, `responsive-${viewport.name}-${themeValue}.png`),
        fullPage: true,
      });
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
