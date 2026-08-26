import { useSession } from "../session/SessionContext.tsx";
import { AppShell } from "./AppShell.tsx";

export function AuthenticatedLayout() {
  const { session, logout, logoutError } = useSession();

  if (session === null) return null;

  return (
    <AppShell
      key={session.generation}
      identity={session.identity}
      onLogout={logout}
      logoutError={logoutError}
    />
  );
}
