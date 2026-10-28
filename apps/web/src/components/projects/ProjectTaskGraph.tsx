import { useId, useState } from "react";
import { Minus, Plus, RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import type { ProjectTaskGraph as GraphSnapshot, TaskStatus } from "../../api/projects.ts";
import { taskKeys, useProjectTaskGraph } from "../../queries/projects.ts";
import { GRAPH_NODE_WIDTH, layoutTaskGraph } from "../../lib/taskGraph.ts";

const STATUS: Record<TaskStatus, string> = {
  backlog:"待规划", todo:"待处理", in_progress:"进行中", blocked:"已阻塞", done:"已完成", cancelled:"已取消",
};
type Props = {
  organizationId: string; projectId: string; signal: AbortSignal;
  selectedTaskId: string | null; disabled: boolean; onOpenTask(id: string): void;
};

export function ProjectTaskGraph(props: Props) {
  const query = useProjectTaskGraph(props.organizationId, props.projectId, props.signal);
  const queryClient = useQueryClient();
  const [zoom, setZoom] = useState(1);
  async function refresh() {
    await Promise.all([query.refetch(), queryClient.invalidateQueries({queryKey:taskKeys.list(props.organizationId, props.projectId), exact:true})]);
  }
  return <section className="project-task-graph" aria-label="真实任务节点图" aria-busy={query.isFetching}>
    <div className="task-graph-toolbar">
      <div><h3>任务节点图</h3><p>箭头从前置任务指向后续任务。点击节点查看与编辑任务。</p></div>
      <div className="task-graph-controls">
        <button type="button" aria-label="缩小节点图" disabled={zoom <= .5} onClick={()=>setZoom(value=>value-.25)}><Minus size={16} aria-hidden="true"/></button>
        <output aria-label="节点图缩放比例">{Math.round(zoom*100)}%</output>
        <button type="button" aria-label="放大节点图" disabled={zoom >= 1.5} onClick={()=>setZoom(value=>value+.25)}><Plus size={16} aria-hidden="true"/></button>
        <button type="button" disabled={query.isFetching || props.disabled} onClick={()=>void refresh()}><RefreshCw size={16} aria-hidden="true"/>{query.isFetching ? "正在读取" : "刷新节点图"}</button>
      </div>
    </div>
    {query.isFetching || query.isPending ? <p role="status">正在读取完整项目节点图…</p>
      : query.isError ? <div className="task-graph-error"><p role="alert">{query.error instanceof Error ? query.error.message : "节点图读取失败"}</p><button type="button" onClick={()=>void query.refetch()}>重新读取节点图</button></div>
      : <GraphDrawing graph={query.data} zoom={zoom} selectedTaskId={props.selectedTaskId} disabled={props.disabled} onOpenTask={props.onOpenTask}/>}
  </section>;
}

function GraphDrawing({graph, zoom, selectedTaskId, disabled, onOpenTask}: {
  graph: GraphSnapshot; zoom: number; selectedTaskId: string | null; disabled: boolean; onOpenTask(id:string):void;
}) {
  const arrowId = useId();
  let layout: ReturnType<typeof layoutTaskGraph>;
  try { layout = layoutTaskGraph(graph); }
  catch (error) { return <p role="alert">{error instanceof Error ? error.message : "任务图数据无效"}</p>; }
  if (!graph.tasks.length) return <p className="task-graph-empty">还没有任务。创建任务后，它会出现在列表和节点图中。</p>;
  const milestones = new Map(graph.milestones.map(item=>[item.id,item]));
  const done = graph.tasks.filter(task=>task.status === "done").length;
  const blocked = graph.tasks.filter(task=>task.status === "blocked").length;
  return <>
    <div className="task-graph-summary"><span>已完成 {done} / {graph.tasks.length}</span><span>状态阻塞 {blocked}</span><span>{graph.dependencies.length} 条依赖</span><span>完整项目 · 版本 {graph.project.revision}</span></div>
    <p className="task-graph-help">可横向与纵向滚动。“前置未完成”是依赖提示，不改变任务的实际状态。</p>
    <div className="task-graph-scroll" tabIndex={0} aria-label="任务节点图画布，可横向与纵向滚动">
      <div style={{width:layout.width*zoom,height:layout.height*zoom}}>
        <div className="task-graph-canvas" style={{width:layout.width,height:layout.height,transform:`scale(${zoom})`}}>
          {layout.lanes.map(lane=><div className="task-graph-lane" key={lane.id ?? "unassigned"} style={{top:lane.y,height:lane.height,width:layout.width}}>
            <div className="task-graph-lane-label" id={`${arrowId}-stage-${lane.id ?? "unassigned"}`}><h4>{lane.name}</h4>{lane.archived && <span>已归档</span>}<span>{lane.done} / {lane.nodes.length} 已完成</span></div>
          </div>)}
          <svg className="task-graph-lines" width={layout.width} height={layout.height} aria-hidden="true">
            <defs><marker id={arrowId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="var(--color-muted)"/></marker></defs>
            {layout.edges.map(edge=>{
              const sx=edge.source.x+GRAPH_NODE_WIDTH, sy=edge.source.y+66, tx=edge.target.x-4, ty=edge.target.y+66;
              const path = tx-sx > 100
                ? `M ${sx} ${sy} H ${sx+18} V ${edge.source.y-14} H ${tx-18} V ${ty} H ${tx}`
                : `M ${sx} ${sy} C ${sx+24} ${sy}, ${tx-24} ${ty}, ${tx} ${ty}`;
              return <path className="task-graph-edge" key={edge.id} data-active={edge.predecessorTaskId===selectedTaskId || edge.successorTaskId===selectedTaskId} d={path} markerEnd={`url(#${arrowId})`}/>;
            })}
          </svg>
          {layout.nodes.map(({task,x,y,unfinishedPredecessors})=><button type="button" className="task-graph-node" key={task.id} disabled={disabled} data-status={task.status} data-selected={task.id===selectedTaskId} style={{left:x,top:y}} aria-label={`查看任务：${task.title}，${STATUS[task.status]}`} aria-describedby={`${arrowId}-stage-${task.stageId ?? "unassigned"}`} title={task.title} onClick={()=>onOpenTask(task.id)}>
            <strong>{task.title}</strong>
            <span className="task-graph-milestone">{task.milestoneId ? milestones.get(task.milestoneId)!.name : "未设置里程碑"}</span>
            <span className="task-graph-node-state">{STATUS[task.status]}</span>
            {unfinishedPredecessors>0 && <span className="task-graph-waiting">前置未完成 {unfinishedPredecessors}</span>}
          </button>)}
        </div>
      </div>
    </div>
    <p className="task-graph-read-at">读取时间：{new Date(graph.readAt).toLocaleTimeString("zh-CN",{hour12:false})}。其他窗口的修改可通过刷新读取。</p>
  </>;
}
