// 09 可辨识联合与穷尽检查
//
// 本日最值钱的一个模式。它把「非法的状态组合」从「靠人记住别写」
// 变成「写不出来」。

interface Document {
  id: number | string;
  title: string;
}

// 字段显式声明再赋值。别用 TS 的参数属性简写（constructor(public kind: ...)）——
// Node 的 strip-only 模式跑不了，理由见 08-narrowing.ts 里的说明。
class ApiError extends Error {
  kind: "network" | "http" | "timeout";

  constructor(kind: "network" | "http" | "timeout", message: string) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
  }
}

// ─── 先看当前项目的形状有什么问题 ─────────────────────────

type 平铺的State = {
  phase: "idle" | "loading" | "success" | "error";
  documents: Document[];
  error: ApiError | null;
};

// 这个类型允许下面这些组合，它们类型上全都合法、业务上全都不该存在：

const 非法1: 平铺的State = {
  phase: "loading",
  documents: [],
  error: new ApiError("network", "加载中却带着错误？"),
};

const 非法2: 平铺的State = {
  phase: "error",
  documents: [{ id: 1, title: "出错了却有数据？" }],
  error: null,          // phase 是 error 却没有 error 对象
};

console.log(非法1.phase, 非法2.phase);

// 编译器一声不响。要防住这些，只能靠写代码的人记得——而人会忘。

// ─── 可辨识联合：把数据绑到状态上 ─────────────────────────

type State =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "success"; documents: Document[] }
  | { phase: "error"; error: ApiError };

// phase 是「辨识字段」（discriminant）：
//   - 每个分支里它都是一个确定的字面量
//   - 一旦比较过它，编译器就知道当前在哪个分支、有哪些字段

// 现在上面那两种非法组合根本写不出来：
// const 试试: State = { phase: "loading", error: new ApiError("network", "x") };
// ↑ 取消注释 → 报错，loading 分支不接受 error 字段

function 渲染(state: State): string {
  if (state.phase === "success") {
    return `${state.documents.length} 篇文档`;
    // 这里能点 documents，因为 success 分支有它
  }

  if (state.phase === "error") {
    // return state.documents;
    // ↑ 取消注释 → 报错，error 分支没有 documents 字段
    return `出错：${state.error.message}`;
  }

  return state.phase === "loading" ? "加载中…" : "待加载";
}

console.log(渲染({ phase: "idle" }));
console.log(渲染({ phase: "success", documents: [{ id: 1, title: "甲" }] }));
console.log(渲染({ phase: "error", error: new ApiError("timeout", "超时") }));

// ─── 穷尽检查：本文件的重点 ───────────────────────────────

function 文案(state: State): string {
  switch (state.phase) {
    case "idle":
      return "待加载";
    case "loading":
      return "加载中";
    case "success":
      return "已就绪";
    case "error":
      return "出错了";
    default: {
      // 四个分支都处理过了，所以走到这里的 state 类型是 never（不可能存在的类型）
      const 穷尽: never = state;
      return 穷尽;
    }
  }
}

console.log(文案({ phase: "idle" }), 文案({ phase: "loading" }));

// ─── 亲手体验：加第五个状态 ───────────────────────────────
//
// 复盘里提到 Day 21 后端可能会加 pending/running 状态。模拟一次：
//
// 第一步：把下面这行加进上面的 State 联合（第 47 行附近）
//
//     | { phase: "pending" }
//
// 第二步：跑 pnpm typecheck
//
// 预期：「文案」函数里 const 穷尽: never = state 那行报错，说
//       Type '{ phase: "pending"; }' is not assignable to type 'never'
//
//       翻译成人话：你加了一个状态，但这个 switch 没处理它。
//
// 第三步：加一个 case "pending" 让它变绿
// 第四步：把 State 里那行和新加的 case 都删回去
//
// 这四步是本日最该亲手做一遍的操作。它展示的能力是：
// **改动数据形状时，编译器把所有需要跟着改的地方全部列出来。**
// 靠人搜索、靠测试覆盖、靠 code review 都做不到这么彻底。
//
// 大多数人是在这个时刻真正被 TypeScript 说服的。

// ─── 为什么 never 能起作用 ────────────────────────────────
//
// never 表示「不可能有值的类型」。收窄到最后什么都不剩时，类型就是 never。
// 所以「能不能赋给 never」恰好等价于「是不是所有分支都已处理」。
// 这是一个借用类型系统做完备性检查的技巧，不是 never 的本意，但极其好用。

// ─── 落点 ─────────────────────────────────────────────────
//
// apps/web/src/state/documentStore.js:12
//
//   let state = { phase: "idle", documents: [], error: null };
//
// 这就是上面「平铺的State」的形状。文件头的注释写着「这里是六态」，
// 说明你心里的模型比这个类型精确——可辨识联合就是把那个模型写进代码。
//
// 注意：本日不改 documentStore.js。这是 Day 7 的活，
// 因为改它会牵动 ui/ 层（statusBar 和 documentList 都读 state），
// 一次性动三层容易失控。今天只在这个演示文件里练明白模式本身。

// 让本文件成为模块而非全局脚本：否则九个演示文件共享全局作用域，
// 顶层声明会互相撞名，Document 还会撞上 DOM 内置的那个同名接口。
export {};
