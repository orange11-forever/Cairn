import type { IdentityContext } from "../api/auth.ts";
import type { ApiError } from "../api/errors.ts";
import { Link, Outlet, useLocation } from "react-router-dom";

import { useSession } from "../session/SessionContext.tsx";
import { ProjectSwitcher } from "./ProjectSwitcher.tsx";
import { AccountMenu } from "./AccountMenu.tsx";
import { BrandMark } from "./BrandMark.tsx";
import { MascotAssistant } from "./MascotAssistant.tsx";
import { PrimaryNavigation } from "./PrimaryNavigation.tsx";
import { ThemeControl } from "./ThemeControl.tsx";

export function AppShell({ identity, onLogout, logoutError }: { identity: IdentityContext; onLogout: () => Promise<void>; logoutError: ApiError | null }) {
  const { pathname } = useLocation();
  const { session } = useSession();
  const projectId = pathname.match(/^\/projects\/([^/]+)/)?.[1] ?? null;
  const normalizedPathname = pathname.replace(/\/+$/, "") || "/";
  const knowledgePath = normalizedPathname.match(/^(\/projects\/[^/]+\/knowledge)(?:\/sources)?$/)?.[1] ?? null;
  const page = knowledgePath !== null
      ? "knowledge"
      : "projects";

  return (
    <div className="app-shell">
      <header className="product-header">
        <Link className="product-brand" to="/projects" aria-label="Cairn">
          <BrandMark />
        </Link>
        {session === null ? <div /> : <ProjectSwitcher key={session.generation} organizationId={identity.organization.id} projectId={projectId} sessionSignal={session.signal} />}
        <div className="header-utilities">
          {page === "knowledge" ? null : <MascotAssistant page={page} />}
          <AccountMenu identity={identity} onLogout={onLogout} logoutError={logoutError} appearance={<ThemeControl />} />
        </div>
      </header>
      <div className="app-layout">
        <PrimaryNavigation currentKnowledgePath={knowledgePath} />
        <main className="workspace">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
