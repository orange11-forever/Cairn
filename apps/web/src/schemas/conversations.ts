// 对话与引用的 DTO。
//
// 引用（citation）是这个产品的核心资产，不是装饰。企业知识库和通用聊天机器人的
// 区别就在这里：答案必须能指回它依据的原文，用户才敢用它做决定。
// 所以 citation 的校验比 answer 文本本身更严 —— 一条指向不存在文档的引用，
// 比没有引用更坏，它让用户以为答案有依据。

import { z } from "zod";
import { IsoDateTimeSchema, NonEmptyStringSchema, ResourceIdSchema } from "./primitives.ts";

/**
 * 引用 DTO：答案里的一句话来自哪份文档的哪一段。
 *
 * documentId 必填且不给兜底：引用的全部意义就是"可以跳回去核对"。
 * 没有 documentId 的引用无法跳转，它在 UI 上是一个死链接，
 * 显示出来只会让用户以为系统在骗他。这条数据坏了应当整条丢弃。
 *
 * snippet 是原文摘录，用于在答案下方高亮显示。它必须非空 ——
 * 空摘录的引用在界面上是一个没有内容的引用块。
 */
export const CitationDtoSchema = z.object({
  documentId: ResourceIdSchema,
  documentTitle: NonEmptyStringSchema,
  snippet: NonEmptyStringSchema,

  /**
   * 文档内的定位锚点，例如 "section-4"。可选：
   * 有的来源（纯文本、图片 OCR）切不出结构化的段落编号，
   * 那时退化成"跳到文档开头"仍然可用。
   */
  anchor: NonEmptyStringSchema.optional(),

  /**
   * 检索相关度得分，0-1。可选，因为它是排序的中间产物，不是每个接口都会带。
   *
   * 用 min/max 夹住而不是裸 number：得分超出 [0,1] 说明检索层的归一化写错了，
   * 这是那种"能一路跑到 UI 上、把进度条画到屏幕外"的 bug。
   * Day 24 做混合检索（向量 + 关键词）时，两路得分融合最容易在这里出界。
   */
  score: z.number().min(0).max(1).optional(),
});

export type CitationDto = z.infer<typeof CitationDtoSchema>;

/** 消息作者。 */
export const MESSAGE_ROLES = ["user", "assistant"] as const;
export const MessageRoleSchema = z.enum(MESSAGE_ROLES);
export type MessageRole = z.infer<typeof MessageRoleSchema>;

/**
 * 消息 DTO —— 用可辨识联合建模，而不是"一个 role 字段 + 一堆可选字段"。
 *
 * 为什么值得这样写：user 消息永远没有 citations，assistant 消息永远有（可能是空数组）。
 * 若写成 `{ role, content, citations?: Citation[] }`，类型允许出现
 * "role 是 user 却带着 citations" 这种后端不会发、前端也不该处理的组合，
 * 而 UI 代码为了让编译器满意，得到处写 `msg.citations?.map(...)`。
 *
 * 用 discriminatedUnion 之后，在 `if (msg.role === "assistant")` 分支里
 * citations 是必有的，编译器自己知道，不用判空。Day 6 学的可辨识联合，
 * 这就是它在真实数据上的第一次应用。
 */
export const MessageDtoSchema = z.discriminatedUnion("role", [
  z.object({
    role: z.literal("user"),
    id: ResourceIdSchema,
    content: NonEmptyStringSchema,
    createdAt: IsoDateTimeSchema,
  }),
  z.object({
    role: z.literal("assistant"),
    id: ResourceIdSchema,
    content: NonEmptyStringSchema,
    createdAt: IsoDateTimeSchema,
    /**
     * 空数组是合法的，含义是"这个问题在知识库里没找到依据"。
     * 那种情况 UI 要显示"未在文档中找到相关内容"，而不是编一个答案 ——
     * 所以字段必须存在（能区分"没找到"和"忘了带引用"），只是可以为空。
     */
    citations: z.array(CitationDtoSchema),
  }),
]);

export type MessageDto = z.infer<typeof MessageDtoSchema>;

/** 一轮完整对话。 */
export const ConversationDtoSchema = z.object({
  id: ResourceIdSchema,
  title: NonEmptyStringSchema,
  messages: z.array(MessageDtoSchema),
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema,
});

export type ConversationDto = z.infer<typeof ConversationDtoSchema>;
