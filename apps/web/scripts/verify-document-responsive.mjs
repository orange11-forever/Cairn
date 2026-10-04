import { join } from "node:path";

export async function checkFormattedReaderResponsive({ page, expect, screenshotDir }) {
  const draft = "格式化全文阅读布局草稿";
  for (const width of [360, 768, 1280]) {
    for (const theme of ["light", "dark"]) {
      await page.setViewportSize({ width, height: 850 });
      const menu = page.locator(".account-menu");
      if (!(await menu.evaluate(element => element.open))) await menu.locator("summary").click();
      await menu.locator(`input[name="theme-preference"][value="${theme}"]`).check();
      await menu.locator("summary").click();
      await page.waitForFunction(theme => document.documentElement.dataset.theme === theme, theme);
      const maskColor = await page.evaluate(() => {
        const header = document.querySelector(".product-header");
        return header ? getComputedStyle(header).backgroundColor : getComputedStyle(document.body).backgroundColor;
      });

      if (width <= 900) await page.getByRole("button", { name: "岑宁", exact: true }).click();
      const composer = page.getByLabel("向项目知识提问", { exact: true });
      await composer.fill(draft);
      const composerGeometry = await composer.evaluate(input => {
        const bounds = input.getBoundingClientRect();
        const navigation = document.querySelector(".primary-nav")?.getBoundingClientRect();
        const bottom = navigation && navigation.width >= innerWidth - 1 && navigation.height < 150 ? navigation.top : innerHeight;
        return bounds.width >= 44 && bounds.height >= 44 && bounds.left >= 0 && bounds.right <= innerWidth &&
          bounds.top >= 0 && bounds.bottom <= bottom;
      });
      expect(composerGeometry, `真实格式化阅读 ${width}px ${theme} 的助手输入区应可用且不被导航遮挡`);
      if (width <= 900) await page.getByRole("button", { name: "内容", exact: true }).click();

      const reader = page.locator(".knowledge-document");
      await reader.locator(".knowledge-document-markdown").waitFor();
      expect(await reader.getByRole("heading", { name: "全文阅读验收", exact: true }).count() === 1,
        `真实格式化阅读 ${width}px ${theme} 保留语义标题`);
      expect(await reader.getByRole("table").count() === 1 && await reader.locator("pre code").count() === 1,
        `真实格式化阅读 ${width}px ${theme} 保留代码与表格`);
      expect(await reader.getByText("MARKDOWN_EOF_COMPLETE_20261004", { exact: true }).count() === 1,
        `真实格式化阅读 ${width}px ${theme} 包含实际 EOF 正文`);
      const layout = await reader.evaluate(element => {
        const bounds = element.getBoundingClientRect();
        const code = element.querySelector(".knowledge-document-markdown pre");
        return { overflow: document.documentElement.scrollWidth > innerWidth + 1,
          withinViewport: bounds.left >= 0 && bounds.right <= innerWidth + 1,
          localCodeScroll: code !== null && code.scrollWidth > code.clientWidth };
      });
      expect(!layout.overflow && layout.withinViewport, `真实格式化阅读 ${width}px ${theme} 不应横向溢出`);
      expect(layout.localCodeScroll, `真实格式化阅读 ${width}px ${theme} 的长代码应在代码区内滚动`);

      for (const name of ["重新读取正文", "资料详情", "复制代码", "回到引用"]) {
        const control = reader.getByRole("button", { name, exact: true });
        await control.scrollIntoViewIfNeeded();
        const geometry = await control.evaluate(button => {
          const bounds = button.getBoundingClientRect();
          const hit = document.elementFromPoint(bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
          return bounds.width >= 44 && bounds.height >= 44 && (hit === button || button.contains(hit));
        });
        expect(geometry, `真实格式化阅读 ${width}px ${theme} 的${name}须为可命中的44px控件`);
      }
      await reader.getByRole("button", { name: "回到引用", exact: true }).click();
      await page.waitForFunction(() => {
        const target = document.activeElement;
        const reader = target?.closest(".knowledge-reader-scroll");
        if (!target?.matches('.knowledge-document-body [data-citation-hit="true"]') || !reader) return false;
        const bounds = target.getBoundingClientRect(), viewport = reader.getBoundingClientRect();
        return bounds.top >= viewport.top && bounds.bottom <= viewport.bottom && window.scrollY === 0;
      });
      expect(await reader.locator('ul[data-citation-hit="true"],table[data-citation-hit="true"]').count() === 0,
        `真实格式化阅读 ${width}px ${theme} 不把未引用父集合染色`);
      await page.screenshot({ path: join(screenshotDir, `full-reader-${theme}-${width}-body.png`), fullPage: true,
        mask: [page.locator(".account-menu")], maskColor });
      await reader.getByText("MARKDOWN_EOF_COMPLETE_20261004", { exact: true }).scrollIntoViewIfNeeded();
      await reader.getByText("已到文档末尾 · 正文完整", { exact: true }).scrollIntoViewIfNeeded();
      expect(await reader.getByText("已到文档末尾 · 正文完整", { exact: true }).isVisible(),
        `真实格式化阅读 ${width}px ${theme} 保留完整正文末尾状态`);
      await page.screenshot({ path: join(screenshotDir, `full-reader-${theme}-${width}-eof.png`), fullPage: true,
        mask: [page.locator(".account-menu")], maskColor });

      if (width <= 900) await page.getByRole("button", { name: "岑宁", exact: true }).click();
      expect(await composer.inputValue() === draft, `真实格式化阅读 ${width}px ${theme} 分区切换保留未发送草稿`);
      if (width <= 900) await page.getByRole("button", { name: "内容", exact: true }).click();
    }
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByLabel("向项目知识提问", { exact: true }).fill("");
}
