// Geometry regression for the real shell/styles and expanded upload/list boundary.
import { chromium } from "playwright";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

export async function checkWorkbenchExplorerReachability(page) {
  const brand = await page.locator(".product-brand").boundingBox();
  if (!brand || brand.width < 44 || brand.height < 44) {
    throw new Error(`Workbench brand hit box is smaller than 44px: ${brand?.width}x${brand?.height}`);
  }
  const explorer = page.locator(".knowledge-explorer");
  if (!await explorer.isVisible()) throw new Error("Explorer must be visible for its reachability check");
  const rows = explorer.locator(".knowledge-resource-select");
  if (await rows.count() === 0) throw new Error("Explorer fixture must have resource rows");
  const measurements = [];
  for (const row of [rows.first(), rows.last()]) {
    // Trial clicks use normal browser scrolling and hit testing without opening a resource.
    await row.click({ trial: true, timeout: 1500 });
    const bounds = await row.evaluate(element => {
      const rect = element.getBoundingClientRect();
      const pane = element.closest(".knowledge-explorer").getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return { width: rect.width, height: rect.height, top: rect.top, bottom: rect.bottom,
        paneTop: pane.top, paneBottom: pane.bottom,
        reachable: hit === element || element.contains(hit) };
    });
    if (!bounds.reachable || bounds.width < 44 || bounds.height < 44 ||
      bounds.top < bounds.paneTop - 1 || bounds.bottom > bounds.paneBottom + 1) {
      throw new Error(`Explorer resource row is clipped or obscured: ${JSON.stringify(bounds)}`);
    }
    measurements.push(bounds);
  }
  return measurements;
}

async function runOfflineFixture() {
  const styles = (await Promise.all(["main.css", "workbench.css"].map(name =>
    readFile(new URL(`../styles/${name}`, import.meta.url), "utf8")))).join("\n");
  const browser = await chromium.launch();
  const failures = [];
  try {
    const page = await browser.newPage();
    for (const theme of ["light", "dark"]) for (const width of [360, 390, 768]) for (const height of [480, 640, 800]) {
      await page.setViewportSize({ width, height });
      await page.setContent(`<html data-theme="${theme}"><style>${styles}</style><body>
        <div class="app-shell"><header class="product-header"><a class="product-brand" href="#" aria-label="Cairn"><span class="cairn-brand-mark"><svg viewBox="0 0 36 36"><path d="M0 0h36v36H0z"/></svg><span>Cairn</span></span></a><div></div><div></div></header>
        <div class="app-layout"><nav class="primary-nav"><ul><li><a href="#">项目</a></li></ul></nav><main class="workspace"><section class="knowledge-page">
        <nav class="knowledge-mobile-panes"><button>资料</button><button>内容</button><button>助手</button></nav>
        <div class="knowledge-workbench"><aside class="knowledge-explorer"><div class="knowledge-explorer-heading"><h2>项目资料</h2><button>上传</button></div><p class="knowledge-explorer-project">合成项目</p>
        <div class="knowledge-explorer-upload"><section class="knowledge-upload-batch" style="height:1100px"><div class="knowledge-upload-heading">展开的合成上传批次</div><button class="secondary-action">取消上传</button></section></div>
        <section class="knowledge-resources"><div class="knowledge-resources-heading"><span>已加载4项</span></div><ul class="knowledge-resource-list">${[1, 2, 3, 4].map(index => `<li class="knowledge-resource"><button class="knowledge-resource-select"><span class="knowledge-resource-content"><span class="knowledge-resource-title-line"><strong>${index}:长资料标题${"Boundary".repeat(30)}.pdf</strong></span></span></button></li>`).join("")}</ul></section></aside></div>
        <footer class="knowledge-statusbar"><span>合成项目</span><span>可维护资料</span></footer></section></main></div></div></body></html>`);
      try { await checkWorkbenchExplorerReachability(page); }
      catch (error) { failures.push({ theme, width, height, error: error.message }); }
    }
    if (failures.length) throw new Error(JSON.stringify(failures));
    console.log("Workbench hit geometry: 18 theme/viewport cases passed");
  } finally { await browser.close(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await runOfflineFixture();
