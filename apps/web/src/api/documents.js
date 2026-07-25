// 文档资源的端点定义。
// 一个资源一个文件：调用方看到的是 fetchDocuments()，看不到 URL 和查询参数长什么样。
// Day 19 后端真正实现 /api/documents 时，改动只落在这一层。

import { request } from "./client.js";
import { normalizeDocuments } from "../lib/documents.js";

/**
 * 拉取文档列表。
 * @param {object} [options]
 * @param {string} [options.scenario] 仅 Mock 阶段使用，让后端切换返回哪种情况
 * @param {number} [options.timeoutMs]
 * @param {AbortSignal} [options.signal]
 * @returns {Promise<import("../lib/documents.js").Document[]>}
 */
export async function fetchDocuments({ scenario, timeoutMs, signal } = {}) {
  const raw = await request("/api/docs", {
    query: scenario ? { scenario } : undefined,
    timeoutMs,
    signal,
  });

  // 网络边界处就把数据收进已知形状，不让脏数据流进 UI。
  // Day 7 这一步会换成 Zod schema 校验，职责位置不变。
  return normalizeDocuments(raw);
}
