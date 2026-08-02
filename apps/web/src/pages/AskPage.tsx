import { AssistantPanel } from "../components/AssistantPanel.tsx";
import { useSession } from "../session/SessionContext.tsx";

export function AskPage() {
  const { session } = useSession();

  if (session === null) return null;

  return <AssistantPanel parentSignal={session.signal} />;
}
