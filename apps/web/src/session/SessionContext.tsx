import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { UserDto } from "@cairn/contracts";
import { useNavigate } from "react-router-dom";

export interface ActiveSession {
  user: UserDto;
  signal: AbortSignal;
}

export interface SessionContextValue {
  session: ActiveSession | null;
  establishSession(user: UserDto): void;
  logout(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const controllerRef = useRef<AbortController | null>(null);
  const [session, setSession] = useState<ActiveSession | null>(null);

  function establishSession(user: UserDto): void {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setSession({ user, signal: controller.signal });
  }

  async function logout(): Promise<void> {
    await queryClient.cancelQueries();
    controllerRef.current?.abort();
    queryClient.clear();
    controllerRef.current = null;
    setSession(null);
    navigate("/login", { replace: true });
  }

  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  return (
    <SessionContext.Provider value={{ session, establishSession, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error("useSession 必须在 SessionProvider 内使用");
  }
  return context;
}
