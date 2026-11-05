import { useEffect, useState, type ReactNode } from "react";

import { TopoBackground } from "./trail/TopoBackground.tsx";

export const INTRO_MIN_MS = 1300;
export const INTRO_EXIT_MS = 300;

// Routing, login retries and later restores must not replay the launch sequence.
let visited = false;
type Phase = "play" | "exit" | "done";

export function StartupIntro({ restoring, children }: { restoring: boolean; children?: ReactNode }) {
  const [phase, setPhase] = useState<Phase>(() => visited || !restoring ? "done" : "play");
  const [reduced] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [minElapsed, setMinElapsed] = useState(reduced);

  useEffect(() => { visited = true; }, []);
  useEffect(() => {
    if (phase !== "play" || reduced) return;
    const timer = window.setTimeout(() => setMinElapsed(true), INTRO_MIN_MS);
    return () => window.clearTimeout(timer);
  }, [phase, reduced]);
  useEffect(() => {
    if (phase === "play" && minElapsed && !restoring) setPhase("exit");
  }, [phase, minElapsed, restoring]);
  useEffect(() => {
    if (phase !== "exit") return;
    const timer = window.setTimeout(() => setPhase("done"), INTRO_EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  return <>
    {phase !== "done" && <div className="startup-intro" aria-hidden="true" data-phase={phase} data-reduced={reduced ? "true" : undefined}>
      <TopoBackground draw={!reduced} variant="scene" />
      <div className="startup-intro-core">
        <svg className="startup-intro-mark" viewBox="0 0 36 36">
          <path className="piece" d="M2.2 28.7 9.4 15c.5-1 1.3-1.3 2-.3l2.7 3.7c-1.5 1.1-2.7 2.8-3.6 4.5l-3.8 7.6H3.2c-1.2 0-1.6-.8-1-1.8Z" />
          <path className="piece" d="m14.1 17.4 4.1-8.6c.6-1.3 1.3-2.1 2.5-2.1 1.3 0 2 .9 2.6 2.1l3.1 7-5.1 4-3-1.9c-1.3-.9-2.7-1.1-4.2-.5Z" />
          <path className="piece" d="m10.1 30.5 4.8-8.7c.7-1.3 1.5-2 2.6-1.4l3.2 2c.4.2.7.2 1.1-.1l5.6-4.5 6.2 10.8c.6 1.1.2 1.9-1.1 1.9H10.1Z" />
          <path className="trail" d="M6.4 31 L10.6 22.4 Q12.6 18.9 15.4 18.9 L20.6 21.8 L26.9 16.8" />
        </svg>
        <span className="startup-intro-word">Cairn</span>
        <span className="startup-intro-status mono">› 正在恢复会话</span>
      </div>
    </div>}
    <div className="startup-content" inert={phase !== "done" && !restoring} aria-hidden={phase !== "done" && !restoring ? true : undefined} data-revealing={phase === "exit" ? "true" : undefined}>
      {restoring || phase === "play" ? <main className="session-status-page" aria-busy="true" role="status">正在恢复会话…</main> : children}
    </div>
  </>;
}
