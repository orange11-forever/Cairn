// 校验边界。今天的验收标准「错误 API 数据会被校验层拒绝」由这个文件负责。
//
// 只有两个导出，对应两种拒绝策略。选哪个是**产品决策**，不是技术偏好：
//
//   parseOrThrow  —— 全有或全无。数据坏了整个请求失败。
//                    用于单个关键对象：当前用户、一轮对话、一次上传的结果。
//
//   parseList     —— 逐条筛。坏的丢掉，好的照常返回，丢了几条要能报出来。
//                    用于列表：文档列表、搜索结果、消息历史。
//
// 判据是一句话：**用户能不能带着不完整的数据继续工作？**
//   文档列表少一行 → 能。剩下 99 个文档还是能搜、能问、能用。
//   当前用户解析失败 → 不能。不知道他是谁就不知道该给他看哪些文档，
//                     猜一个身份是安全问题，不是体验问题。

import { z } from "zod";
import { ApiError } from "../api/errors.ts";
import type { ResourceId } from "./primitives.ts";

/**
 * 严格解析：不符合 schema 就抛 ApiError("contract")。
 *
 * 抛的是 ApiError 而不是 Zod 自己的 ZodError，理由是模块边界：
 * UI 层不该 import zod。它只认 ApiError 和上面的 kind，于是"校验用哪个库"
 * 成了这一层的内部实现 —— 哪天换成 valibot 或后端下发的 JSON Schema，
 * 改动不会漏到 UI 去。这也是今天"模块边界"这个题目的实际含义：
 * 边界不是目录结构，是"哪些类型允许跨过去"。
 *
 * @param schema 目标 schema
 * @param data   来自网络的未知数据
 * @param context 出错时报给开发者的位置，例如 "GET /api/me"
 */
export function parseOrThrow<T>(
  schema: z.ZodType<T>,
  data: unknown,
  context: string,
): T {
  const result = schema.safeParse(data);

  if (!result.success) {
    // z.prettifyError 输出多行、带字段路径，例如：
    //   ✖ Invalid input: expected string, received number
    //     → at title
    // 比 JSON.stringify(issues) 好读得多，而这条消息的读者是排查故障的开发者。
    const detail = z.prettifyError(result.error);

    // console.error 而不是把 detail 塞进 message：给用户看的文案要短且无术语，
    // 完整报告留在控制台。两个受众，两条渠道。
    console.error(`[contract] ${context} 响应不符合契约：\n${detail}`);

    throw new ApiError("contract", "服务器返回的数据格式不正确，请联系管理员", {
      context,
      cause: result.error,
    });
  }

  return result.data;
}

/** parseList 的结果：解析出来的条目，加上被丢弃条目的数量。 */
export interface ParseListResult<T> {
  items: T[];
  /** 被丢弃的条数。0 表示全部通过。 */
  dropped: number;
}

/**
 * 逐条解析数组。整体不是数组则抛错，单条不合格则丢弃。
 *
 * 为什么不用 z.array(schema)：z.array 是全有或全无的（已实测），
 * 一条坏数据会让整个列表解析失败。对文档列表来说那是最坏的结果 ——
 * 一份脏数据让用户的整个知识库看起来是空的。
 *
 * 但"整体不是数组"必须抛错，不能返回 []：
 * 这说明契约整个坏了（后端改成了 {items:[...]} 分页格式而前端不知道）。
 * 静默返回 [] 会把"后端故障"显示成"你还没有文档"，是最坏的一种谎报 ——
 * 用户会以为数据丢了，而真相是前端没看懂响应。这条规则由契约测试持续保护。
 *
 * dropped 计数不是可选的诊断信息，是这个设计能成立的前提：
 * 静默丢数据的系统会让"后端某个字段改名"变成一个没人发现的慢性 bug ——
 * 列表逐渐变短却没有报错。有了计数才能在控制台和监控中发现。
 */
export function parseList<T>(
  schema: z.ZodType<T>,
  data: unknown,
  context: string,
): ParseListResult<T> {
  if (!Array.isArray(data)) {
    console.error(`[contract] ${context} 响应不是数组，实际拿到 ${describeType(data)}`);
    throw new ApiError("contract", "服务器返回的数据格式不正确，请联系管理员", {
      context,
    });
  }

  const items: T[] = [];
  const problems: string[] = [];

  for (const [index, entry] of data.entries()) {
    const result = schema.safeParse(entry);
    if (result.success) {
      items.push(result.data);
    } else {
      problems.push(`  [${index}] ${z.prettifyError(result.error).replace(/\n/g, "\n  ")}`);
    }
  }

  if (problems.length > 0) {
    // warn 而不是 error：这条路径是"降级后继续工作"，不是失败。
    // 用 error 会破坏控制台零错误约束，而这条降级警告本身仍是有价值的信号。
    console.warn(
      `[contract] ${context} 丢弃了 ${problems.length}/${data.length} 条不合格数据：\n${problems.join("\n")}`,
    );
  }

  return { items, dropped: problems.length };
}

export function parseUniqueResourceList<T extends { id: ResourceId }>(
  schema: z.ZodType<T>,
  data: unknown,
  context: string,
): ParseListResult<T> {
  const result = parseList(schema, data, context);
  const seen = new Set<ResourceId>();
  for (const item of result.items) {
    if (seen.has(item.id)) {
      console.error(`[contract] ${context} 响应包含重复资源 id：${item.id}`);
      throw new ApiError("contract", "服务器返回的数据格式不正确，请联系管理员", {
        context,
      });
    }
    seen.add(item.id);
  }
  return result;
}

/** 给人看的类型描述。typeof null === "object" 帮不上忙，数组也一样。 */
function describeType(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "数组";
  if (typeof value === "object") return `对象（键：${Object.keys(value).join(", ") || "无"}）`;
  return `${typeof value}（${JSON.stringify(value)}）`;
}
