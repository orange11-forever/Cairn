// 03 联合类型与字面量类型
//
// 这是第一个「必须手写标注、推断帮不了你」的场景。

// ─── 字面量类型：把值本身当类型 ───────────────────────────

type 加载中 = "loading";
// 这个类型只有一个合法值："loading"。别的字符串都不行。

// ─── 联合类型：用 | 把多个类型并起来 ──────────────────────

type Phase = "idle" | "loading" | "success" | "error";

let phase: Phase = "idle";
phase = "loading";

// phase = "loadng";
// ↑ 取消注释 → 报错，并且报错信息会列出四个合法值。
//   这就是为什么值得手写这个标注：拼错在编译期就死，
//   而不是等到界面上什么都不显示才发现。

console.log(phase);

// ─── 为什么推断帮不了你 ───────────────────────────────────

let 推断的 = "idle";
推断的 = "随便什么字符串";   // 合法，因为它被推断成 string

let 标注的: Phase = "idle";
// 标注的 = "随便什么字符串";   // ← 取消注释 → 报错

// 要点：推断只能从值倒推，它不知道你的业务只允许四个状态。
// 「只允许四个状态」这个知识在你脑子里，标注是把它写进代码的唯一方式。

// ─── 联合不只用于字符串 ───────────────────────────────────

type Id = number | string;

const 数字id: Id = 1;
const 字符串id: Id = "doc-001";

console.log(数字id, 字符串id, 推断的, 标注的);

// ─── 用联合类型的变量做运算要先收窄 ───────────────────────

function 打印id(id: Id): string {
  // return id.toUpperCase();
  // ↑ 取消注释 → 报错。number 上没有 toUpperCase，
  //   而 id 可能是 number，所以编译器不放行。

  if (typeof id === "string") {
    return id.toUpperCase();   // 这里安全，已经确认是 string
  }
  return String(id);
}

console.log(打印id("doc-002"), 打印id(7));

// 上面那个 if 就��「类型收窄」，08-narrowing.ts 专门讲。
// 先记住这个因果：联合类型带来了安全，代价是用之前必须先分辨清楚。

// ─── 落点 ─────────────────────────────────────────────────
//
// apps/web/src/state/documentStore.js:9
//
//   /** @typedef {"idle" | "loading" | "success" | "error"} Phase */
//
// 你已经写过这个类型了，一字不差，只是写在注释里没人校验。
// 第 12 行还得写 /** @type {Phase} */ ("idle") 来强转，TS 里不需要这层。
//
// apps/web/src/lib/documents.js:18 的 status 字段同理，
// 它是 "completed" | "processing" | "failed" | "unknown" 四个字面量的联合。

// 让本文件成为模块而非全局脚本：否则九个演示文件共享全局作用域，
// 顶层声明会互相撞名，Document 还会撞上 DOM 内置的那个同名接口。
export {};
