// 08 类型收窄
//
// 收窄 = 在某个代码分支里，编译器把一个宽类型认定为更窄的类型。
// 你写的每个 if 检查，编译器都在跟着更新它对类型的判断。

// ─── typeof ───────────────────────────────────────────────

function 描述(value: number | string): string {
  if (typeof value === "string") {
    return value.toUpperCase();   // 这里 value 是 string
  }
  return value.toFixed(2);        // 这里 value 只能是 number 了
}

console.log(描述("abc"), 描述(3.14159));

// 注意 else 分支不用写 typeof value === "number"，
// 编译器自己排除了 string —— 这叫「收窄的补集」。

// ─── Array.isArray ────────────────────────────────────────

function 计数(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  return 0;
}

console.log(计数([1, 2]), 计数("不是数组"));

// ─── instanceof ───────────────────────────────────────────

type ErrorKind = "network" | "http" | "timeout" | "aborted";

class ApiError extends Error {
  kind: ErrorKind;

  constructor(kind: ErrorKind, message: string) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
  }
}
// 字段要先声明（kind: ErrorKind），再在构造函数里赋值。
//
// TS 有个简写叫「参数属性」，能一行搞定：
//   constructor(public kind: ErrorKind, message: string) { super(message); }
//
// 但**不要用**。Node 的 strip-only 模式跑不了它，会报
// ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX —— 因为参数属性需要生成真实的赋值代码，
// 而 Node 只删类型不生成代码。
//
// 这是本日「类型编译后消失」那条原则的一个实证：凡是需要生成运行时代码的
// TS 语法（参数属性、enum、namespace），都不属于纯类型层，也都不该用。
// 项目里 api/errors.js:13-18 就是显式赋值的写法，迁移时照搬即可。

function 处理错误(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.kind}: ${error.message}`;   // 这里能点 kind
  }
  if (error instanceof Error) {
    return error.message;                       // 这里只能点 Error 的成员
  }
  return "未知错误";
}

console.log(处理错误(new ApiError("timeout", "请求超时")));
console.log(处理错误(new Error("普通错误")));
console.log(处理错误("字符串也可能被 throw"));

// 最后这行值得注意：JS 里 throw 什么都行，不一定是 Error。
// 所以 catch 到的东西类型是 unknown，必须收窄 —— 这不是 TS 多事，是 JS 的现实。

// ─── in 操作符 ─────���──────────────────────────────────────

type 有数据 = { documents: string[] };
type 有错误 = { error: string };

function 取内容(state: 有数据 | 有错误): string {
  if ("documents" in state) {
    return state.documents.join(", ");
  }
  return state.error;
}

console.log(取内容({ documents: ["甲", "乙"] }), 取内容({ error: "炸了" }));

// ─── null 检查 ────────────────────────────────────────────

function 取长度(s: string | null): number {
  // return s.length;
  // ↑ 取消注释 → 's' is possibly 'null'

  if (s === null) return 0;
  return s.length;
}

// 提前返回（early return）是最常用的收窄写法，
// 它让主逻辑不用嵌在 if 里面。

console.log(取长度("abcd"), 取长度(null));

// ─── 自定义类型守卫 ───────────────────────────────────────

function 是非空字符串(v: unknown): v is string {
  return typeof v === "string" && v.trim() !== "";
}
// 返回类型写 `v is string` 而不是 boolean，
// 编译器才会在调用处收窄。写成 boolean 就没有这个效果。

function 取标题(raw: unknown): string {
  return 是非空字符串(raw) ? raw.trim() : "未命名文档";
  //                        ↑ 这里 raw 是 string，能点 trim
}

console.log(取标题("  季度复盘  "), 取标题(""), 取标题(42));

// ─── 落点 ─────────────────────────────────────────────────
//
// apps/web/src/state/documentStore.js:44-56
//
//   } catch (error) {
//     if (error instanceof ApiError && error.kind === "aborted") { ... }
//     else { ... error instanceof ApiError ? error : new ApiError(...) }
//   }
//
// 你已经在用 instanceof 收窄了，而且用得对——先判 ApiError 再点 .kind。
// 迁到 TS 后这段几乎不用改，因为原本的写法就是类型安全的。
//
// 第 54 行 `error.message ?? "未知错误"` 有个细节：
// TS 里 catch 的 error 是 unknown，直接点 .message 会报错。
// 这段之所以在 JS 里能跑，是因为运行时碰巧 throw 的都是 Error 对象。
// Day 7 迁 state/ 时要处理这个——不是改行为，是把已经成立的假设写成检查。

// 让本文件成为模块而非全局脚本：否则九个演示文件共享全局作用域，
// 顶层声明会互相撞名，Document 还会撞上 DOM 内置的那个同名接口。
export {};
