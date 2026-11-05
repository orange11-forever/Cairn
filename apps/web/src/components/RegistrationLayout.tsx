import type { ReactNode } from "react";

import { AuthScene } from "./AuthScene.tsx";

export function RegistrationLayout({ children }: { children: ReactNode }) {
  return <AuthScene cardClassName="login-card registration-card">{children}</AuthScene>;
}
