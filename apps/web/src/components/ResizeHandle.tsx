import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

interface Props {
  axis: "x" | "y";
  label: string;
  pane: RefObject<HTMLElement | null>;
  min: number;
  max(): number;
  onResize(size: number): void;
  onReset(): void;
  direction?: 1 | -1;
  className?: string;
  hidden?: boolean;
}

export function ResizeHandle({ axis, label, pane, min, max, onResize, onReset, direction = 1, className = "", hidden }: Props) {
  const handle = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: number; origin: number; size: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [metrics, setMetrics] = useState({ now: min, max: min });
  const bounds = () => Math.max(min, max());
  const measured = () => {
    const rect = pane.current?.getBoundingClientRect();
    return Math.round((axis === "x" ? rect?.width : rect?.height) ?? min);
  };

  useLayoutEffect(() => {
    const element = pane.current;
    if (!element) return;
    const update = () => {
      const ceiling = bounds();
      const now = Math.max(min, Math.min(ceiling, measured()));
      setMetrics(previous => previous.now === now && previous.max === ceiling ? previous : { now, max: ceiling });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    if (element.parentElement) observer.observe(element.parentElement);
    return () => observer.disconnect();
  }, [pane, axis, min, max]);

  function resize(value: number) {
    const ceiling = bounds();
    const next = Math.round(Math.max(min, Math.min(ceiling, value)));
    onResize(next);
    setMetrics({ now: next, max: ceiling });
  }
  function finish() {
    const current = drag.current;
    if (!current) return;
    drag.current = null;
    if (handle.current?.hasPointerCapture(current.id)) handle.current.releasePointerCapture(current.id);
    delete document.documentElement.dataset.panelResizeAxis;
    setDragging(false);
  }
  useEffect(() => {
    window.addEventListener("blur", finish);
    return () => {
      window.removeEventListener("blur", finish);
      if (drag.current) delete document.documentElement.dataset.panelResizeAxis;
      drag.current = null;
    };
  }, []);

  return <div ref={handle} role="separator" tabIndex={0} hidden={hidden}
    className={`resize-handle ${className}`} data-axis={axis} data-dragging={dragging || undefined}
    aria-label={label} aria-orientation={axis === "x" ? "vertical" : "horizontal"}
    aria-valuemin={min} aria-valuemax={metrics.max} aria-valuenow={metrics.now} aria-valuetext={`${metrics.now} 像素`}
    aria-disabled={metrics.max === min || undefined}
    title={`${label}；拖动或用方向键调整，双击恢复默认`}
    onPointerDown={event => {
      if (event.button !== 0 || !event.isPrimary || bounds() <= min) return;
      event.preventDefault();
      event.currentTarget.focus({ preventScroll: true });
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { id: event.pointerId, origin: axis === "x" ? event.clientX : event.clientY, size: measured() };
      document.documentElement.dataset.panelResizeAxis = axis;
      setDragging(true);
    }}
    onPointerMove={event => {
      const current = drag.current;
      if (!current || current.id !== event.pointerId) return;
      resize(current.size + ((axis === "x" ? event.clientX : event.clientY) - current.origin) * direction);
    }}
    onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={finish} onDoubleClick={onReset}
    onKeyDown={event => {
      const negative = axis === "x" ? "ArrowLeft" : "ArrowUp";
      const positive = axis === "x" ? "ArrowRight" : "ArrowDown";
      if (![negative, positive, "Home", "End", "Enter", "Escape"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Escape") { finish(); return; }
      if (event.key === "Enter") { onReset(); return; }
      resize(event.key === "Home" ? min : event.key === "End" ? bounds() : measured() + (event.key === positive ? 1 : -1) * direction * (event.shiftKey ? 40 : 10));
    }}
  />;
}
