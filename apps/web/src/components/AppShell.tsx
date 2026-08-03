import type { UserDto } from "@cairn/contracts";
import { Link, Outlet } from "react-router-dom";

import { AccountMenu } from "./AccountMenu.tsx";
import { PrimaryNavigation } from "./PrimaryNavigation.tsx";

export function AppShell({ user, onLogout }: { user: UserDto; onLogout: () => Promise<void> }) {
  return (
    <div className="app-shell">
      <header className="product-header">
        <Link className="product-brand" to="/documents">
          Cairn
        </Link>
        <PrimaryNavigation />
        <AccountMenu user={user} onLogout={onLogout} />
      </header>
      <main className="workspace">
        <Outlet />
      </main>
    </div>
  );
}
