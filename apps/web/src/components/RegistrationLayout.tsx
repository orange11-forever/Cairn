import type { ReactNode } from "react";
import { BrandMark } from "./BrandMark.tsx";
import { MascotFigure } from "./MascotFigure.tsx";

export function RegistrationLayout({ children }: { children: ReactNode }) {
  return <main className="login-page"><header className="auth-header"><BrandMark /></header><div className="login-layout">
    <section className="login-brand-scene" aria-label="Cairn 品牌场景">
      <MascotFigure variant="full" state="idle" label="岑宁，Cairn 知识向导" idleCaption="岑宁，知识向导" />
    </section>
    <section className="login-card registration-card">{children}</section>
  </div></main>;
}
