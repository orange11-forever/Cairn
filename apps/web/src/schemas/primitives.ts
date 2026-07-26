// 所有 DTO 共用的基础字段。
//
// 为什么单独一个文件：这些约束是跨资源的。"id 可以是数字或字符串" 这条规则
// 文档、用户、对话都要用；写三遍就会在第四个资源上写歪一次。
//
// Day 17 后端建 resources 表时，这里的 ResourceIdSchema 要跟着收紧成 uuid，
// 改一处而不是改五处 —— 这就是把它抽出来的回报。

import { z } from "zod";

/**
 * 资源 id。
 *
 * 为什么允许 number | string 而不直接收紧成 string：
 * 现在的 mock 后端发的是自增整数（1,2,3),Day 17 之后会换成 uuid 字符串。
 * 两者都要能过，否则今天就得改 mock、或者今天的代码到 Day 17 全废。
 *
 * 注意这里**故意不做 coerce**。z.coerce.string() 会把 null 变成 "null"、
 * 把 undefined 变成 "undefined"，两个都是 truthy 的合法字符串 ——
 * 那正好是 Day 5 那个 bug 的形状：坏数据被悄悄转成看起来合法的东西。
 * 校验层的职责是拒绝，不是打扮。
 */
export const ResourceIdSchema = z.union([z.number(), z.string()]);

/** 从 schema 反推类型。单一事实来源是 schema，类型跟着它走，不能反过来。 */
export type ResourceId = z.infer<typeof ResourceIdSchema>;

/**
 * 非空字符串。trim 之后仍非空才算。
 *
 * `"   "` 必须判为空：它在 UI 上渲染出来是一片空白，用户看到的是"这条没有标题"，
 * 而类型系统认为 string 已经满足了。这类"类型对了但语义错了"的值只能靠运行时校验挡。
 */
export const NonEmptyStringSchema = z
  .string()
  .transform((s) => s.trim())
  .refine((s) => s !== "", { message: "不能是空字符串" });

/**
 * ISO 8601 时间戳字符串，例如 "2026-07-26T10:30:00Z"。
 *
 * 为什么存字符串而不在这里 new Date()：
 * 校验层的输出应当仍是可序列化的纯数据（能 JSON.stringify、能进 localStorage、
 * 能做 deepEqual 断言）。Date 对象是带行为的活物，一旦混进 DTO，
 * "DTO 是数据快照" 这个前提就没了。要 Date 的地方在使用处转。
 *
 * 用 z.iso.datetime() 而不是 z.string()：光是 string 会让 "昨天" 这种值通过。
 */
export const IsoDateTimeSchema = z.iso.datetime();

export type IsoDateTime = z.infer<typeof IsoDateTimeSchema>;
