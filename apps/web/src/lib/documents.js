// 文档数据的纯函数层：只做数据 → 数据的转换，不碰 DOM、不碰网络。
// 纯函数没有副作用、给定输入必得同样输出，所以是整个前端最容易测、也最值得测的一层。

/** 后端认可的处理状态。不在这个表里的一律归为 unknown。 */
export const DOCUMENT_STATUSES = ["completed", "processing", "failed"];

const STATUS_LABELS = {
  completed: "已就绪",
  processing: "处理中",
  failed: "处理失败",
  unknown: "状态未知",
};

/**
 * @typedef {object} Document
 * @property {number|string} id
 * @property {string} title
 * @property {"completed"|"processing"|"failed"|"unknown"} status
 */

/**
 * 把后端返回的原始数组收进已知形状。这是脏数据能进入前端的最后一道关。
 *
 * 三条规则各有理由：
 * 1. 整体不是数组 → 抛错。说明 API 契约整个坏了，静默返回 [] 会把「后端故障」
 *    显示成「你还没有文档」，是最坏的一种谎报。
 * 2. 缺 id → 丢弃该条。列表渲染需要稳定 key，没 id 的条目后续无法删除/重试，
 *    留着比丢掉更危险。
 * 3. status 不认识 → 归为 unknown 而非丢弃。后端加了新状态（比如 Day 21 的
 *    pending/running）时，前端应当降级显示而不是让文档凭空消失。
 *
 * @param {unknown} raw
 * @returns {Document[]}
 */
export function normalizeDocuments(raw) {
  if (!Array.isArray(raw)) {
    throw new TypeError("文档列表响应不是数组");
  }

  return raw
    .filter((item) => item != null && item.id != null)
    .map((item) => ({
      id: item.id,
      // 标题缺失不影响功能，给占位符即可，不值得丢弃整条
      title: typeof item.title === "string" && item.title.trim() !== ""
        ? item.title.trim()
        : "未命名文档",
      status: DOCUMENT_STATUSES.includes(item.status) ? item.status : "unknown",
    }));
}

/**
 * 按状态筛选。"all" 表示不筛。
 * @param {Document[]} documents
 * @param {string} status
 * @returns {Document[]}
 */
export function filterByStatus(documents, status) {
  if (status === "all") return documents;
  return documents.filter((doc) => doc.status === status);
}

/**
 * 统计各状态的数量，供侧栏角标使用。
 * 已知状态即使为 0 也要出现在结果里，否则 UI 得自己补 0。
 * @param {Document[]} documents
 * @returns {Record<string, number>}
 */
export function countByStatus(documents) {
  // null 原型：计数表的 key 来自数据，不能让 "toString" 这类名字命中 Object.prototype
  // 上继承来的成员（那会让 `?? 0` 失效，累加出一个字符串）。
  const counts = Object.assign(
    Object.create(null),
    Object.fromEntries(DOCUMENT_STATUSES.map((s) => [s, 0])),
  );
  for (const doc of documents) {
    counts[doc.status] = (counts[doc.status] ?? 0) + 1;
  }
  return counts;
}

/**
 * 状态 → 中文文案。UI 不该自己散落这套映射。
 *
 * 用 Object.hasOwn 而不是直接 `STATUS_LABELS[status] ?? fallback`：后者查的是整条原型链，
 * status 若是 "toString"/"constructor" 这类 Object.prototype 上的名字，会拿到继承来的函数，
 * 它是 truthy，?? 兜不住，最后把一个函数塞进 UI 文案。只认自有属性就没这个洞。
 */
export function statusLabel(status) {
  return Object.hasOwn(STATUS_LABELS, status)
    ? STATUS_LABELS[status]
    : STATUS_LABELS.unknown;
}
