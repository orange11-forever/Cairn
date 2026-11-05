import { Navigate, Outlet, Route, Routes, useNavigate, useSearchParams } from "react-router-dom";
import type { IdentityContext } from "../api/auth.ts";

import { AuthenticatedLayout } from "../components/AuthenticatedLayout.tsx";
import { RegistrationForm } from "../components/RegistrationForm.tsx";
import { LoginForm } from "../components/LoginForm.tsx";
import { OAuthFinalize } from "../components/OAuthFinalize.tsx";
import { TopoBackground } from "../components/trail/TopoBackground.tsx";
import { StartupIntro } from "../components/StartupIntro.tsx";
import { KnowledgePage } from "../pages/KnowledgePage.tsx";
import { KnowledgeSourcesPage } from "../pages/KnowledgeSourcesPage.tsx";
import { AccountIdentitiesPage } from "../pages/AccountIdentitiesPage.tsx";
import { ProjectCreatePage, ProjectTasksPage, ProjectsPage } from "../pages/ProjectsPage.tsx";
import { CodeWorkspacePage } from "../pages/CodeWorkspacePage.tsx";
import { useSession } from "../session/SessionContext.tsx";

function LoginRoute() {
  const { status, establishSession } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  if (status === "authenticated") return <Navigate to="/projects" replace />;

  function handleSuccess(identity: IdentityContext) {
    establishSession(identity);
    navigate("/projects", { replace: true });
  }

  if (params.get("oauth") === "login_ready") return <OAuthFinalize onSuccess={handleSuccess} />;

  return <LoginForm onSuccess={handleSuccess} oauthOutcome={params.get("oauth")} />;
}

function RequireSession() {
  const { status } = useSession();

  return status === "anonymous" ? <Navigate to="/login" replace /> : <Outlet />;
}

function FallbackRoute() {
  const { status } = useSession();

  return <Navigate to={status === "anonymous" ? "/login" : "/projects"} replace />;
}

function SessionRoutes() {
  const { status, restoreError, retryRestore, restartLogin } = useSession();
  return <StartupIntro restoring={status === "restoring"}>
    {status === "restore-error" ? (
      <main className="session-status-page">
        <TopoBackground variant="scene" />
        <div className="session-restore-error">
          <p className="form-error" role="alert">
            {restoreError?.message ?? "暂时无法恢复会话，请重试"}
          </p>
          <button type="button" className="retry-btn" onClick={retryRestore}>
            重试
          </button>
          {restoreError?.code === "session_changed" && <button type="button" className="retry-btn" onClick={() => void restartLogin()}>重新开始登录</button>}
        </div>
      </main>
    ) : (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route element={<RequireSession />}>
        <Route element={<AuthenticatedLayout />}>
          <Route path="/account/identities" element={<AccountIdentitiesPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/new" element={<ProjectCreatePage />} />
          <Route path="/projects/:projectId/tasks" element={<ProjectTasksPage />} />
          <Route path="/projects/:projectId/code" element={<CodeWorkspacePage />} />
          <Route path="/projects/:projectId/knowledge" element={<KnowledgePage />} />
          <Route path="/projects/:projectId/knowledge/sources" element={<KnowledgeSourcesPage />} />
          <Route path="/documents" element={<Navigate to="/projects" replace />} />
          <Route path="/ask" element={<Navigate to="/projects" replace />} />
        </Route>
      </Route>
      <Route path="*" element={<FallbackRoute />} />
    </Routes>
    )}
  </StartupIntro>;
}

// Registration remains available while the existing browser session is restored.
export function AppRoutes() {
  return <Routes>
    <Route path="/register" element={<RegistrationForm />} />
    <Route path="*" element={<SessionRoutes />} />
  </Routes>;
}
