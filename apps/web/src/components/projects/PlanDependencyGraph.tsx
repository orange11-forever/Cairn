import { useId } from "react";
import type { ProposedTask } from "../../api/projectPlanning.ts";

export function PlanDependencyGraph({ tasks, selectedId, onSelect }: {
  tasks: ProposedTask[]; selectedId: string | null; onSelect(id: string): void;
}) {
  const arrowId = useId();
  const levels = new Map<string, number>();
  const byId = new Map(tasks.map(task => [task.id, task]));
  function level(id: string): number {
    if (levels.has(id)) return levels.get(id)!;
    const predecessors = byId.get(id)!.dependsOn;
    const value = predecessors.length ? Math.max(...predecessors.map(level)) + 1 : 0;
    levels.set(id, value);
    return value;
  }
  const rows = new Map<number, number>();
  const nodes = tasks.map(task => {
    const column = level(task.id);
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    return {task, x: 16 + column * 248, y: 16 + row * 112};
  });
  const positions = new Map(nodes.map(node => [node.task.id, node]));
  const width = (Math.max(...levels.values()) + 1) * 248 + 16;
  const height = Math.max(...rows.values()) * 112 + 16;
  return <div className="plan-graph-scroll" tabIndex={0} aria-label="依赖图画布，可横向滚动">
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="group" aria-label="规划任务依赖图">
      <defs><marker id={arrowId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>
      <g className="plan-graph-edges" aria-hidden="true">
        {nodes.flatMap(node => node.task.dependsOn.map(id => {
          const source = positions.get(id)!;
          return <path key={`${id}-${node.task.id}`} d={`M ${source.x + 216} ${source.y + 44} C ${source.x + 232} ${source.y + 44}, ${node.x - 16} ${node.y + 44}, ${node.x - 3} ${node.y + 44}`} markerEnd={`url(#${arrowId})`}/>;
        }))}
      </g>
      {nodes.map(({task,x,y}) => <g key={task.id} transform={`translate(${x},${y})`} className="plan-graph-node" data-selected={selectedId === task.id} role="button" tabIndex={0} aria-label={`查看建议任务：${task.title}`} onClick={() => onSelect(task.id)} onKeyDown={event => {if(event.key === "Enter" || event.key === " "){event.preventDefault();onSelect(task.id);}}}>
        <rect width="216" height="88" rx="8"/>
        <foreignObject x="12" y="10" width="192" height="68"><div className="plan-graph-label"><strong>{task.id} · {task.title}</strong><span>{task.stageId}{task.milestoneId ? ` · ${task.milestoneId}` : ""}</span></div></foreignObject>
      </g>)}
    </svg>
  </div>;
}
