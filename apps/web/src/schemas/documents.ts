// 文档资源的 DTO 与校验 schema。
//
// 这个文件里有**两套**文档形状，区别是今天最重要的一个概念：
//
//   DocumentDtoSchema  = 契约。一个正确的后端应该发什么。status 只有三种。
//   Document（领域模型）= 前端实际用什么。status 有四种，多出来的 "unknown"
//                        后端永远不会发 —— 它是前端自己造的降级值。
//
// 为什么不合成一个：合成一个就必须选一边。
//   选宽的（含 unknown）→ 契约文档撒谎，看代码的人会以为后端可能发 unknown，
//                        于是在后端代码里也去处理这个值，白写。
//   选窄的（不含 unknown）→ 前端的兜底分支在类型上成了死代码，而运行时天天走到
//                        （Day 6 交接里那个未决问题就是这个形状）。
// 两个类型各自诚实，中间用一个显式的转换函数连接，那个函数就是边界。

import { z } from "zod";
import { ResourceIdSchema } from "./primitives.ts";

/**
 * 后端认可的处理状态。
 *
 * 从 Day 6 的 `DOCUMENT_STATUSES as const` 搬到这里，因为它现在是**契约的一部分**，
 * 而不只是前端的一个常量。数组仍然导出：UI 要遍历它渲染筛选器和角标。
 */
export const DOCUMENT_STATUSES = ["completed", "processing", "failed"] as const;

/** 后端会发的状态。 */
export const KnownStatusSchema = z.enum(DOCUMENT_STATUSES);
export type KnownStatus = z.infer<typeof KnownStatusSchema>;

/**
 * 前端会拿到的状态：后端三种 + 本层兜底出来的 unknown。
 *
 * 注意这是个**领域**枚举，不是契约的一部分 —— "unknown" 是前端造的，
 * 后端永远不会发它。它出现在这里是因为前端各层之间要传这个值。
 */
export const DocumentStatusSchema = z.enum([...DOCUMENT_STATUSES, "unknown"]);
export type DocumentStatus = z.infer<typeof DocumentStatusSchema>;

/**
 * 文档 DTO —— 严格契约版。
 *
 * 这个 schema 的用途不是日常解析（日常解析用下面宽松的那套），而是：
 * 1. 当文档：读代码的人想知道"后端到底发什么"，看这里，不用去翻后端仓库。
 * 2. Day 19 后端实现 /api/documents 时，拿它当验收断言，检测契约漂移。
 *
 * 严格在两处：status 必须是三种之一（不降级），title 必须非空（不给占位符）。
 */
export const DocumentDtoSchema = z.object({
  id: ResourceIdSchema,
  title: z.string().min(1),
  status: KnownStatusSchema,
});

export type DocumentDto = z.infer<typeof DocumentDtoSchema>;

/**
 * 标题的宽松解析：坏标题不该让整条文档消失。
 *
 * 理由是产品性的，不是技术性的：标题只影响显示。一个没标题的文档，用户仍然需要
 * 能看到它、能点它、能删掉它。为了一个显示字段丢掉整条记录，是拿用户的数据
 * 去惩罚后端的 bug。
 *
 * 用 z.unknown() 起头而不是 z.string()：非字符串（42、null）也要走到占位符，
 * 如果起手是 z.string()，它们会先在类型检查上失败，transform 根本不会执行。
 */
const LenientTitleSchema = z.unknown().transform((value) => {
  if (typeof value === "string" && value.trim() !== "") return value.trim();
  return "未命名文档";
});

/**
 * 状态的宽松解析：不认识的状态降级成 unknown，而不是丢弃文档。
 *
 * `.catch()` 的语义是"解析失败就用这个值"，它同时覆盖了三种情况：
 *   status: "pending"（后端加了新状态）、status: null（脏数据）、
 *   status 字段整个缺失（catch 对 undefined 也生效，已实测）。
 *
 * 这条降级路径是有产品理由的：Day 21 后端会加 pending/running 状态。
 * 那天后端先上线、前端后上线的窗口期里，前端必须还能显示文档列表 ——
 * 而不是让用户看到一个空列表，以为文档都没了。
 *
 * 建在 DocumentStatusSchema（含 unknown）上而不是 KnownStatusSchema 上：
 * 后者 catch 出来的类型推不出 "unknown"，得靠 `as never` 硬掰，
 * 那个断言正是"类型没建模对"的信号。让兜底值本来就属于目标枚举，就不用掰。
 */
const LenientStatusSchema = DocumentStatusSchema.catch("unknown");

/**
 * 领域模型 schema：前端各层之间流动的文档形状。
 *
 * 注意 z.object() 默认**剥离**未声明的字段（已实测）。这不是副作用而是要的：
 * 后端多塞的字段不该漏进 UI 层，否则某天有人开始用一个没进过契约的字段，
 * 而后端并不知道前端在依赖它。
 */
export const DocumentSchema = z.object({
  id: ResourceIdSchema,
  title: LenientTitleSchema,
  status: LenientStatusSchema,
});

/**
 * 前端内部流通的文档类型。
 *
 * 用 z.infer 而不是手写 interface：手写就有两份真相，schema 改了类型不改，
 * 编译器不会提醒（它俩没有任何关联）。让类型从 schema 派生，schema 是唯一事实来源。
 */
export type Document = z.infer<typeof DocumentSchema>;
