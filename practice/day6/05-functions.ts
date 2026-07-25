// 05 函数签名
//
// 参数必须标注（推断不出来），返回值通常可以省。

interface Document {
  id: number | string;
  title: string;
  status: "completed" | "processing" | "failed" | "unknown";
}

// ─── 参数与返回值 ─────────────────────────────────────────

function 取标题(doc: Document): string {
  return doc.title;
}

// 返回值省掉也行，编译器能从 return 推断：
function 取标题2(doc: Document) {
  return doc.title;   // 推断为 string
}

// 什么时候该显式写返回值？当你想让编译器**替你检查函数体有没有写错**时。
// 写了 : string 而函数体返回了 number，报错点在函数内部，离问题近。
// 不写的话，错误会在调用处才暴露，离问题远。

const 样例: Document = { id: 1, title: "季度复盘", status: "completed" };
console.log(取标题(样例), 取标题2(样例));

// ─── 宽签名 vs 窄签名（本文件重点）────────────────────────

type Phase = Document["status"];
// Document["status"] 是「索引访问类型」：取出那个字段的类型，
// 也就是 "completed" | "processing" | "failed" | "unknown"。
// 好处是将来 Document 改了，这里自动跟着改。

// 版本 A：宽签名，跟你现在的 JSDoc 一样
function 筛选_宽(documents: Document[], status: string): Document[] {
  if (status === "all") return documents;
  return documents.filter((doc) => doc.status === status);
}

// 版本 B：窄签名
function 筛选_窄(documents: Document[], status: Phase | "all"): Document[] {
  if (status === "all") return documents;
  return documents.filter((doc) => doc.status === status);
}

const 列表: Document[] = [
  { id: 1, title: "甲", status: "completed" },
  { id: 2, title: "乙", status: "failed" },
];

// 现在故意拼错状态名，对比两个版本的表现：

console.log(筛选_宽(列表, "complete").length);
// 编译通过，运行返回 0 —— 静默的错。你得等界面空了才发现。

// console.log(筛选_窄(列表, "complete").length);
// ↑ 取消注释 �� 编译期报错，并列出所有合法值。

console.log(筛选_窄(列表, "completed").length);   // 1

// 这就是「收窄签名」的全部价值：把一类只能靠测试或肉眼发现的错，
// 变成写代码时就被拦住的错。

// ─── 箭头函数与回调 ───────────────────────────────────────

const 计数 = (documents: Document[]): number => documents.length;

// 回调的参数一般不用标注，编译器从上下文推断：
列表.filter((doc) => doc.status === "completed");
//          ↑ doc 自动是 Document，不用写 (doc: Document)

console.log(计数(列表));

// ─── 落点 ─────────────────────────────────────────────────
//
// apps/web/src/lib/documents.js:52-61
//
//   /**
//    * @param {Document[]} documents
//    * @param {string} status        ← 这里是宽签名
//    */
//   export function filterByStatus(documents, status) { ... }
//
// 迁移时改成 Phase | "all"。注意 "all" 这个哨兵值必须显式并进联合，
// 因为它不是 Document["status"] 的成员——这个细节现在的 JSDoc 表达不出来。

// 让本文件成为模块而非全局脚本：否则九个演示文件共享全局作用域，
// 顶层声明会互相撞名，Document 还会撞上 DOM 内置的那个同名接口。
export {};
