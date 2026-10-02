import { Navigate, Outlet, Route, Routes, useNavigate, useSearchParams } from "react-router-dom";
import type { IdentityContext } from "../api/auth.ts";

import { AuthenticatedLayout } from "../components/AuthenticatedLayout.tsx";
import { LoginForm } from "../components/LoginForm.tsx";
import { OAuthFinalize } from "../components/OAuthFinalize.tsx";
import { KnowledgePage } from "../pages/KnowledgePage.tsx";
import { KnowledgeSourcesPage } from "../pages/KnowledgeSourcesPage.tsx";
import { AccountIdentitiesPage } from "../pages/AccountIdentitiesPage.tsx";
import { ProjectsPage } from "../pages/ProjectsPage.tsx";
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

export function AppRoutes() {
  const { status, restoreError, retryRestore, restartLogin } = useSession();
  if (status === "restoring") {
    return <main className="session-status-page" aria-busy="true">正在恢复会话…</main>;
  }
  if (status === "restore-error") {
    return (
      <main className="session-status-page">
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
    );
  }
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route element={<RequireSession />}>
        <Route element={<AuthenticatedLayout />}>
          <Route path="/account/identities" element={<AccountIdentitiesPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId/knowledge" element={<KnowledgePage />} />
          <Route path="/projects/:projectId/knowledge/sources" element={<KnowledgeSourcesPage />} />
          <Route path="/documents" element={<Navigate to="/projects" replace />} />
          <Route path="/ask" element={<Navigate to="/projects" replace />} />
        </Route>
      </Route>
      <Route path="*" element={<FallbackRoute />} />
    </Routes>
  );
}
