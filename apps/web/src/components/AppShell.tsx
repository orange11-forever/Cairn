import type { IdentityContext } from "../api/auth.ts";
import type { ApiError } from "../api/errors.ts";
import { Link, Outlet, useLocation } from "react-router-dom";

import { AccountMenu } from "./AccountMenu.tsx";
import { BrandMark } from "./BrandMark.tsx";
import { MascotAssistant } from "./MascotAssistant.tsx";
import { PrimaryNavigation } from "./PrimaryNavigation.tsx";
import { ThemeControl } from "./ThemeControl.tsx";

export function AppShell({ identity, onLogout, logoutError }: { identity: IdentityContext; onLogout: () => Promise<void>; logoutError: ApiError | null }) {
  const { pathname } = useLocation();
  const normalizedPathname = pathname.replace(/\/+$/, "") || "/";
  const page = normalizedPathname.endsWith("/knowledge")
      ? "knowledge"
      : "projects";

  return (
    <div className="app-shell">
      <header className="product-header">
        <Link className="product-brand" to="/projects" aria-label="Cairn">
          <BrandMark />
        </Link>
        <div className="header-utilities">
          {page === "knowledge" ? null : <MascotAssistant page={page} />}
          <AccountMenu identity={identity} onLogout={onLogout} logoutError={logoutError} appearance={<ThemeControl />} />
        </div>
      </header>
      <div className="app-layout">
        <PrimaryNavigation currentKnowledgePath={page === "knowledge" ? normalizedPathname : null} />
        <main className="workspace">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
