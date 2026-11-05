import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router-dom";
import type { IdentityContext } from "../../api/auth.ts";
import { projectPath } from "../../app/projectRoutes.ts";
import { refreshProjectStructure, taskKeys } from "../../queries/projects.ts";
import { useSession } from "../../session/SessionContext.tsx";
import { ProjectOperations } from "./ProjectOperations.tsx";
import { ProjectPlanPreview } from "./ProjectPlanPreview.tsx";
import { ProjectCreation } from "./ProjectCreation.tsx";

export function ProjectCommandPanel({ projectId }: { projectId: string | null }) {
  const { session } = useSession();
  if (!session) return null;
  return <Commands key={`${session.generation}:${projectId}`} projectId={projectId} identity={session.identity} signal={session.signal} />;
}

function Commands({ projectId, identity, signal }: { projectId: string | null; identity: IdentityContext; signal: AbortSignal }) {
  const client = useQueryClient();
  const tabId = useId();
  type Mode = "operation" | "plan" | "create";
  const [mode, setMode] = useState<Mode>(projectId ? "operation" : "create");
  const [busy, setBusy] = useState(false);
  const canCreate = ["owner", "admin", "member"].includes(identity.membership.role);
  const tabs: [Mode, string][] = [
    ...(projectId ? [["operation", "项目操作"], ["plan", "拆分任务"]] as [Mode, string][] : []),
    ...(canCreate ? [["create", "创建项目"]] as [Mode, string][] : []),
  ];

  async function refresh() {
    const org = identity.organization.id;
    await Promise.all([
      refreshProjectStructure(client, org, projectId!),
      client.invalidateQueries({ queryKey: taskKeys.list(org, projectId!), exact: true }, { throwOnError: true }),
      client.invalidateQueries({ queryKey: taskKeys.detailScope(org, projectId!) }, { throwOnError: true }),
      client.invalidateQueries({ queryKey: taskKeys.dependencyScope(org, projectId!) }, { throwOnError: true }),
    ]);
  }

  return <div className="project-command-panel">
    {projectId && <div className="project-command-links"><Link to={projectPath(projectId, "tasks")}>查看项目任务</Link></div>}
    {tabs.length === 0 ? <p>先从顶栏选择一个项目，再告诉我需要执行的操作。</p> : <>
      <div className="project-command-tabs" role="tablist" aria-label="助手工作方式" onKeyDown={event => {
        if (busy || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const index = tabs.findIndex(([value]) => value === mode);
        const next = tabs[event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowLeft" ? -1 : 1) + tabs.length) % tabs.length]![0];
        setMode(next);
        document.getElementById(`${tabId}-${next}`)?.focus();
      }}>
        {tabs.map(([value, label]) => <button key={value} id={`${tabId}-${value}`} type="button" role="tab" aria-selected={mode === value} aria-controls={`${tabId}-panel`} tabIndex={mode === value ? 0 : -1} disabled={busy && mode !== value} onClick={() => setMode(value)}>{label}</button>)}
      </div>
      <div role="tabpanel" id={`${tabId}-panel`} aria-labelledby={`${tabId}-${mode}`}>
        {mode === "create" && canCreate ? <ProjectCreation identity={identity} signal={signal} onBusy={setBusy} />
          : projectId && (mode === "operation"
            ? <ProjectOperations projectId={projectId} ownerId={identity.user.id} csrfToken={identity.csrfToken} signal={signal} onApplied={refresh} onBusy={setBusy} />
            : <ProjectPlanPreview projectId={projectId} ownerId={identity.user.id} csrfToken={identity.csrfToken} signal={signal} onApplied={refresh} onBusy={setBusy} />)}
      </div>
    </>}
  </div>;
}
