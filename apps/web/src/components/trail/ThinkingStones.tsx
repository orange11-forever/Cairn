import type { ReactNode } from "react";

export function ThinkingStones({ children }: { children: ReactNode }) {
  return (
    <span className="thinking-stones">
      <span aria-hidden="true" className="thinking-stones-dots">
        <span className="stone" />
        <span className="stone" />
        <span className="stone" />
      </span>
      <span>{children}</span>
    </span>
  );
}
