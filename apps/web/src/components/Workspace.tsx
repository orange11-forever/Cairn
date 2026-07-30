// 登录后的工作台布局。
//
// Day 8 的 App 就是这个形状（Sidebar + main.workspace 里两块面板）。
// Day 9 加了登录门之后它整体搬到这里，让 App 继续只做一件事——
// 那条「App 里出现 useState 或 await 就说明状态提太高了」的约束仍然成立。
//
// 它自己也没有 state：user 和 onLogout 都是 props。它是纯布局组合，
// 只多了一件事——把 user 传给需要它的那一个子组件（Sidebar）。

import { AssistantPanel } from "./AssistantPanel.tsx";
import { DocumentsPanel } from "./DocumentsPanel.tsx";
import { Sidebar } from "./Sidebar.tsx";
import type { UserDto } from "../schemas/users.ts";

const NAV_ITEMS = [
  { href: "/documents", label: "知识文档" },
  { href: "/conversations", label: "问答记录" },
];

interface WorkspaceProps {
  user: UserDto;
  onLogout: () => void;
}

export function Workspace({ user, onLogout }: WorkspaceProps) {
  return (
    // Fragment 而不是包一层 div：多余的 div 会打乱 CSS 里
    // body > .product-header + .workspace 这类相邻/子选择器（Day 8 的理由，仍然成立）。
    <>
      <Sidebar
        brand="Cairn"
        items={NAV_ITEMS}
        activeHref="/documents"
        user={user}
        onLogout={onLogout}
      />
      <main className="workspace">
        <DocumentsPanel />
        <AssistantPanel />
      </main>
    </>
  );
}
