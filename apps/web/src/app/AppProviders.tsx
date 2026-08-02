import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import { SessionProvider } from "../session/SessionContext.tsx";
import { createAppQueryClient } from "./queryClient.ts";

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(createAppQueryClient);

  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <SessionProvider>{children}</SessionProvider>
      </QueryClientProvider>
    </BrowserRouter>
  );
}
