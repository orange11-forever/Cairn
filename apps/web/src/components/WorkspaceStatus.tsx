import type { ReactNode } from "react";

import { MascotFigure } from "./MascotFigure.tsx";
import type { MascotFigureProps, MascotState } from "./MascotFigure.tsx";

export interface WorkspaceStatusProps {
  state: "empty" | "loading" | "success" | "error";
  mascot?: MascotFigureProps;
  title: string;
  description: string;
  action?: ReactNode;
}

const MASCOT_STATE: Record<WorkspaceStatusProps["state"], MascotState> = {
  empty: "idle",
  loading: "thinking",
  success: "success",
  error: "attention",
};

export function WorkspaceStatus({
  state,
  mascot,
  title,
  description,
  action,
}: WorkspaceStatusProps) {
  return (
    <section className="workspace-status" data-state={state} aria-live="polite">
      {mascot === undefined ? null : (
        <MascotFigure state={MASCOT_STATE[state]} {...mascot} />
      )}
      <div className="workspace-status-content">
        <h2>{title}</h2>
        <p>{description}</p>
        {action === undefined ? null : <div className="workspace-status-action">{action}</div>}
      </div>
    </section>
  );
}
