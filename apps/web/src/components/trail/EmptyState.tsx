import { useEffect, useState, type ReactNode } from "react";

import { MascotFigure } from "../MascotFigure.tsx";
import { TopoBackground } from "./TopoBackground.tsx";

const drawn = new Set<string>();

export function EmptyState({ title, description, action, drawKey }: {
  title: string; description: string; action?: ReactNode; drawKey: string;
}) {
  const [draw] = useState(() => !drawn.has(drawKey));
  useEffect(() => { drawn.add(drawKey); }, [drawKey]);
  return (
    <section className="trail-empty" data-draw={draw ? "true" : undefined}>
      <TopoBackground draw={draw} variant="page" />
      <div className="trail-empty-copy">
        <MascotFigure label="岑宁，Cairn 项目向导" variant="avatar" />
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
          {action}
        </div>
      </div>
    </section>
  );
}
