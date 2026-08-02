import { Navigate, Outlet, Route, Routes, useNavigate } from "react-router-dom";

import { AuthenticatedLayout } from "../components/AuthenticatedLayout.tsx";
import { LoginForm } from "../components/LoginForm.tsx";
import { AskPage } from "../pages/AskPage.tsx";
import { DocumentsPage } from "../pages/DocumentsPage.tsx";
import { useSession } from "../session/SessionContext.tsx";
import type { UserDto } from "../schemas/users.ts";

function LoginRoute() {
  const { session, establishSession } = useSession();
  const navigate = useNavigate();

  if (session !== null) return <Navigate to="/documents" replace />;

  function handleSuccess(user: UserDto) {
    establishSession(user);
    navigate("/documents", { replace: true });
  }

  return <LoginForm onSuccess={handleSuccess} />;
}

function RequireSession() {
  const { session } = useSession();

  return session === null ? <Navigate to="/login" replace /> : <Outlet />;
}

function FallbackRoute() {
  const { session } = useSession();

  return <Navigate to={session === null ? "/login" : "/documents"} replace />;
}

export function AppRoutes() {
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
