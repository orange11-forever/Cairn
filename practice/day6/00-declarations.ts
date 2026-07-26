// 00 变量声明：let / const / var
//
// 这个文件回答一个问题：TypeScript 里声明变量有几种写法。
// 答案是——声明关键字有三个（let / const / var，其中 var 别用），
// 而 let 的写法只有四种，是「标不标类型」×「给不给初始值」的两两配对。

// ═══ 第一部分：let 的四种形式 ═══════════════════════════════

// 形式 1：只标类型，不给值。「我知道它是什么，但还不知道是多少」
let 计数: number;
计数 = 0; // 用之前必须先赋值，否则报错，见下面第 30 行

// 形式 2：只给值，不标类型。日常最常用的一种
let 标题 = "未命名文档";
// 编译器从初始值推断出 string。写成 let 标题: string = "..." 是噪音。

// 形式 3：两个都写。只在「推断结果不是你想要的」时才需要
let 状态: string | null = null;
状态 = "loading"; // 标注说了可以是 string，所以通过
// 状态 = 1;
// ↑ 取消注释 → 报错 TS2322: Type 'number' is not assignable to type 'string | null'.

// 形式 4：两个都不写。得到 any
// let 危险;
// 危险 = 1;
// 危险 = "然后变成字符串";
// ↑ 这三行**不报错**（哪怕 strict 开着）。这是本文件最该记住的一条。

console.log(计数, 标题, 状态);

// ─── 形式 4 的真相：evolving any（实测出来的，不是文档抄的）───
//
// 「不标类型也不给值」得到的不是「错误」，是一个会跟着赋值变型的 any。
// TS 管这叫 evolving any。它的行为跟 JS 一模一样——等于没有类型检查。
//
// 更要小心的是：`let x = null` 也走同一条路，这是 null/undefined 初始值的特殊待遇。
// 我原本以为它会推断成 null 类型、后面赋 string 会报错。实测不是：

let 演进 = null; // 看着像形式 2（给了初始值），实际是形式 4
演进 = "字符串"; // 不报错
// 演进 = 42;      // 也不报错，它已经变成 number 了
console.log(演进);

// 但它并非完全放任 —— 赋值之前就当 string 用会被拦住：
// let 空的 = null;
// console.log(空的.toUpperCase());
// ↑ 取消注释 → 报错 TS18047: '空的' is possibly 'null'.
//
// 结论：想要一个「暂时是 null，将来放 string」的变量，必须手写形式 3
// （`let x: string | null = null`）。省掉标注不是省事，是把检查一起省掉了。

// ─── 顺带记一个坑：函数参数没有形式 4 ─────────────────────
//
// 变量的隐式 any 不报错，函数参数的隐式 any **会**报错：
// function f(x) { return x; }
// ↑ 报错 TS7006: Parameter 'x' implicitly has an 'any' type.
//
// 差别的原因：参数没有初始值可推断，也没有后续赋值可演进，
// 编译器彻底无从下手，所以直接要求你标。变量至少还有「跟着赋值猜」这条退路。

// ─── 形式 1 的陷阱：用在赋值之前 ───────────────────────────

// let 未赋值: number;
// console.log(未赋值 + 1);
// ↑ 取消注释 → 报错 TS2454: Variable '未赋值' is used before being assigned.
//   这是 strict 送的检查，JS 里同样的代码只会得到 undefined 然后算出 NaN。

// ═══ 第二部分：let 和 const 的真差别 ═══════════════════════

// 差别一：能不能重新赋值。这个你已经知道。
let 可变 = 1;
可变 = 2;

const 不可变 = 1;
// 不可变 = 2;
// ↑ 取消注释 → 报错 TS2588: Cannot assign to '不可变' because it is a constant.

// 差别二（TS 特有，更重要）：推断出的类型宽度不同。
let 用let推断 = "loading";
//  ↑ 类型是 string。因为还能改，编译器只能断言到「某个字符串」

const 用const推断 = "loading";
//    ↑ 类型是字面量类型 "loading"，比 string 窄得多。
//      因为改不了，编译器可以断言得更死。

// 这个差别有实际后果：
type Phase = "idle" | "loading" | "success";

const 直接用const: Phase = 用const推断; // 通过。"loading" 是 Phase 的成员
// const 直接用let: Phase = 用let推断;
// ↑ 取消注释 → 报错。string 太宽了，它可能是 "随便什么"，编译器不敢让它进 Phase。

console.log(可变, 不可变, 用let推断, 用const推断, 直接用const);

// 要点：**默认写 const，改不了的时候才换 let**。
// 不只是「习惯好」——const 给你更窄的类型，白拿的约束力。

// ─── const 的边界：锁的是绑定，不是内容 ────────────────────

const 列表 = [1, 2];
列表.push(3); // 允许！const 只禁止 列表 = 别的数组，不禁止改数组内部
console.log(列表); // [1, 2, 3]

// 列表 = [4];
// ↑ 这个才报错。

// 想连内容一起锁，要 as const（02-arrays-objects.ts 讲）：
const 真锁住 = [1, 2] as const;
// 真锁住.push(3);
// ↑ 取消注释 → 报错：readonly 数组没有 push

// ═══ 第三部分：var —— 知道它坏在哪就行，别用 ═══════════════

// var 的作用域是函数级，不是块级。这是 JS 的历史包袱：
function 演示var(): number[] {
  const 收集: number[] = [];
  for (var i = 0; i < 3; i++) {
    // 这里的 i 属于整个函数，三次循环共享同一个 i
    收集.push(i);
  }
  // 循环结束后 i 依然可见，值是 3
  收集.push(i * 100);
  return 收集;
}

function 演示let(): number[] {
  const 收集: number[] = [];
  for (let j = 0; j < 3; j++) {
    收集.push(j); // 每轮循环一个新的 j
  }
  // 这里访问 j 会直接报错：Cannot find name 'j'
  return 收集;
}

console.log(演示var(), 演示let()); // [0,1,2,300] [0,1,2]

// var 还能重复声明同一个名字而不报错，let/const 不行：
// let 标题 = "第二次声明";
// ↑ 取消注释 → 报错 TS2451: Cannot redeclare block-scoped variable '标题'.
//   这个报错你在 07-any-vs-unknown.ts 的实验里见过。

// ═══ 第四部分：解构声明 ═════════════════════════════════════
//
// 严格说这不是第五种形式，是 let/const 的左边换成了模式。
// 但它在真实代码里出现的频率极高，你项目里就有。

const 文档 = { id: 1, title: "季度复盘", status: "completed" };

// 对象解构：按属性名取
const { id, title } = 文档;
console.log(id, title);

// 改名（因为上面 标题 已经被占用了）
const { title: 文档标题 } = 文档;
console.log(文档标题);

// 给默认值：属性不存在或为 undefined 时用它
const { 作者 = "未知" } = 文档 as { 作者?: string };
console.log(作者);

// 数组解构：按位置取
const [第一, 第二] = [10, 20];
console.log(第一, 第二);

// 解构也能标类型，但标注的是整体，不是单个变量：
const { id: 编号 }: { id: number } = 文档;
console.log(编号);

// 注意：下面这种写法是**改名**，不是标类型。新手最容易踩的一个坑。
// const { id: number } = 文档;   ← 这是把 id 改名叫 number，不是声明 id 是 number

// ─── 落点 ─────────────────────────────────────────────────
//
// 你项目里的真实例子（apps/web/src/lib/documents.ts）：
//
//   export const DOCUMENT_STATUSES = [...] as const;   ← const + as const，锁绑定也锁内容
//   const counts: Record<string, number> = Object.assign(...)  ← 形式 3，推断不出来所以手写
//   const title = typeof item.title === "string" ? ... : "未命名文档";  ← 形式 2，推断够用
//
// 以及 tests/web/documents-transform.test.mjs 里到处都是的：
//   filterByStatus(sample, 'completed').map(({ id }) => id)   ← 参数位置上的对象解构
//
// 整个文件里一个 let 都没有。这不是刻意的——纯函数层不改变量，
// 每个中间结果都是一个新的 const。用得上 let 的地方通常是循环��加器和状态标记。

export {};
