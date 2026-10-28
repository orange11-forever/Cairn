import type { ProjectTaskGraph } from "../api/projects.ts";

export const GRAPH_NODE_WIDTH = 224;
export const GRAPH_NODE_HEIGHT = 132;
const COLUMN = 272;
const ROW = 156;

export function layoutTaskGraph(graph: ProjectTaskGraph) {
  const byId = new Map(graph.tasks.map(task => [task.id, task]));
  const predecessors = new Map(graph.tasks.map(task => [task.id, [] as string[]]));
  const successors = new Map(graph.tasks.map(task => [task.id, [] as string[]]));
  for (const edge of graph.dependencies) {
    predecessors.get(edge.successorTaskId)!.push(edge.predecessorTaskId);
    successors.get(edge.predecessorTaskId)!.push(edge.successorTaskId);
  }
  const remaining = new Map([...predecessors].map(([id, values]) => [id, values.length]));
  const levels = new Map(graph.tasks.map(task => [task.id, 0]));
  const queue = graph.tasks.filter(task => !remaining.get(task.id)).map(task => task.id);
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index]!;
    for (const next of successors.get(id)!) {
      levels.set(next, Math.max(levels.get(next)!, levels.get(id)! + 1));
      remaining.set(next, remaining.get(next)! - 1);
      if (remaining.get(next) === 0) queue.push(next);
    }
  }
  if (queue.length !== graph.tasks.length) throw new Error("任务依赖存在循环，无法绘制完整节点图。请检查依赖关系。");
  const stageOrder = [...graph.stages].sort((a,b) => a.position - b.position || a.id.localeCompare(b.id));
  const groups = [...stageOrder.map(stage => ({id:stage.id, name:stage.name, archived:stage.archived})),
    {id:null, name:"未设置阶段", archived:false}];
  let y = 0;
  const lanes = groups.flatMap(group => {
    const tasks = graph.tasks.filter(task => task.stageId === group.id);
    if (!tasks.length) return [];
    const rows = new Map<number, number>();
    const nodes = tasks.map(task => {
      const column = levels.get(task.id)!;
      const row = rows.get(column) ?? 0;
      rows.set(column, row + 1);
      return {task, x: 16 + column * COLUMN, y: y + 48 + row * ROW,
        unfinishedPredecessors: predecessors.get(task.id)!.filter(id => byId.get(id)!.status !== "done").length};
    });
    const height = Math.max(...rows.values()) * ROW + 64;
    const lane = {...group, y, height, nodes, done:tasks.filter(task => task.status === "done").length};
    y += height;
    return [lane];
  });
  const nodes = lanes.flatMap(lane => lane.nodes);
  const positions = new Map(nodes.map(node => [node.task.id, node]));
  const edges = graph.dependencies.map(edge => ({...edge,
    source:positions.get(edge.predecessorTaskId)!, target:positions.get(edge.successorTaskId)!}));
  return {lanes, nodes, edges, width:16 + (Math.max(0, ...levels.values()) + 1) * COLUMN, height:y};
}
