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

export default defineConfig({
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
