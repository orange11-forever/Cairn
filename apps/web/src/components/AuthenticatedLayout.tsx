import { Outlet } from "react-router-dom";

import { useSession } from "../session/SessionContext.tsx";
import { Sidebar } from "./Sidebar.tsx";

export function AuthenticatedLayout() {
  const { session, logout } = useSession();

  if (session === null) return null;

  return (
    <>
      <Sidebar user={session.user} onLogout={logout} />
      <main className="workspace">
        <Outlet />
      </main>
    </>
  );
}
