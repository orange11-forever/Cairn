import { Navigate, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import type { IdentityContext } from "../api/auth.ts";

import { AuthenticatedLayout } from "../components/AuthenticatedLayout.tsx";
import { LoginForm } from "../components/LoginForm.tsx";
import { AskPage } from "../pages/AskPage.tsx";
import { DocumentsPage } from "../pages/DocumentsPage.tsx";
import { useSession } from "../session/SessionContext.tsx";

function LoginRoute() {
  const { status, establishSession } = useSession();
  const navigate = useNavigate();

  if (status === "authenticated") return <Navigate to="/documents" replace />;

  function handleSuccess(identity: IdentityContext) {
    establishSession(identity);
    navigate("/documents", { replace: true });
  }

  return <LoginForm onSuccess={handleSuccess} />;
}

function RequireSession() {
  const { status } = useSession();

  return status === "anonymous" ? <Navigate to="/login" replace /> : <Outlet />;
}

function FallbackRoute() {
  const { status } = useSession();

  return <Navigate to={status === "anonymous" ? "/login" : "/documents"} replace />;
}

export function AppRoutes() {
  const { status } = useSession();
  if (status === "restoring") {
    return <main aria-busy="true">正在恢复会话…</main>;
  }
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route element={<RequireSession />}>
        <Route element={<AuthenticatedLayout />}>
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/ask" element={<AskPage />} />
        </Route>
      </Route>
      <Route path="*" element={<FallbackRoute />} />
    </Routes>
  );
}
