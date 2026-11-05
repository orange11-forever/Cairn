import { X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { MascotFigure } from "../MascotFigure.tsx";

export const TOAST_DURATION_MS = 4000;
const MAX_TOASTS = 3;

interface ToastInput { title: string; detail?: string }
interface ToastEntry extends ToastInput { id: number }
interface ToastContextValue { notify(toast: ToastInput): void }

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const nextId = useRef(1);
  const notify = useCallback((toast: ToastInput) => {
    const id = nextId.current++;
    setToasts((current) => [...current, { ...toast, id }].slice(-MAX_TOASTS));
  }, []);
  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);
  const value = useMemo(() => ({ notify }), [notify]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <section aria-label="操作结果" aria-live="polite" className="toast-region">
        {toasts.map((toast) => <ToastItem key={toast.id} onDismiss={dismiss} toast={toast} />)}
      </section>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastEntry; onDismiss(id: number): void }) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;
  const remaining = useRef(TOAST_DURATION_MS);
  useEffect(() => {
    if (paused) return;
    const started = Date.now();
    const timer = window.setTimeout(() => onDismiss(toast.id), remaining.current);
    return () => {
      window.clearTimeout(timer);
      remaining.current -= Date.now() - started;
    };
  }, [paused, toast.id, onDismiss]);
  return (
    <div className="toast" data-paused={paused ? "true" : undefined}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}
      onFocus={() => setFocused(true)} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
      <MascotFigure label="岑宁" variant="avatar" />
      <div className="toast-copy">
        <strong>{toast.title}</strong>
        {toast.detail === undefined ? null : <span>{toast.detail}</span>}
      </div>
      <button aria-label="关闭提示" className="btn-ghost toast-close" onClick={() => onDismiss(toast.id)} type="button">
        <X aria-hidden="true" size={15} />
      </button>
      <span aria-hidden="true" className="toast-trail" />
    </div>
  );
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (value === null) throw new Error("useToast 必须在 ToastProvider 内使用");
  return value;
}
