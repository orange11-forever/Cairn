// 文档数据的纯函数层：只做数据 → 数据的转换，不碰 DOM、不碰网络、不碰校验。
// 纯函数没有副作用、给定输入必得同样输出，所以是整个前端最容易测、也最值得测的一层。
//
// 校验属于 schemas/；这一层只处理已经可信的数据之间的变换。
//
// 为什么要分开这两件事：它们的输入假设相反。
//   校验层的输入是 unknown（来自网络，不可信），职责是"证明它是什么"。
//   本层的输入是 Document[]（已经证明过了），职责是"拿它算点什么"。
// 混在一个函数里的后果是每个函数都得自己判一遍空、判一遍类型，
// 而判过之后类型信息又传不给下一个函数，于是层层重复判空。

import type { Document, DocumentStatus } from "../schemas/documents.ts";
import { DOCUMENT_STATUSES } from "../schemas/documents.ts";

// 类型和常量都从 schema 层重新导出：调用方（UI、测试）不必知道它们定义在哪，
// 也不必为了拿一个类型去 import zod。
export type { Document, DocumentStatus, KnownStatus } from "../schemas/documents.ts";
export { DOCUMENT_STATUSES } from "../schemas/documents.ts";

const STATUS_LABELS: Record<DocumentStatus, string> = {
  completed: "已就绪",
  processing: "处理中",
  failed: "处理失败",
  unknown: "状态未知",
};

/**
 * 按状态筛选。"all" 表示不筛。
 *
 * "all" 必须显式并进联合：它是个哨兵值，不是 Document["status"] 的成员。
 * 收窄成这个联合之后，把 "completed" 拼成 "complete" 会在编译期被拦住，
 * 而 JSDoc 时代的 `@param {string} status` 只会让它静默返回空列表。
 */
export function filterByStatus(
  documents: Document[],
  status: DocumentStatus | "all",
): Document[] {
  if (status === "all") return documents;
  return documents.filter((doc) => doc.status === status);
}

/**
 * 统计各状态的数量，供侧栏角标使用。
 * 已知状态即使为 0 也要出现在结果里，否则 UI 得自己补 0。
 *
 * 返回 Record<string, number> 而不是 Record<DocumentStatus, number>：
 * key 来自数据，脏数据能造出任何 key，声明成后者就是又一次对契约撒谎。
 */
export function countByStatus(documents: Document[]): Record<string, number> {
  // null 原型：计数表的 key 来自数据，不能让 "toString" 这类名字命中 Object.prototype
  // 上继承来的成员（那会让 `?? 0` 失效，累加出一个字符串）。
  //
  // Object.create(null) 的返回类型是 any，本计划禁 any，所以显式标注。
  const counts: Record<string, number> = Object.assign(
    Object.create(null) as Record<string, number>,
    Object.fromEntries(DOCUMENT_STATUSES.map((s) => [s, 0])),
  );

  for (const doc of documents) {
    // 这里的 `?? 0` 有两个独立的理由，别把它们混成一个：
    //   运行时：null 原型保证查不到继承成员，未知 key 得到 undefined 而非函数
    //   编译期：noUncheckedIndexedAccess 让 counts[key] 的类型是 number | undefined
    // 一个防脏数据，一个防漏判空。恰好落在同一行代码上。
    counts[doc.status] = (counts[doc.status] ?? 0) + 1;
  }

  return counts;
}

/**
 * 状态 → 中文文案。UI 不该自己散落这套映射。
 *
 * 入参保持 unknown，而不是 DocumentStatus。
 *
 * 变化在于职责重新划分了。校验层（schemas/parse.ts）现在负责把不可信数据收口，
 * 所以正常路径上进来的一定是合法 DocumentStatus。但这个函数还要服务另一类调用者：
 * 绕过校验层的代码（测试、将来的 localStorage 读取、URL 查询参数）。
 *
 * 标成 DocumentStatus 的代价是兜底分支在类型上变成死代码，
 * 而运行时它仍然会被走到 —— 那正是"类型系统相信了签名的承诺"这个陷阱。
 * 一个函数如果真实契约是"任何东西进来都吐合法文案"，签名就该那么写。
 *
 * 用 Object.hasOwn 而不是 `STATUS_LABELS[status] ?? fallback`：后者查的是整条原型链，
 * status 若是 "toString"/"constructor" 这类 Object.prototype 上的名字，会拿到继承来的函数，
 * 它是 truthy，?? 兜不住，最后把一个函数塞进 UI 文案。只认自有属性就没这个洞。
 */
export function statusLabel(status: unknown): string {
  if (typeof status === "string" && Object.hasOwn(STATUS_LABELS, status)) {
    // hasOwn 是运行时检查，它不参与类型收窄，所以这里仍需断言把 string 对上索引
    return STATUS_LABELS[status as DocumentStatus];
  }
  return STATUS_LABELS.unknown;
}
