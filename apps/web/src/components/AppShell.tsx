import type { IdentityContext } from "../api/auth.ts";
import type { ApiError } from "../api/errors.ts";
import { Link, Outlet, useLocation } from "react-router-dom";

import { projectIdFromPath, projectModuleFromPath, projectPath } from "../app/projectRoutes.ts";
import { useSession } from "../session/SessionContext.tsx";
import { AccountMenu } from "./AccountMenu.tsx";
import { BrandMark } from "./BrandMark.tsx";
import { CodingOverview } from "./code/CodingOverview.tsx";
import { ProjectConversationsProvider } from "./knowledge/ProjectConversationsContext.tsx";
import { MascotAssistant } from "./MascotAssistant.tsx";
import { PrimaryNavigation } from "./PrimaryNavigation.tsx";
import { ProjectSwitcher } from "./ProjectSwitcher.tsx";
import { ProjectCommandPanel } from "./projects/ProjectCommandPanel.tsx";
import { ThemeControl } from "./ThemeControl.tsx";
import { ToastProvider } from "./toast/ToastContext.tsx";

const CREATE_ROLES = ["owner", "admin", "member"];

export function AppShell({ identity, onLogout, logoutError }: { identity: IdentityContext; onLogout: () => Promise<void>; logoutError: ApiError | null }) {
  const { pathname } = useLocation();
  const { session } = useSession();
  const projectId = projectIdFromPath(pathname);
  const module = projectModuleFromPath(pathname);
  const layout = (
    <div className="app-layout">
      <PrimaryNavigation projectId={projectId} />
      <main className="workspace"><Outlet /></main>
    </div>
  );

  return (
    <ToastProvider>
      <div className="app-shell">
        <header className="product-header">
          <Link aria-label="Cairn" className="product-brand" to={projectId === null ? "/projects" : projectPath(projectId, "tasks")}>
            <BrandMark />
          </Link>
          {session === null ? <div /> : (
            <ProjectSwitcher
              canCreateProject={CREATE_ROLES.includes(identity.membership.role)}
              key={session.generation}
              organizationId={identity.organization.id}
              projectId={projectId}
              sessionSignal={session.signal}
            />
          )}
          <div className="header-utilities">
            <CodingOverview />
            <MascotAssistant page={module ?? "tasks"}><ProjectCommandPanel projectId={projectId} /></MascotAssistant>
            <AccountMenu appearance={<ThemeControl />} identity={identity} logoutError={logoutError} onLogout={onLogout} />
          </div>
        </header>
        {module === "knowledge" && projectId !== null && session !== null ? (
          <ProjectConversationsProvider
            csrfToken={identity.csrfToken}
            generation={session.generation}
            key={`${session.generation}:${identity.user.id}:${identity.organization.id}:${projectId}`}
            organizationId={identity.organization.id}
            projectId={projectId}
            sessionSignal={session.signal}
            userId={identity.user.id}
          >{layout}</ProjectConversationsProvider>
        ) : layout}
      </div>
    </ToastProvider>
  );
}
