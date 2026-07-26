// 后端错误响应体的 DTO。
//
// 注意这和 api/errors.ts 里的 ApiError **不是**一回事，两者容易混：
//
//   ApiErrorResponse（这里）= 后端 4xx/5xx 响应的 body 长什么样。是线上数据。
//   ApiError（api/errors.ts） = 前端内部统一的错误对象。是本地的类实例，带 retryable 等行为。
//
// 方向是：解析 body → 得到 ApiErrorResponse → 构造成 ApiError 交给 UI。
// 混成一个的后果是前端的错误分类被后端的响应格式绑死，后端换个字段名，
// UI 的所有错误判断一起改。

import { z } from "zod";

/**
 * 后端错误响应体。
 *
 * 全部字段都宽松，这是刻意的 —— 这是**错误路径**。
 * 如果解析错误响应本身也可能失败并抛错，那就会在处理错误的过程中产生新错误，
 * 用户最后看到的是一个和真实故障毫无关系的报错。错误处理路径必须比正常路径更能容错。
 *
 * 所以这里用 z.looseObject 而不是 z.object：网关、代理、框架默认错误页
 * 各自会塞不同的字段（error/detail/traceId/timestamp），剥掉它们没好处，
 * 留着至少能在控制台里看到线索。
 */
export const ApiErrorResponseSchema = z.looseObject({
  /** 给用户看的话。缺失时由前端按 HTTP 状态码兜一句，见 toUserMessage。 */
  message: z.string().optional(),

  /** 机器可读的错误码，例如 "quota_exceeded"。Day 25 映射 LLM Provider 错误时会用到。 */
  code: z.string().optional(),

  /** 链路追踪 id。用户报障时让他把这个念出来，比截图有用得多。 */
  traceId: z.string().optional(),
});

export type ApiErrorResponse = z.infer<typeof ApiErrorResponseSchema>;

/**
 * 尽力从任意响应体里挖出一句能给用户看的话。
 *
 * 入参是 unknown 而不是 ApiErrorResponse：调用它的地方恰恰是"响应体是什么都不知道"
 * 的时候（可能是 HTML 错误页、可能是空 body、可能是网关吐的纯文本）。
 * 标成 ApiErrorResponse 会要求调用方先解析成功，而解析失败正是要处理的情况之一。
 *
 * 永不抛错、永远返回字符串。这是错误路径上的函数，它自己不能成为新的失败源。
 */
export function extractErrorMessage(body: unknown, fallback: string): string {
  const parsed = ApiErrorResponseSchema.safeParse(body);
  if (parsed.success && parsed.data.message !== undefined) {
    const trimmed = parsed.data.message.trim();
    if (trimmed !== "") return trimmed;
  }
  return fallback;
}
