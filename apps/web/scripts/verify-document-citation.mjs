import { join } from "node:path";

export async function checkLongMarkdownCitationBlocks({ page, webOrigin, projectId, expect, screenshotDir }) {
  const fixtures = [
    { fileName: "preview-长列表.md", phrase: "清岚列表末段引用定位验收", tag: "LI", ancestor: "ul",
      content: Array.from({ length: 500 }, (_, index) => `- ${index === 499 ? "清岚列表末段引用定位验收" : `list item ${index + 1}`}`).join("\n") + "\n\nLIST_EOF_COMPLETE\n" },
    { fileName: "preview-长表格.md", phrase: "澄湾表格末段引用定位验收", tag: "TR", ancestor: "table",
      content: ["| Item | Status |", "| --- | --- |", ...Array.from({ length: 300 }, (_, index) => `| ${index === 299 ? "澄湾表格末段引用定位验收" : `table row ${index + 1}`} | ready |`)].join("\n") + "\n\nTABLE_EOF_COMPLETE\n" },
  ];
  for (const fixture of fixtures) {
    await page.goto(`${webOrigin}/projects/${projectId}/knowledge`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "上传资料" }).click();
    await page.getByLabel("上传知识资料", { exact: true }).setInputFiles({
      name: fixture.fileName, mimeType: "text/markdown", buffer: Buffer.from(fixture.content, "utf8"),
    });
    await page.getByRole("button", { name: "开始上传" }).click();
    await page.locator('.knowledge-upload-file[data-phase="ready"]').waitFor({ timeout: 120_000 });
    await page.getByLabel("搜索项目知识", { exact: true }).fill(fixture.phrase);
    await page.getByRole("button", { name: "搜索项目知识", exact: true }).click();
    const result = page.getByRole("region", { name: "项目知识检索" }).locator(".knowledge-search-result")
      .filter({ hasText: fixture.fileName }).first();
    await result.waitFor({ timeout: 30_000 });
    const [response] = await Promise.all([
      page.waitForResponse(response => response.request().method() === "GET" &&
        /\/knowledge\/resources\/[^/]+\/content\?/.test(response.url()) && new URL(response.url()).searchParams.has("chunk_id")),
      result.getByRole("button", { name: "查看引用上下文" }).click(),
    ]);
    expect(response.status() === 200, "长文引用应通过真实完整正文接口授权");
    const full = await response.json();
    expect(full.content === fixture.content, "长文应保持完整 EOF 原文");
    expect(full.highlight?.lineStart > 150, "引用应落在长集合后段的可信行范围");
    const cited = page.locator(`.knowledge-document-body ${fixture.tag.toLowerCase()}[data-line-start="${full.highlight.lineStart}"][data-citation-hit="true"]`).first();
    await cited.waitFor();
    await page.waitForFunction(({ tag, line }) => document.activeElement?.tagName === tag &&
      document.activeElement?.getAttribute("data-line-start") === String(line), { tag: fixture.tag, line: full.highlight.lineStart });
    const readLocation = () => cited.evaluate(node => {
      const reader = node.closest(".knowledge-reader-scroll");
      const bounds = node.getBoundingClientRect();
      const viewport = reader?.getBoundingClientRect();
      return { visible: viewport !== undefined && bounds.top >= viewport.top && bounds.bottom <= viewport.bottom,
        focused: node === document.activeElement, bodyScroll: window.scrollY, readerScroll: reader?.scrollTop ?? 0 };
    });
    const automatic = await readLocation();
    expect(automatic.focused && automatic.visible, "自动定位应聚焦并显示真实引用行，不能聚焦巨大父容器");
    expect(automatic.readerScroll > 0 && automatic.bodyScroll === 0, "引用定位应只滚动阅读区");
    expect(await page.locator(`.knowledge-document-body ${fixture.ancestor}[data-citation-hit="true"]`).count() === 0,
      "引用高亮不能覆盖未引用的集合父容器");
    await page.locator(".knowledge-reader-scroll").evaluate(reader => { reader.scrollTop = 0; });
    await page.getByRole("button", { name: "回到引用", exact: true }).click();
    const returned = await readLocation();
    expect(returned.focused && returned.visible && returned.bodyScroll === 0,
      "回到引用应恢复实际引用行的焦点与阅读区可见性");
    await page.screenshot({ path: join(screenshotDir, `${fixture.tag === "LI" ? "long-list" : "long-table"}-citation-visible.png`), fullPage: true });
  }
}
