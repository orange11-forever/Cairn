// 文档资源的端点定义。
// 一个资源一个文件：调用方看到的是 fetchDocuments()，看不到 URL 和查询参数长什么样。
// Day 19 后端真正实现 /api/documents 时，改动只落在这一层。

import { request } from "./client.ts";
import { DocumentSchema, type Document } from "../schemas/documents.ts";
import { parseUniqueResourceList } from "../schemas/parse.ts";

export interface FetchDocumentsOptions {
  /** 仅 Mock 阶段使用，让后端切换返回哪种情况。 */
  scenario?: string;
  timeoutMs?: number;
  /** 外部取消信号（用户点取消、组件卸载）。 */
  signal: AbortSignal;
}

export interface FetchDocumentsResult {
  documents: Document[];
  /**
   * 被校验层丢弃的条数。往上传而不是就地咽掉：
   * UI 需要它来决定是否显示"部分数据无法显示"的提示 ——
   * 用户有权知道他看到的列表是不完整的。Day 30 还要把它上报到监控。
   */
  dropped: number;
}

/**
 * 拉取文档列表。
 *
 * 校验发生在这里，而不是更外层的 store 或 UI：
 * 这是数据**第一次**变成前端可用形状的地方，也是唯一还知道"它来自哪个接口"的地方
 *（parseList 需要 context 才能报出有用的日志）。往外一层就丢失这个信息了。
 */
export async function fetchDocuments(
  { scenario, timeoutMs, signal }: FetchDocumentsOptions,
): Promise<FetchDocumentsResult> {
  const raw = await request("/api/v1/documents", {
    query: scenario ? { scenario } : undefined,
    timeoutMs,
    signal,
  });

  // 网络边界处就把数据收进已知形状，不让脏数据流进 UI。
  //
  // 用 parseList（逐条筛）而不是 parseOrThrow（全有或全无）：
  // 一条脏数据不该让用户的整个知识库看起来是空的。判据见 schemas/parse.ts 文件头。
  const { items, dropped } = parseUniqueResourceList(
    DocumentSchema,
    raw,
    "GET /api/v1/documents",
  );

  return { documents: items, dropped };
}
