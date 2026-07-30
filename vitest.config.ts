// Vitest 配置。Day 9 引入，只为一件事：**能在 Node 里渲染 React 组件**。
//
// 为什么不用现有的 node --test：它不认 JSX（Day 8 已实测——那是 lib/statusText.ts
// 被抽成纯 .ts 的原因之一），而且没有 DOM。给它补这两样等于自己实现半个 Vitest。
//
// 为什么不把现有 42 个测试迁过来：它们跑得好、且不需要 DOM。
// 迁移的收益是"统一工具"，成本是碰一批本来是绿的测试——
// Day 7 和 Day 8 各验证过一次同一条教训：**不要在引入新东西的同一步动既有的验证网。**
// 两个运行器并存的代价只是 package.json 里多一行。

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // 复用同一个 React 插件：测试里的 JSX 转换必须和生产构建一致，
  // 否则"测试过了但线上坏"会有一整类无法解释的原因。
  plugins: [react()],

  test: {
    // jsdom 提供 document/window。它不是真浏览器——
    // 没有布局引擎（getBoundingClientRect 全返回 0）、没有真实滚动。
    // 所以 useAutoScroll 这类依赖布局的东西**在这一层测不了**，
    // 它由 verify-web.mjs 在真 Chromium 里验证。
    // 知道每层能证明什么、不能证明什么，比测试数量重要。
    environment: "jsdom",

    // 只收 tests/react/。tests/web/ 归 node --test，两边不重叠。
    include: ["tests/react/**/*.test.tsx"],

    // 每个测试文件跑前先执行：装 jest-dom 的断言、每个测试后清理 DOM。
    setupFiles: ["tests/react/setup.ts"],

    // 默认 globals: false，所以测试文件要显式 import { test, expect }。
    // 保持显式：全局注入的 expect 让人看不出它从哪来，
    // 而这个项目里同时存在 node:assert 和 vitest 的断言，混淆的代价更高。
    globals: false,
  },
});
