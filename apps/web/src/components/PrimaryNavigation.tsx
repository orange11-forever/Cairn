import { BookOpenText, Code2, ListChecks, Settings2, type LucideIcon } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";

import { projectModuleFromPath, projectPath, type ProjectModule } from "../app/projectRoutes.ts";
import { Stone } from "./trail/Stone.tsx";

type DesktopHost = { postMessage(message: string): void };

const MODULES: readonly { module: ProjectModule; label: string; icon: LucideIcon; desktopOnly: boolean }[] = [
  { module: "tasks", label: "任务", icon: ListChecks, desktopOnly: false },
  { module: "knowledge", label: "知识", icon: BookOpenText, desktopOnly: false },
  { module: "code", label: "代码", icon: Code2, desktopOnly: true },
];

export function PrimaryNavigation({ projectId }: { projectId: string | null }) {
  const { pathname } = useLocation();
  const host = (window as Window & { chrome?: { webview?: DesktopHost } }).chrome?.webview;
  const items = MODULES.filter((item) => !item.desktopOnly || host !== undefined);
  const currentIndex = projectId === null ? -1 : items.findIndex((item) => item.module === projectModuleFromPath(pathname));

  return (
    <nav aria-label="主导航" className="primary-nav">
      {currentIndex >= 0 ? (
        <span aria-hidden="true" className="nav-indicator" data-index={currentIndex}>
          {/* key 让落地动画在每次换项时重播。 */}
          <Stone key={currentIndex} />
        </span>
      ) : null}
      <ul>
        {items.map(({ module, label, icon: Icon }) => {
          const content = (
            <>
              <Icon aria-hidden="true" size={18} strokeWidth={1.8} />
              <span className="nav-label-full">{label}</span>
              <span className="nav-label-short">{label}</span>
            </>
          );
          return (
            <li key={module}>
              {projectId === null
                ? <span aria-disabled="true" className="nav-item-disabled">{content}</span>
                : <NavLink aria-label={label} to={projectPath(projectId, module)}>{content}</NavLink>}
            </li>
          );
        })}
      </ul>
      {host === undefined ? null : (
        <button className="nav-settings" onClick={() => host.postMessage("cairn:settings:models")} type="button">
          <Settings2 aria-hidden="true" size={18} strokeWidth={1.8} />
          <span>设置</span>
        </button>
      )}
    </nav>
  );
}
