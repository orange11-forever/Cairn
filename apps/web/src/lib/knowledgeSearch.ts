import type { KnowledgeLocator } from "../api/knowledge.ts";

export const KNOWLEDGE_SEARCH_LIMIT = 10;

export type KnowledgeQueryValidation =
  | { ok: true; query: string }
  | { ok: false; query: string; message: string };

const MEDIA_TYPE_LABELS: ReadonlyMap<string, string> = new Map([
  ["application/pdf", "PDF"],
  ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "DOCX"],
  ["application/vnd.openxmlformats-officedocument.presentationml.presentation", "PPTX"],
  ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "XLSX"],
  ["application/zip", "ZIP"],
  ["text/csv", "CSV"],
  ["text/html", "HTML"],
  ["text/markdown", "Markdown"],
  ["text/plain", "纯文本"],
]);

const API_EDGE_WHITESPACE =
  /^[\p{White_Space}\u001c-\u001f]+|[\p{White_Space}\u001c-\u001f]+$/gu;

function normalizeKnowledgeQuery(value: string): string {
  return value.normalize("NFKC").replace(API_EDGE_WHITESPACE, "");
}

export function validateKnowledgeQuery(value: string): KnowledgeQueryValidation {
  const query = normalizeKnowledgeQuery(value);
  const length = Array.from(query).length;
  if (length < 3) return { ok: false, query, message: "请输入至少 3 个字符" };
  if (length > 500) {
    return { ok: false, query, message: "搜索内容不能超过 500 个字符" };
  }
  return { ok: true, query };
}

export function formatKnowledgeMediaType(mediaType: string): string {
  return MEDIA_TYPE_LABELS.get(mediaType) ?? mediaType;
}

function lineRange(start: number, end: number): string {
  return start === end ? `第 ${start} 行` : `第 ${start}–${end} 行`;
}

function withHeadings(headingPath: readonly string[], detail?: string): string {
  const parts = [...(headingPath.length === 0 ? [] : [headingPath.join(" › ")])];
  if (detail !== undefined) parts.push(detail);
  return parts.join(" · ");
}

function assertNever(value: never): never {
  throw new Error(`未支持的知识定位类型: ${String(value)}`);
}

export function formatKnowledgeLocator(locator: KnowledgeLocator): string {
  switch (locator.type) {
    case "pdf":
      return `第 ${locator.page} 页`;
    case "docx": {
      const details = [
        locator.paragraph == null ? null : `第 ${locator.paragraph} 段`,
        locator.table == null ? null : `第 ${locator.table} 个表格`,
      ].filter((value): value is string => value !== null);
      if (locator.headingPath.length === 0 && details.length === 0) return "Word 文档";
      return withHeadings(
        locator.headingPath,
        details.length === 0 ? undefined : details.join(" · "),
      );
    }
    case "pptx":
      return `第 ${locator.slide} 张幻灯片（${locator.area === "notes" ? "演讲者备注" : "正文"}）`;
    case "xlsx":
      return `工作表「${locator.sheet}」 · ${locator.cellRange}`;
    case "csv":
      return lineRange(locator.rowStart, locator.rowEnd);
    case "html":
      return withHeadings(locator.headingPath, `第 ${locator.block} 个正文块`);
    case "text":
    case "markdown":
      return withHeadings(
        locator.headingPath ?? [],
        lineRange(locator.lineStart, locator.lineEnd),
      );
    default:
      return assertNever(locator);
  }
}
