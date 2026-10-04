import { BookOpenText, FolderKanban, Search, RefreshCw } from "lucide-react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { navigationItems } from "../app/navigation.ts";

export function PrimaryNavigation({ currentKnowledgePath = null }: { currentKnowledgePath?: string | null }) {
  const location = useLocation();
  const pathname = location.pathname.replace(/\/+$/, "") || "/";
  const searchActive = new URLSearchParams(location.search).get("view") === "search" && pathname === currentKnowledgePath;
  const icons = {
    "/projects": FolderKanban,
  } as const;

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
        {currentKnowledgePath === null ? null : <li>
          <Link to={currentKnowledgePath} aria-current={pathname === currentKnowledgePath && !searchActive ? "page" : undefined} aria-label="知识资料">
            <BookOpenText aria-hidden="true" size={18} strokeWidth={1.8} />
            <span className="nav-label-full">知识资料</span>
            <span className="nav-label-short">资料</span>
          </Link>
        </li>}
        {currentKnowledgePath === null ? null : <li><Link aria-current={searchActive ? "page" : undefined} to={`${currentKnowledgePath}?view=search`} aria-label="搜索项目资料"><Search aria-hidden="true" size={22} strokeWidth={1.8} /><span className="nav-label-short">搜索</span></Link></li>}
        {currentKnowledgePath === null ? null : <li><NavLink to={`${currentKnowledgePath}/sources`} aria-label="来源与同步"><RefreshCw aria-hidden="true" size={22} strokeWidth={1.8} /><span className="nav-label-short">来源</span></NavLink></li>}
      </ul>
    </nav>
  );
}
