import { useEffect, useRef } from "react";
import { Settings2 } from "lucide-react";

type DesktopHost = { postMessage(message: string): void };

export function DesktopModelSettings() {
  const host = (window as Window & { chrome?: { webview?: DesktopHost } }).chrome?.webview;
  if (!host) return null;
  return <button type="button" className="desktop-model-settings"
    onClick={() => host.postMessage("cairn:settings:models")}>AI / API 配置</button>;
}

export function DesktopSettings() {
  const panel = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const host = (window as Window & { chrome?: { webview?: DesktopHost } }).chrome?.webview;
  useEffect(() => {
    function outside(event: PointerEvent) {
      if (event.target instanceof Node && panel.current && !panel.current.contains(event.target)) panel.current.open = false;
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);
  if (!host) return null;

  function close() {
    if (panel.current) panel.current.open = false;
  }
  function invoke(action: string) {
    close();
    host!.postMessage(`cairn:settings:${action}`);
  }

  return <details className="desktop-settings" ref={panel}
    onKeyDown={event => { if (event.key === "Escape") { close(); trigger.current?.focus(); } }}>
    <summary ref={trigger} tabIndex={0}><Settings2 size={18} aria-hidden="true" strokeWidth={1.7} /><span>设置</span></summary>
    <div className="desktop-settings-panel">
      <section aria-label="AI 服务"><h2>AI 服务</h2>
        <button type="button" onClick={() => invoke("models")}>AI / API 配置</button>
      </section>
      <section aria-label="数据管理"><h2>数据管理</h2>
        <button type="button" onClick={() => invoke("backup")}>备份数据…</button>
        <button type="button" onClick={() => invoke("restore")}>从备份恢复…</button>
        <button type="button" onClick={() => invoke("folder")}>打开数据文件夹</button>
      </section>
      <section aria-label="帮助与诊断"><h2>帮助与诊断</h2>
        <button type="button" onClick={() => invoke("diagnostics")}>诊断信息</button>
      </section>
    </div>
  </details>;
}
