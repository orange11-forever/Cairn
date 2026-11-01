import { BookOpenText, FolderKanban, Search, RefreshCw, Code2 } from "lucide-react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { navigationItems } from "../app/navigation.ts";
import { ConversationHistory } from "./knowledge/ConversationHistory.tsx";

export function PrimaryNavigation({ currentKnowledgePath = null }: { currentKnowledgePath?: string | null }) {
  const location = useLocation();
  const pathname = location.pathname.replace(/\/+$/, "") || "/";
  const projectId = pathname.match(/^\/projects\/([^/]+)\/(?:knowledge|code)/)?.[1];
  const desktop = Boolean((window as Window & { chrome?: { webview?: unknown } }).chrome?.webview);
  const searchActive = new URLSearchParams(location.search).get("view") === "search" && pathname === currentKnowledgePath;
  const icons = {
    "/projects": FolderKanban,
  } as const;
  const knowledgeLink = (view: "chat" | "search", sources = false) => {
    const params = new URLSearchParams(location.search); params.set("view", view);
    return `${currentKnowledgePath}${sources ? "/sources" : ""}?${params.toString()}`;
  };

  return (
    <nav className="primary-nav" aria-label="主导航">
      <ul>
        {navigationItems.map((item) => {
          const Icon = icons[item.to];
          return (
            <li key={item.to}>
              <NavLink to={item.to} end aria-label={item.label}>
                <Icon aria-hidden="true" size={18} strokeWidth={1.8} />
                <span className="nav-label-full">{item.label}</span>
                <span className="nav-label-short">{item.shortLabel}</span>
              </NavLink>
            </li>
          );
        })}
        {desktop && projectId && <li><NavLink to={`/projects/${projectId}/code`} aria-label="代码与架构"><Code2 aria-hidden="true" size={20} strokeWidth={1.8} /><span className="nav-label-full">代码与架构</span><span className="nav-label-short">代码</span></NavLink></li>}
        {currentKnowledgePath === null ? null : <li>
          <Link to={knowledgeLink("chat")} aria-current={pathname === currentKnowledgePath && !searchActive ? "page" : undefined} aria-label="知识工作台">
            <BookOpenText aria-hidden="true" size={18} strokeWidth={1.8} />
            <span className="nav-label-full">知识工作台</span>
            <span className="nav-label-short">工作台</span>
          </Link>
        </li>}
        {currentKnowledgePath === null ? null : <li><Link aria-current={searchActive ? "page" : undefined} to={knowledgeLink("search")} aria-label="搜索项目资料"><Search aria-hidden="true" size={22} strokeWidth={1.8} /><span className="nav-label-full">搜索资料</span><span className="nav-label-short">搜索</span></Link></li>}
        {currentKnowledgePath === null ? null : <li><NavLink to={knowledgeLink("chat", true)} aria-label="来源与同步"><RefreshCw aria-hidden="true" size={22} strokeWidth={1.8} /><span className="nav-label-full">来源与同步</span><span className="nav-label-short">来源</span></NavLink></li>}
      </ul>
      {currentKnowledgePath === null ? null : <ConversationHistory />}
    </nav>
  );
}
