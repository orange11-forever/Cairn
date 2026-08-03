import { useSession } from "../session/SessionContext.tsx";
import { AppShell } from "./AppShell.tsx";

export function AuthenticatedLayout() {
  const { session, logout } = useSession();

  if (session === null) return null;

  return <AppShell user={session.user} onLogout={logout} />;
}
