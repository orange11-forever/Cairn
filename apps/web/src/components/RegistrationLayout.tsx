import type { ReactNode } from "react";
import { BrandMark } from "./BrandMark.tsx";
import { MascotFigure } from "./MascotFigure.tsx";

export function RegistrationLayout({ children }: { children: ReactNode }) {
  return <main className="login-page"><div className="login-layout">
    <section className="login-brand-scene" aria-label="Cairn 品牌场景">
      <span className="login-wordmark-chip login-wordmark"><BrandMark /></span>
      <MascotFigure variant="full" state="idle" label="岑宁，Cairn 知识向导" idleCaption="岑宁，知识向导" />
    </section>
    <section className="login-card registration-card">{children}</section>
  </div></main>;
}
