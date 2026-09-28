import { BookOpenText, FolderKanban } from "lucide-react";
import { NavLink } from "react-router-dom";

import { navigationItems } from "../app/navigation.ts";

export function PrimaryNavigation({ currentKnowledgePath = null }: { currentKnowledgePath?: string | null }) {
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
          <NavLink to={currentKnowledgePath} aria-label="知识资料">
            <BookOpenText aria-hidden="true" size={18} strokeWidth={1.8} />
            <span className="nav-label-full">知识资料</span>
            <span className="nav-label-short">资料</span>
          </NavLink>
        </li>}
      </ul>
    </nav>
  );
}
