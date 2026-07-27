// Vite 配置。Day 7 引入，起因是 Day 6 的一个实测结论：
//
//   浏览器加载不了 .ts。第一次探针只报 MIME 错，看起来像服务器配置问题；
//   于是把 .ts 也按 text/javascript 发一次排除干扰项——浏览器仍然炸，
//   报 `Unexpected identifier 'as'`，位置是 documents.ts 的 `as const`。
//   浏览器的 JS 解析器读不懂类型语法，MIME 配不出来。
//
// 结论：构建步骤是必需的，不是可选的。Node 能跑 .ts（strip-only）不代表浏览器能。
// 这个文件就是那个构建步骤。

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Day 8：JSX 也是浏览器读不懂的语法，和上面的 .ts 同理——
  // `<div>` 在 .tsx 里是表达式，浏览器的解析器只会看到一个小于号。
  // 插件负责把 JSX 转成 React.createElement 调用，并在 dev 下提供组件热更新。
  //
  // 版本说明：装 6.0.4 时 pnpm 报未满足的 peer（要 vite ^8，我们是 7.1.12）。
  // 降到 5.2.0，它的 peer 范围同时含 ^7 和 ^8——现在可用，将来升 vite 8 也不用再动。
  plugins: [react()],

  // 仓库是 monorepo 布局，前端不在根目录。root 指到 index.html 所在处，
  // Vite 才知道从哪找入口；node_modules 仍在仓库根，Vite 会自己往上找。
  root: "apps/web",

  server: {
    port: 5500,
    // 端口被占时直接失败，不要静默换到 5501。
    // verify-web.mjs 硬编码了 5500，静默换端口会让验证脚本连到一个空端口，
    // 报出来的错是「页面加载失败」，掩盖真正原因。
    strictPort: true,
  },

  build: {
    // 产物放 apps/web/dist（相对 root）。
    outDir: "dist",
    // 构建产物要能对照源码排错，Day 7 之后 bundle 会越来越大。
    sourcemap: true,
  },
});
