import { describe, expect, test } from "vitest";

import type { KnowledgeLocator } from "../../src/api/knowledge.ts";
import {
  formatKnowledgeLocator,
  formatKnowledgeMediaType,
  validateKnowledgeQuery,
} from "../../src/lib/knowledgeSearch.ts";

describe("knowledge search query validation", () => {
  test.each([
    ["  ＡＢＣ  ", { ok: true, query: "ABC" }],
    ["索引边界", { ok: true, query: "索引边界" }],
    ["😀😀😀", { ok: true, query: "😀😀😀" }],
  ])("normalizes %j before validating code points", (input, expected) => {
    expect(validateKnowledgeQuery(input)).toEqual(expected);
  });

  test.each([
    ["", "请输入至少 3 个字符"],
    ["索引", "请输入至少 3 个字符"],
    ["😀😀", "请输入至少 3 个字符"],
    ["知".repeat(501), "搜索内容不能超过 500 个字符"],
  ])("rejects invalid normalized input %j", (input, message) => {
    expect(validateKnowledgeQuery(input)).toEqual({
      ok: false,
      query: input.normalize("NFKC").trim(),
      message,
    });
  });

  test("accepts exactly 500 Unicode code points", () => {
    const query = "😀".repeat(500);
    expect(validateKnowledgeQuery(query)).toEqual({ ok: true, query });
  });

  test.each([
    [500, { ok: true, query: "é".repeat(500) }],
    [
      501,
      {
        ok: false,
        query: "é".repeat(501),
        message: "搜索内容不能超过 500 个字符",
      },
    ],
  ])("validates %i code points after NFKC composition", (length, expected) => {
    expect(validateKnowledgeQuery("e\u0301".repeat(length))).toEqual(expected);
  });
});

describe("knowledge locator formatting", () => {
  const locatorCases: Array<[KnowledgeLocator, string]> = [
    [{ type: "pdf", page: 3 }, "第 3 页"],
    [
      { type: "docx", headingPath: ["运行手册", "升级"], paragraph: 4, table: null },
      "运行手册 › 升级 · 第 4 段",
    ],
    [
      { type: "docx", headingPath: [], paragraph: null, table: 2 },
      "第 2 个表格",
    ],
    [
      { type: "docx", headingPath: [], paragraph: null, table: null },
      "Word 文档",
    ],
    [{ type: "pptx", slide: 8, area: "body" }, "第 8 张幻灯片（正文）"],
    [
      { type: "pptx", slide: 8, area: "notes" },
      "第 8 张幻灯片（演讲者备注）",
    ],
    [
      { type: "xlsx", sheet: "故障清单", cellRange: "A1:C8" },
      "工作表「故障清单」 · A1:C8",
    ],
    [{ type: "csv", rowStart: 9, rowEnd: 9 }, "第 9 行"],
    [{ type: "csv", rowStart: 9, rowEnd: 14 }, "第 9–14 行"],
    [
      { type: "html", headingPath: ["部署", "回滚"], block: 2 },
      "部署 › 回滚 · 第 2 个正文块",
    ],
    [{ type: "text", headingPath: [], lineStart: 6, lineEnd: 6 }, "第 6 行"],
    [
      { type: "markdown", headingPath: ["租约"], lineStart: 6, lineEnd: 12 },
      "租约 · 第 6–12 行",
    ],
  ];

  test.each(locatorCases)("formats %o as %s", (locator, expected) => {
    expect(formatKnowledgeLocator(locator)).toBe(expected);
  });

  test.each([
    ["application/pdf", "PDF"],
    [
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "DOCX",
    ],
    [
      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      "PPTX",
    ],
    [
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "XLSX",
    ],
    ["text/csv", "CSV"],
    ["text/html", "HTML"],
    ["text/markdown", "Markdown"],
    ["text/plain", "纯文本"],
    ["application/x-cairn-unknown", "application/x-cairn-unknown"],
  ])("formats media type %s", (mediaType, expected) => {
    expect(formatKnowledgeMediaType(mediaType)).toBe(expected);
  });
});
