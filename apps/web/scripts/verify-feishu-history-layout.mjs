// Browser-only layout regression. The 50 rows and pager are synthetic DOM data;
// the page and stylesheet are real, and no Feishu or API request is made here.
import { chromium } from "playwright";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const WIDTHS = [360, 600, 768, 900, 1280];
const THEMES = ["light", "dark"];

export async function checkFeishuHistoryReachability(page) {
  const originalTheme = await page.evaluate(() => document.documentElement.dataset.theme);
  await page.evaluate(() => {
    const detail = document.querySelector(".feishu-detail");
    if (detail === null) throw new Error("Feishu source detail region is missing");
    const fixture = document.createElement("section");
    fixture.className = "feishu-sync-history";
    fixture.dataset.feishuLayoutFixture = "true";
    fixture.setAttribute("aria-label", "合成的长同步记录布局检查");
    const heading = document.createElement("div");
    heading.className = "feishu-section-heading";
    heading.innerHTML = "<h2>合成同步记录</h2>";
    const list = document.createElement("ol");
    for (let index = 0; index < 50; index += 1) {
      const row = document.createElement("li");
      row.innerHTML = `<div><strong>可检索</strong><span>手动</span></div><time>2026/9/29 12:00:${String(index).padStart(2, "0")}</time><p>合成记录 ${index + 1}，用于测试长历史末行可见性。</p>`;
      list.append(row);
    }
    const pager = document.createElement("button");
    pager.type = "button";
    pager.textContent = "加载更多记录";
    pager.dataset.feishuLayoutPager = "true";
    fixture.append(heading, list, pager);
    detail.append(fixture);
  });
  const measurements = [];
  const failures = [];
  try {
    for (const theme of THEMES) {
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 850 });
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        const result = await page.evaluate(() => {
          const fixture = document.querySelector('[data-feishu-layout-fixture="true"]');
          const row = fixture?.querySelector("li:last-child")?.getBoundingClientRect();
          const pager = fixture?.querySelector('[data-feishu-layout-pager="true"]')?.getBoundingClientRect();
          const nav = document.querySelector(".primary-nav");
          const navRect = nav?.getBoundingClientRect();
          if (!row || !pager || !nav || !navRect) throw new Error("layout fixture is incomplete");
          const fixed = getComputedStyle(nav).position === "fixed";
          const visibleBottom = fixed ? navRect.top : window.innerHeight;
          return {
            rowTop: row.top, rowBottom: row.bottom, rowHeight: row.height,
            pagerTop: pager.top, pagerBottom: pager.bottom, pagerHeight: pager.height,
            navTop: navRect.top, fixed, visibleBottom,
          };
        });
        measurements.push({ theme, width, ...result });
        if (result.rowHeight < 1 || result.pagerHeight < 44 ||
          result.rowTop < 0 || result.rowBottom > result.visibleBottom ||
          result.pagerTop < 0 || result.pagerBottom > result.visibleBottom) {
          failures.push({ theme, width, ...result });
        }
      }
    }
    if (failures.length > 0) throw new Error(`Feishu long-history row/pager obscured: ${JSON.stringify(failures)}`);
    return measurements;
  } finally {
    await page.evaluate((value) => {
      document.querySelector('[data-feishu-layout-fixture="true"]')?.remove();
      if (value === undefined) delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = value;
      window.scrollTo(0, 0);
    }, originalTheme);
  }
}

async function runOfflineFixture() {
  const stylesheet = await readFile(new URL("../styles/main.css", import.meta.url), "utf8");
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 360, height: 850 } });
    await page.setContent(`<style>${stylesheet}</style>
      <div class="app-shell"><header class="product-header">Cairn</header>
      <div class="app-layout"><nav class="primary-nav" aria-label="主导航"><ul><li><a href="#">项目</a></li><li><a href="#">资料</a></li></ul></nav>
      <main class="workspace"><section class="feishu-page"><div class="workspace-header"><h1>飞书来源</h1></div>
      <div class="feishu-layout" data-mobile-detail="true"><aside class="feishu-source-list">来源列表</aside><section class="feishu-detail" aria-label="来源详情"><h2>合成来源</h2></section></div>
      </section></main></div></div>`);
    const result = await checkFeishuHistoryReachability(page);
    console.log(JSON.stringify(result));
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await runOfflineFixture();
}
