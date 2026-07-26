# Day 6 TypeScript 语法演示

九个可以单独跑、可以随便改的文件。每个文件对应一个语法点，末尾都指出它在 `apps/web/src/` 里的落点。

Node 22 原生支持剥离类型，所以直接跑就行，不用先编译：

```bash
node practice/day6/01-annotations.ts
```

想看类型检查的结果（跑得起来不代表类型对）：

```bash
pnpm typecheck
```

两者的区别是本日第一个要建立的认知：**`node` 只剥离类型不检查，`tsc` 只检查不运行**。

## 文件顺序

```
00-declarations.ts         let / const / var 与解构声明
01-annotations.ts          基础标注与类型推断
02-arrays-objects.ts       数组与对象形状
03-unions.ts               联合类型与字面量类型
04-type-vs-interface.ts    两种声明方式的取舍
05-functions.ts            参数与返回值签名
06-optional.ts             可选属性与 undefined
07-any-vs-unknown.ts       为什么本计划禁 any
08-narrowing.ts            类型收窄的三种手段
09-discriminated-union.ts  可辨识联合与穷尽检查
```

前七个是标注语法，后两个是 TS 真正值钱的地方。

## 怎么用

每个文件里都有被注释掉的错误行，长这样：

```ts
// phase = "loadng";   // ← 取消注释，跑 pnpm typecheck 看报错
```

**一定要真的取消注释跑一遍**。读一百遍正确写法不如亲眼看一次报错信息——将来你遇到的报错就是这些。看完再注释回去。

## 与项目代码的对应关系

| 演示文件 | 项目里的落点 |
|---|---|
| 03-unions | `state/documentStore.js:9` 的 `Phase` typedef |
| 04-type-vs-interface | `lib/documents.js:14-19` 的 `Document` typedef |
| 05-functions | `lib/documents.js:58` 的 `filterByStatus` |
| 06-optional | `state/documentStore.js:32` 的 `scenario?` |
| 07-any-vs-unknown | `lib/documents.js:32` 的 `@param {unknown} raw` |
| 08-narrowing | `state/documentStore.js:46` 的 `instanceof ApiError` |
| 09-discriminated-union | `state/documentStore.js:12` 的 state 形状（Day 7 才改） |

这张表说明一件事：**你已经在写类型了**，只是写在 JSDoc 注释里，没有任何工具替你校验。
