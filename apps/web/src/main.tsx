// 应用入口。只做一件事：把 React 树挂到 #root 上。
//
// 和旧的 main.ts 对比就是这一天的全部收获：
//   旧版 61 行——取五个 DOM 元素、订阅 store、在回调里手动同步四处 UI、绑两个事件。
//   新版 十几行——因为"状态变了要更新哪些 DOM"不再是需要人写的指令。
// 那 61 行没有一行是错的，但每一行都是"必须记得做对"的活。

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App.tsx";
import { AppProviders } from "./app/AppProviders.tsx";

const container = document.getElementById("root");

// 同 requireElement 的理由（见旧 main.ts 的注释，那套推理在 React 下一字不变）：
// getElementById 返回 HTMLElement | null，缺元素说明 HTML 和脚本不匹配，
// 这是构建期错误，该立刻响亮地失败，而不是让页面半死不活。
if (container === null) {
  throw new Error("页面缺少必需的元素 #root：HTML 与脚本不匹配");
}

createRoot(container).render(
  // StrictMode 只在开发环境生效，生产构建里它什么都不做。
  // 它会刻意把组件渲染两次、把 effect 挂载卸载两次，用来暴露副作用写错的地方——
  // 比如在渲染期间改外部变量、或者 effect 没写清理函数。
  // 看到 console 打印两遍不是 bug，是它在替你找 bug。
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>,
);
