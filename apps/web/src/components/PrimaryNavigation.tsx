import { FileText, MessageCircle } from "lucide-react";
import { NavLink } from "react-router-dom";

import { navigationItems } from "../app/navigation.ts";

export function PrimaryNavigation() {
  return (
    <nav className="primary-nav" aria-label="主导航">
      <ul>
        {navigationItems.map((item) => {
          const Icon = item.to === "/documents" ? FileText : MessageCircle;
          return (
            <li key={item.to}>
              <NavLink to={item.to} aria-label={item.label}>
                <Icon aria-hidden="true" size={18} strokeWidth={1.8} />
                <span className="nav-label-full">{item.label}</span>
                <span className="nav-label-short">{item.shortLabel}</span>
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
