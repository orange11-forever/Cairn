// 04 type 与 interface
//
// 描述对象形状时两者几乎等价。真正的差别只有两处，其余都是风格问题。

// ─── 两种写法 ─────────────────────────────────────────────

type 文档A = {
  id: number;
  title: string;
};

interface 文档B {
  id: number;
  title: string;
}
// 注意 interface 后面没有等号，也不用分号结尾。

const a: 文档A = { id: 1, title: "季度复盘" };
const b: 文档B = { id: 2, title: "架构评审" };

console.log(a, b);

// ─── 差别一：interface 能声明合并 ─────────────────────────

interface 可扩展 {
  id: number;
}

interface 可扩展 {
  title: string;
}
// 同名 interface 会累加，现在「可扩展」同时有 id 和 title。

const 合并结果: 可扩展 = { id: 3, title: "两次声明合起来的" };
console.log(合并结果);

// type 不行：
// type 不可扩展 = { id: number };
// type 不可扩展 = { title: string };
// ↑ 取消注释 → Duplicate identifier

// 声明合并主要用于给第三方库补类型，日常业务代码里用得不多。

// ─── 差别二：只有 type 能表达非对象类型 ───────────────────

type Phase = "idle" | "loading";           // 联合，interface 做不到
type 坐标 = [number, number];               // 元组，interface 做不到
type 可空文档 = 文档A | null;                // 同上

const p: Phase = "idle";
const 点: 坐标 = [1, 2];
const 空的: 可空文档 = null;

console.log(p, 点, 空的);

// ─── 继承/扩展 ────────────────────────────────────────────

interface 带状态文档 extends 文档B {
  status: string;
}

type 带状态文档2 = 文档A & { status: string };
// & 叫交叉类型，效果类似 extends。

const c: 带状态文档 = { id: 4, title: "x", status: "completed" };
const d: 带状态文档2 = { id: 5, title: "y", status: "failed" };

console.log(c, d);

// ─── 落点 ──────────────────��──────────────────────────────
//
// apps/web/src/lib/documents.js:14-19
//
//   /**
//    * @typedef {object} Document
//    * @property {number|string} id
//    * @property {string} title
//    * @property {"completed"|"processing"|"failed"|"unknown"} status
//    */
//
// 迁移时这个用 interface —— 它是纯对象形状，而且将来 Day 16 接真实 API 后
// 很可能要扩展字段（创建时间、大小、上传者）。
//
// 而 documentStore 里的 Phase 只能用 type，因为它是联合类型。
//
// 选择标准就这一条：能用 interface 的地方用 interface，
// 联合/元组/交叉这些 interface 表达不了的用 type。不用记更多规则。

// 让本文件成为模块而非全局脚本：否则九个演示文件共享全局作用域，
// 顶层声明会互相撞名，Document 还会撞上 DOM 内置的那个同名接口。
export {};
