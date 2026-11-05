import type { ReactNode } from "react";

import { BrandMark } from "./BrandMark.tsx";
import { MascotFigure } from "./MascotFigure.tsx";
import { Stone } from "./trail/Stone.tsx";
import { TopoBackground } from "./trail/TopoBackground.tsx";

export function AuthScene({ children, cardClassName, cardLabelledBy }: {
  children: ReactNode; cardClassName: string; cardLabelledBy?: string;
}) {
  return (
    <main className="login-page">
      <TopoBackground variant="scene" />
      <header className="auth-header"><BrandMark /></header>
      <div className="login-layout">
        <section aria-label="Cairn 品牌场景" className="login-brand-scene">
          <svg aria-hidden="true" className="login-trail" preserveAspectRatio="none" viewBox="0 0 600 560">
            <path d="M-10 550 C 50 500, 80 480, 130 490 S 200 450, 175 380 S 225 250, 330 270 S 470 340, 620 260" />
          </svg>
          <span aria-hidden="true" className="login-cairn">
            <Stone /><Stone /><Stone /><Stone />
          </span>
          <MascotFigure idleCaption="岑宁 · 项目向导" label="岑宁，Cairn 知识向导" state="idle" variant="full" />
        </section>
        <section aria-labelledby={cardLabelledBy} className={cardClassName}>{children}</section>
      </div>
    </main>
  );
}
