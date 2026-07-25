// 07 any 与 unknown
//
// 本计划禁 any。这个文件解释为什么，以及替代品怎么用。

// ─── any：关闭检查 ────────────────────────────────────────

function 用any(raw: any) {
  return raw.随便.怎么.点;
  // 编译器完全不报错。运行时才炸。
  //
  // 更糟的是 any 会传染：这个函数的返回值也是 any，
  // 调用它的地方拿到 any，再往下传，一路失去检查。
}

// ─── unknown：我不知道这是什么，你必须先检查 ──────────────

function 用unknown(raw: unknown) {
  // return raw.length;
  // ↑ 取消注释 → 'raw' is of type 'unknown'
  //   unknown 上什么都不能做，连属性都不能点。

  if (Array.isArray(raw)) {
    return raw.length;      // 检查过了，这里编译器放行
  }
  return 0;
}

console.log(用unknown([1, 2, 3]), 用unknown("不是数组"), 用unknown(null));

// ─── 两者的关系 ───────────────────────────────────────────

// 任何值都能赋给 unknown（跟 any 一样宽）：
const u1: unknown = 42;
const u2: unknown = "字符串";
const u3: unknown = { 任意: "对象" };

// 但 unknown 不能赋给别的类型（跟 any 相反）：
// const n: number = u1;
// ↑ 取消注释 → 报错

const n: number = u1 as number;
// 用 as 断言可以强行绕过，但这是在说「我比编译器更清楚」——
// 说错了它不会救你。能用收窄就别用 as。

console.log(u1, u2, u3, n);

// ─── 为什么禁 any ─────────────────────────────────────────
//
// 写 any 的那一刻，你就退回到了纯 JavaScript，但付出了 TS 的全部成本
// （多写标注、多一个编译步骤）却拿不到收益。
//
// 真正需要「这里类型不确定」的场景，用 unknown + 收窄。
// 代价是必须写那个检查——而那个检查往往正是你本来就该写的运行时校验。

// ─── 实战：外部数据的收口 ─────────────────────────────────

interface Document {
  id: number | string;
  title: string;
  status: "completed" | "processing" | "failed" | "unknown";
}

const DOCUMENT_STATUSES = ["completed", "processing", "failed"] as const;

// 类型守卫函数：返回值写成 `参数 is 类型`，
// 编译器会在调用处据此收窄。
function 是合法状态(v: unknown): v is Document["status"] {
  return typeof v === "string"
    && (DOCUMENT_STATUSES as readonly string[]).includes(v);
}

function 收敛(raw: unknown): Document[] {
  if (!Array.isArray(raw)) {
    throw new TypeError("文档列表响应不是数组");
  }

  const 结果: Document[] = [];
  for (const item of raw) {
    // item 是 unknown（因为 raw 是 unknown[]），每个字段都要检查
    if (typeof item !== "object" || item === null) continue;
    if (!("id" in item) || item.id == null) continue;

    const 标题 = "title" in item && typeof item.title === "string"
      ? item.title.trim()
      : "";

    结果.push({
      id: item.id as number | string,
      title: 标题 !== "" ? 标题 : "未命名文档",
      status: "status" in item && 是合法状态(item.status)
        ? item.status
        : "unknown",
    });
  }
  return 结果;
}

console.log(收敛([
  { id: 1, title: "  季度复盘  ", status: "completed" },
  { id: 2, title: "", status: "什么鬼状态" },
  { title: "没有 id，会被丢弃" },
]));

// 上面这段比你现在的 JS 版本啰嗦不少。要认清这个代价的性质：
// 啰嗦出来的每一行，都是你现在靠「相信后端会返回正确格式」省掉的检查。
// 后端真的返回脏数据时，JS 版本会静默产出坏对象，这个版本不会。

// ─── 落点 ─────────────────────────────────────────────────
//
// apps/web/src/lib/documents.js:32-49
//
//   /** @param {unknown} raw */
//   export function normalizeDocuments(raw) {
//     if (!Array.isArray(raw)) throw new TypeError(...);
//     return raw.filter(...).map((item) => ({ id: item.id, ... }));
//   }
//
// 你已经把入参标成 unknown 了，也已经写了 Array.isArray 检查——方向完全对。
// 但 .map 里直接点 item.id / item.title / item.status，在 TS 里过不去，
// 因为 Array.isArray 只证明了「raw 是数组」，没证明「每个元素长什么样」。
//
// Task 4 Step 3 就是解决这个。上面给了一条路线（逐字段检查 + 类型守卫），
// 另一条是写一个 isRawDocument 守卫整体判断。两条各有取舍，明天讨论。

// 让本文件成为模块而非全局脚本：否则九个演示文件共享全局作用域，
// 顶层声明会互相撞名，Document 还会撞上 DOM 内置的那个同名接口。
export {};
