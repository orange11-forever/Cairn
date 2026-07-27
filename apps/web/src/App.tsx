// 应用根组件。只做布局组合——没有 state，没有 fetch，没有事件处理。
//
// 这条约束是 Day 8 验收「无超大页面组件」的落点。页面级组件最容易变成垃圾场：
// 一开始放一点共享状态，接着放一个 fetch，半年后它两千行、谁都不敢改。
// 保持它只有组合关系，看一眼就知道页面由哪几块拼成。
//
// 判断标准很简单：这个文件里如果出现了 useState 或 await，就说明状态或请求
// 被提得太高了，该往下推到真正需要它的那个子树。

import { AssistantPanel } from "./components/AssistantPanel.tsx";
import { DocumentsPanel } from "./components/DocumentsPanel.tsx";
import { Sidebar } from "./components/Sidebar.tsx";

const NAV_ITEMS = [
  { href: "/documents", label: "知识文档" },
  { href: "/conversations", label: "问答记录" },
];

export function App() {
  return (
    // Fragment 而不是包一层 div：多余的 div 会打乱 CSS 里
    // body > .product-header + .workspace 这类相邻/子选择器。
    // JSX 要求单一根节点，Fragment 满足它而不在 DOM 里留痕。
    <>
      <Sidebar brand="Tracebase" items={NAV_ITEMS} activeHref="/documents" />
      <main className="workspace">
        <DocumentsPanel />
        <AssistantPanel />
      </main>
    </>
  );
}
