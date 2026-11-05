import { useEffect, useRef, useState } from "react";

import type { TaskStatus } from "../../api/projects.ts";

const SETTLE_MS = 700;

export function Stone({ className }: { className?: string }) {
  return <span aria-hidden="true" className={className ? `stone ${className}` : "stone"} />;
}

export function StatusStone({ status, label }: { status: TaskStatus; label: string }) {
  const previous = useRef(status);
  const [settling, setSettling] = useState(false);
  useEffect(() => {
    const becameDone = previous.current !== "done" && status === "done";
    previous.current = status;
    if (!becameDone) { setSettling(false); return; }
    setSettling(true);
    const timer = window.setTimeout(() => setSettling(false), SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [status]);
  return (
    <span
      aria-label={label}
      className="status-stone"
      data-settling={settling ? "true" : undefined}
      data-status={status}
      role="img"
    >
      <span className="stone" />
      <span className="status-stone-dust" />
      <span className="status-stone-dust" />
    </span>
  );
}
