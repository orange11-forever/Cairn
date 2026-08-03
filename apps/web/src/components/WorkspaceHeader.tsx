export function WorkspaceHeader({
  id,
  title,
  description,
  actions,
}: {
  id: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="workspace-header">
      <div>
        <h1 id={id}>{title}</h1>
        <p>{description}</p>
      </div>
      {actions === undefined ? null : <div className="workspace-header-actions">{actions}</div>}
    </div>
  );
}
