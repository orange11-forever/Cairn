import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  type IdentityContext,
  logoutSession,
  restoreSession,
} from "../api/auth.ts";
import { ApiError } from "../api/errors.ts";

export interface ActiveSession {
  identity: IdentityContext;
  user: IdentityContext["user"];
  signal: AbortSignal;
}

export interface SessionApi {
  restore(signal: AbortSignal): Promise<IdentityContext>;
  logout(csrfToken: string, signal: AbortSignal): Promise<void>;
}

export type SessionStatus = "restoring" | "anonymous" | "authenticated";

export interface SessionContextValue {
  status: SessionStatus;
  session: ActiveSession | null;
  logoutError: ApiError | null;
  establishSession(identity: IdentityContext): void;
  logout(): Promise<void>;
}

const defaultSessionApi: SessionApi = { restore: restoreSession, logout: logoutSession };
const SessionContext = createContext<SessionContextValue | undefined>(undefined);

export function SessionProvider({
  children,
  sessionApi = defaultSessionApi,
  restoredIdentity,
}: {
  children: React.ReactNode;
  sessionApi?: SessionApi;
  restoredIdentity?: IdentityContext;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const controllerRef = useRef<AbortController | null>(null);
  const [status, setStatus] = useState<SessionStatus>(
    restoredIdentity === undefined ? "restoring" : "authenticated",
  );
  const [session, setSession] = useState<ActiveSession | null>(() => {
    if (restoredIdentity === undefined) return null;
    const controller = new AbortController();
    controllerRef.current = controller;
    return { identity: restoredIdentity, user: restoredIdentity.user, signal: controller.signal };
  });
  const [logoutError, setLogoutError] = useState<ApiError | null>(null);

  const establishSession = useCallback((identity: IdentityContext): void => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setSession({ identity, user: identity.user, signal: controller.signal });
    setLogoutError(null);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    if (session === null) return;
    await queryClient.cancelQueries();
    try {
      await sessionApi.logout(session.identity.csrfToken, session.signal);
    } catch (error) {
      setLogoutError(
        error instanceof ApiError
          ? error
          : new ApiError("network", "无法退出登录，请重试", { cause: error }),
      );
      return;
    }
    controllerRef.current?.abort();
    queryClient.clear();
    controllerRef.current = null;
    setSession(null);
    setStatus("anonymous");
    setLogoutError(null);
    navigate("/login", { replace: true });
  }, [navigate, queryClient, session, sessionApi]);

  useEffect(() => {
    if (restoredIdentity !== undefined) return;
    const bootstrap = new AbortController();
    void sessionApi
      .restore(bootstrap.signal)
      .then(establishSession)
      .catch(() => {
        if (!bootstrap.signal.aborted) setStatus("anonymous");
      });
    return () => bootstrap.abort();
  }, [establishSession, restoredIdentity, sessionApi]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  return (
    <SessionContext.Provider
      value={{ status, session, logoutError, establishSession, logout }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (context === undefined) throw new Error("useSession 必须在 SessionProvider 内使用");
  return context;
}
