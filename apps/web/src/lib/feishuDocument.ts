const DOCUMENT_ID = /^[A-Za-z0-9]{1,128}$/;
const FEISHU_HOST = /^(?:[a-z0-9-]+\.)*feishu\.cn$/;

/** Parse locally. A pasted link is never fetched or used as a navigation target. */
export function parseFeishuDocumentId(input: string): string | null {
  const value = input.trim();
  if (DOCUMENT_ID.test(value)) return value;
  let url: URL;
  try { url = new URL(value); } catch { return null; }
  if (url.protocol !== "https:" || url.username || url.password || url.port ||
    !FEISHU_HOST.test(url.hostname) || !/^\/docx\/[A-Za-z0-9]{1,128}\/?$/.test(url.pathname)) {
    return null;
  }
  const id = url.pathname.split("/")[2];
  return id !== undefined && DOCUMENT_ID.test(id) ? id : null;
}

export const FEISHU_INTERVALS = [
  { value: "manual", label: "仅手动" },
  { value: "300", label: "每 5 分钟" },
  { value: "900", label: "每 15 分钟" },
  { value: "3600", label: "每小时" },
  { value: "86400", label: "每天" },
  { value: "604800", label: "每周" },
] as const;

export function intervalLabel(seconds: number | null): string {
  if (seconds === null) return "仅手动";
  return FEISHU_INTERVALS.find((entry) => entry.value === String(seconds))?.label ??
    `每 ${seconds} 秒`;
}
