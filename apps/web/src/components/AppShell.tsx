import type { IdentityContext } from "../api/auth.ts";
import type { ApiError } from "../api/errors.ts";
import { Link, Outlet, useLocation } from "react-router-dom";

import { AccountMenu } from "./AccountMenu.tsx";
import { MascotAssistant } from "./MascotAssistant.tsx";
import { PrimaryNavigation } from "./PrimaryNavigation.tsx";
import { ThemeControl } from "./ThemeControl.tsx";

export function AppShell({ identity, onLogout, logoutError }: { identity: IdentityContext; onLogout: () => Promise<void>; logoutError: ApiError | null }) {
  const { pathname } = useLocation();
  const page = pathname === "/ask" ? "ask" : pathname === "/projects" ? "projects" : "documents";

  return (
    <div className="app-shell">
      <header className="product-header">
        <Link className="product-brand" to="/documents">
          <img
            alt=""
            src="/assets/brand/cairn-logo.png"
            onError={(event) => {
              event.currentTarget.hidden = true;
            }}
          />
          <span>Cairn</span>
        </Link>
        <PrimaryNavigation />
        <div className="header-utilities">
          <MascotAssistant page={page} />
          <AccountMenu identity={identity} onLogout={onLogout} logoutError={logoutError} appearance={<ThemeControl />} />
        </div>
      </header>
      <main className="workspace">
        <Outlet />
      </main>
    </div>
  );
}
