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
   * 多路检索得分融合时尤其需要守住这个边界。
   */
  score: z.number().min(0).max(1).optional(),
});

export type CitationDto = z.infer<typeof CitationDtoSchema>;

export const GroundedAnswerDtoSchema = z.object({
  kind: z.literal("grounded_answer"),
  id: ResourceIdSchema,
  content: NonEmptyStringSchema,
  createdAt: IsoDateTimeSchema,
  citations: z.array(CitationDtoSchema).min(1),
});

export const NotFoundAnswerDtoSchema = z.object({
  kind: z.literal("not_found"),
  id: ResourceIdSchema,
  createdAt: IsoDateTimeSchema,
});

export const AskResponseSchema = z.discriminatedUnion("kind", [
  GroundedAnswerDtoSchema,
  NotFoundAnswerDtoSchema,
]);

export type GroundedAnswerDto = z.infer<typeof GroundedAnswerDtoSchema>;
export type NotFoundAnswerDto = z.infer<typeof NotFoundAnswerDtoSchema>;
export type AskResponseDto = z.infer<typeof AskResponseSchema>;
