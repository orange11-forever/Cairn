import { DocumentsPanel } from "../components/DocumentsPanel.tsx";
import { useSession } from "../session/SessionContext.tsx";

export function DocumentsPage() {
  const { session } = useSession();

  if (session === null) return null;

  return <DocumentsPanel userId={session.user.id} />;
}
