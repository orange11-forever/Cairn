import { CircleHelp, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { MascotFigure } from "./MascotFigure.tsx";
import type { MascotState } from "./MascotFigure.tsx";

const PAGE_COPY = {
  projects: {
    title: "项目任务助手",
    description: "我会陪你查看项目任务，并提示当前状态可以执行的下一步操作。",
  },
  knowledge: {
    title: "项目知识助手",
    description: "我会陪你查看当前项目的资料状态，并提示摄取或检索的下一步操作。",
  },
} as const;

export function MascotAssistant({
  page,
  defaultState = "idle",
}: {
  page: "projects" | "knowledge";
  defaultState?: MascotState;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const copy = PAGE_COPY[page];

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node) === false) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const closePanel = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className="mascot-assistant" ref={rootRef}>
      <button
        aria-controls={panelId}
        aria-expanded={open}
        aria-label="打开岑宁助手"
        className="mascot-assistant-trigger"
        onClick={() => setOpen((current) => !current)}
        ref={triggerRef}
        type="button"
      >
        <MascotFigure label="岑宁，Cairn 知识向导" state={defaultState} />
      </button>

      {open ? (
        <section
          aria-label="岑宁助手"
          className="mascot-assistant-panel"
          id={panelId}
          role="dialog"
        >
          <div className="mascot-assistant-heading">
            <span aria-hidden="true" className="mascot-assistant-icon">
              <CircleHelp size={18} strokeWidth={1.8} />
            </span>
            <h2>{copy.title}</h2>
            <button
              aria-label="关闭岑宁助手"
              className="icon-button mascot-assistant-close"
              onClick={closePanel}
              type="button"
            >
              <X aria-hidden="true" size={18} strokeWidth={1.8} />
            </button>
          </div>
          <div className="mascot-assistant-body">
            <MascotFigure label="岑宁，Cairn 助手" state={defaultState} variant="half" />
            <p>{copy.description}</p>
          </div>
        </section>
      ) : null}
    </div>
  );
}
