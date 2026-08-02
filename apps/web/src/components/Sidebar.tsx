// 顶部品牌栏 + 主导航。
//
// 名字叫 Sidebar 是跟着 Day 8 大纲的措辞（"拆分侧栏"）。实际它在视觉上是顶栏——
// .product-header 用的是横向布局。名字和现实不符是将来的困惑源，
// 但改名要动 CSS 类名和大纲对照，今天不值得；Day 11 迁 Next.js 重排布局时一起处理。

import { Link, NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/documents", label: "知识文档" },
  { to: "/ask", label: "知识问答" },
] as const;

interface SidebarProps {
  /** Day 9：当前登录用户。显示身份 + 提供退出入口。 */
  user: { email: string; displayName?: string };
  onLogout: () => Promise<void>;
}

export function Sidebar({ user, onLogout }: SidebarProps) {
  return (
    <header className="product-header">
      <Link to="/documents">Cairn</Link>
      <nav aria-label="主导航">
        <ul>
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to}>{item.label}</NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/*
        Day 9：当前用户 + 退出。
        显示身份不只是装饰——用户需要能确认"我现在是谁"。
        企业环境里一个人常有多个账号（自己的 + 测试账号），
        看不到当前身份就会在错误的账号下上传文档。
      */}
      <div className="product-header-user">
        {/*
          displayName 缺失时退回 email（schemas/users.ts 里说了这是展示决策，
          不是校验决策——所以判断落在这里，不在 schema 里）。
        */}
        <span className="current-user">{user.displayName ?? user.email}</span>
        <button type="button" className="logout-btn" onClick={() => void onLogout()}>
          退出
        </button>
      </div>
    </header>
  );
}
