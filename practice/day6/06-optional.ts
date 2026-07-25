// 06 可选属性与 undefined
//
// strictNullChecks（strict 的一部分）打开后，
// undefined 不再能悄悄混进任何类型 —— 这是 TS 最能防住线上崩溃的一条。

// ─── 可选属性：字段名后加 ? ───────────────────────────────

type Options = {
  scenario?: string;
};

function 加载(options: Options = {}) {
  const { scenario } = options;
  // scenario 的类型是 string | undefined，不是 string

  // return scenario.toUpperCase();
  // ↑ 取消注释 → 'scenario' is possibly 'undefined'
  //   这正是线上最常见的那类崩溃（Cannot read property of undefined），
  //   在编译期被拦下了。

  return scenario?.toUpperCase() ?? "默认场景";
}

console.log(加载({ scenario: "empty" }), 加载({}), 加载());

// ─── ?. 和 ?? 的分工 ──────────────────────────────────────

// ?. 可选链：左边是 null/undefined 就短路返回 undefined，不再往下取
// ?? 空值合并：左边是 null/undefined 才用右边

const 空对象: Options = {};
console.log(空对象.scenario?.length);          // undefined，不报错
console.log(空对象.scenario?.length ?? 0);     // 0

// 注意 ?? 和 || 不一样：
console.log(0 || 99);    // 99  —— 0 是 falsy，被替换了

// @ts-expect-error 故意演示：TS 会指出右侧不可达，因为字面量 0 永远不是 nullish
console.log(0 ?? 99);    // 0   —— 0 不是 null/undefined，保留

// 上面那行 @ts-expect-error 是本文件的附赠知识点：
// 它告诉编译器「我知道这行有错，别报」。跟 @ts-ignore 的区别是——
// 如果这行**其实没错**，@ts-expect-error 自己会报错，提醒你把注释删掉。
// 所以永远用 @ts-expect-error，不用 @ts-ignore：前者会随代码演进自动失效。
//
// 顺便，TS 能静态看出 `0 ?? 99` 没意义，是因为它知道 0 的类型是字面量 0。
// 换成一个 number | undefined 的变量就不会报了 —— 那才是 ?? 的正常用法。

// 这个区别在计数场景会咬人：用 || 会把「数量为 0」错当成「没有值」。
// 你 lib/documents.js:77 用的是 ??，是对的。

// ─── 可选属性 vs 显式 undefined ───────────────────────────

type A = { x?: number };              // x 可以不写
type B = { x: number | undefined };   // x 必须写，但可以是 undefined

const a1: A = {};                     // 合法
// const b1: B = {};                  // ← 取消注释 → 报错，x 必须出现
const b2: B = { x: undefined };       // 合法

console.log(a1, b2);

// 日常用 ? 就够。区别在于「这个字段允许缺席」和「这个字段必须表态」。

// ─── 函数参数的可选 ───────────────────────────────────────

function 问候(名字: string, 敬语?: string): string {
  return `${敬语 ?? "你好"}，${名字}`;
}

console.log(问候("小楚"), 问候("小楚", "早上好"));

// 可选参数必须放在必选参数后面：
// function 错的(敬语?: string, 名字: string) {}
// ↑ 取消注释 → A required parameter cannot follow an optional parameter

// ─── 落点 ─────────────────────────────────────────────────
//
// apps/web/src/state/documentStore.js:32-33
//
//   /** @param {{ scenario?: string }} [options] */
//   async load({ scenario } = {}) {
//
// 两层可选：options 整个可以不传（外层 []），传了的话 scenario 也可以不写（内层 ?）。
// TS 里写成 load(options: Options = {}) 就同时表达了这两层。
//
// 另外 api/client.js 里的 signal、timeout 之类的配置项大概也是可选的，
// Day 7 迁那个文件时会集中遇到。

// 让本文件成为模块而非全局脚本：否则九个演示文件共享全局作用域，
// 顶层声明会互相撞名，Document 还会撞上 DOM 内置的那个同名接口。
export {};
