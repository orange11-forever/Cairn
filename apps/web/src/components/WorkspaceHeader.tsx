export function WorkspaceHeader({
  id,
  title,
  description,
  eyebrow,
  status,
  actions,
}: {
  id: string;
  title: string;
  description: string;
  eyebrow?: string;
  status?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="workspace-header">
      <div>
        {eyebrow === undefined ? null : <p className="workspace-eyebrow">{eyebrow}</p>}
        <h1 id={id}>{title}</h1>
        <p>{description}</p>
        {status === undefined ? null : <div className="workspace-header-status">{status}</div>}
      </div>
      {actions === undefined ? null : <div className="workspace-header-actions">{actions}</div>}
    </div>
  );
}
