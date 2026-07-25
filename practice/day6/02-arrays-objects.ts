// 02 数组与对象形状

// ─── 数组 ─────────────────────────────────────────────────

const 状态列表: string[] = ["completed", "processing", "failed"];

// 另一种等价写法，读起来不如上面直观，但在泛型里会见到：
const 页数列表: Array<number> = [1, 2, 3];

// ─── as const：本文件最重要的一点 ─────────────────────────

const 宽松 = ["completed", "processing", "failed"];
// 推断结果：string[]
// 意味着 宽松.push("随便什么") 是合法的，也意味着它约束不了任何东西。

const 收紧 = ["completed", "processing", "failed"] as const;
// 推断结果：readonly ["completed", "processing", "failed"]
// 现在它是三个确定的字面量，只读，不能 push。

// 收紧.push("pending");
// ↑ 取消注释 → 报错，readonly 数组没有 push

console.log(状态列表, 页数列表, 宽松, 收紧);

// ─── 对象形状 ─────────────────────────────────────────────

const 文档: { id: number; title: string } = {
  id: 1,
  title: "季度复盘.md",
};

// 注意分号：对象类型里字段用 ; 分隔（也能用 ,），跟对象字面量的 , 是两码事。

// ─── 亲手制造报错 ─────────────────────────────────────────

// const 缺字段: { id: number; title: string } = { id: 2 };
// ↑ 取消注释 → Property 'title' is missing

// const 多字段: { id: number } = { id: 3, title: "多余的" };
// ↑ 取消注释 → 报错。字面量直接赋值时，多余属性会被拒绝（叫「多余属性检查」）。
//   但如果先赋给变量再传，就不报了——这个不一致是 TS 的已知设计取舍，
//   知道有这回事就行，别在上面纠结。

console.log(文档);

// ─── 落点 ─────────────────────────────────────────────────
//
// apps/web/src/lib/documents.js:5
//
//   export const DOCUMENT_STATUSES = ["completed", "processing", "failed"];
//
// 迁移时要加 as const。不加的话它的类型是 string[]，
// 无法用来约束 Document 的 status 字段，那这个常量就白定义了。
//
// 加了之后会撞上一个报错（第 48 行的 includes 调用），那是 Task 4 的练习题。

// 让本文件成为模块而非全局脚本：否则九个演示文件共享全局作用域，
// 顶层声明会互相撞名，Document 还会撞上 DOM 内置的那个同名接口。
export {};
