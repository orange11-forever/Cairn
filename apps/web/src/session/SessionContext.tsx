import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  type IdentityContext,
  logoutSession,
  prepareLoginContext,
  restoreSession,
} from "../api/auth.ts";
import { ApiError } from "../api/errors.ts";

export interface ActiveSession {
  identity: IdentityContext;
  user: IdentityContext["user"];
  signal: AbortSignal;
  generation: number;
}

export interface SessionApi {
  restore(signal: AbortSignal): Promise<IdentityContext>;
  prepareLogin?(signal: AbortSignal): Promise<void>;
  logout(csrfToken: string, signal: AbortSignal): Promise<void>;
}

export type SessionStatus = "restoring" | "restore-error" | "anonymous" | "authenticated";

export interface SessionContextValue {
  status: SessionStatus;
  session: ActiveSession | null;
  restoreError: ApiError | null;
  logoutError: ApiError | null;
  establishSession(identity: IdentityContext): void;
  retryRestore(): void;
  logout(): Promise<void>;
  restartLogin(): Promise<void>;
}

const defaultSessionApi: SessionApi = { restore: restoreSession, logout: logoutSession, prepareLogin: prepareLoginContext };
const SessionContext = createContext<SessionContextValue | undefined>(undefined);

function isSessionInvalid(error: unknown): error is ApiError {
  return error instanceof ApiError &&
    error.kind === "http" &&
    error.status === 401 &&
    error.code === "session_invalid";
}

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
  const generationRef = useRef(restoredIdentity === undefined ? 0 : 1);
  const restoreControllerRef = useRef<AbortController | null>(null);
  const expiringRef = useRef(false);
  const [status, setStatus] = useState<SessionStatus>(
    restoredIdentity === undefined ? "restoring" : "authenticated",
  );
  const [session, setSession] = useState<ActiveSession | null>(() => {
    if (restoredIdentity === undefined) return null;
    const controller = new AbortController();
    controllerRef.current = controller;
    return {
      identity: restoredIdentity,
      user: restoredIdentity.user,
      signal: controller.signal,
      generation: generationRef.current,
    };
  });
  const [restoreError, setRestoreError] = useState<ApiError | null>(null);
  const [logoutError, setLogoutError] = useState<ApiError | null>(null);

  const establishSession = useCallback((identity: IdentityContext): void => {
    restoreControllerRef.current?.abort();
    controllerRef.current?.abort();
    queryClient.clear();
    const controller = new AbortController();
    generationRef.current += 1;
    controllerRef.current = controller;
    expiringRef.current = false;
    setSession({
      identity,
      user: identity.user,
      signal: controller.signal,
      generation: generationRef.current,
    });
    setRestoreError(null);
    setLogoutError(null);
    setStatus("authenticated");
  }, [queryClient]);

  const prepareAnonymous = useCallback(async (): Promise<void> => {
    restoreControllerRef.current?.abort();
    const controller = new AbortController();
    restoreControllerRef.current = controller;
    setStatus("restoring");
    setRestoreError(null);
    try {
      await sessionApi.prepareLogin?.(controller.signal);
      if (!controller.signal.aborted) setStatus("anonymous");
    } catch (error) {
      if (controller.signal.aborted) return;
      setRestoreError(error instanceof ApiError ? error : new ApiError("network", "暂时无法准备登录，请重试", { cause: error }));
      setStatus("restore-error");
    }
  }, [sessionApi]);

  const expireSession = useCallback((): void => {
    const controller = controllerRef.current;
    if (controller === null || expiringRef.current) return;
    expiringRef.current = true;

    void Promise.resolve()
      .then(() => queryClient.cancelQueries())
      .catch(() => undefined)
      .then(() => {
        controller.abort();
        queryClient.clear();
        if (controllerRef.current === controller) controllerRef.current = null;
        setSession(null);
        void prepareAnonymous();
        setLogoutError(null);
        navigate("/login", { replace: true });
      });
  }, [navigate, prepareAnonymous, queryClient]);

  const retryRestore = useCallback((): void => {
    restoreControllerRef.current?.abort();
    const controller = new AbortController();
    restoreControllerRef.current = controller;
    setRestoreError(null);
    setStatus("restoring");
    void sessionApi
      .restore(controller.signal)
      .then(establishSession)
      .catch(async (error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError("network", "暂时无法恢复会话，请重试", { cause: error });
        if (
          apiError.kind === "http" &&
          apiError.status === 401 &&
          apiError.code === "session_invalid"
        ) {
          await prepareAnonymous();
          return;
        }
        setRestoreError(apiError);
        setStatus("restore-error");
      });
  }, [establishSession, prepareAnonymous, sessionApi]);

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
    await prepareAnonymous();
    setLogoutError(null);
    navigate("/login", { replace: true });
  }, [navigate, prepareAnonymous, queryClient, session, sessionApi]);

  const restartLogin = useCallback(async (): Promise<void> => {
    if (session !== null) return;
    const controller = new AbortController();
    setStatus("restoring");
    try {
      await sessionApi.logout("", controller.signal);
      await prepareAnonymous();
      navigate("/login", { replace: true });
    } catch (error) {
      setRestoreError(error instanceof ApiError ? error : new ApiError("network", "暂时无法重新开始登录，请重试", { cause: error }));
      setStatus("restore-error");
    }
  }, [navigate, prepareAnonymous, session, sessionApi]);

  useEffect(() => {
    if (restoredIdentity !== undefined) return;
    retryRestore();
    return () => restoreControllerRef.current?.abort();
  }, [restoredIdentity, retryRestore]);

  useEffect(() => {
    const unsubscribeQueries = queryClient.getQueryCache().subscribe((event) => {
      if (
        event.type === "updated" &&
        event.action.type === "error" &&
        isSessionInvalid(event.action.error)
      ) {
        expireSession();
      }
    });
    const unsubscribeMutations = queryClient.getMutationCache().subscribe((event) => {
      if (
        event.type === "updated" &&
        event.action.type === "error" &&
        isSessionInvalid(event.action.error)
      ) {
        expireSession();
      }
    });
    return () => {
      unsubscribeQueries();
      unsubscribeMutations();
    };
  }, [expireSession, queryClient]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  return (
    <SessionContext.Provider
      value={{ status, session, restoreError, logoutError, establishSession, retryRestore, logout, restartLogin }}
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
