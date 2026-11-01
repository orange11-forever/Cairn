import { ArrowRight, FileCode2, Minus, Plus } from 'lucide-react';
import { useId, useMemo, useState } from 'react';
import type { ArchitectureAnalysis, RepositorySnapshot } from '../../api/workspace.ts';
import '../../../styles/architecture-graph.css';

type Graph = ArchitectureAnalysis['graph'];
const NODE_WIDTH = 196;
const NODE_HEIGHT = 84;

// Breadth-first columns keep the entry near its collaborators. Revisiting a
// node never changes its column, so cycles and disconnected modules remain visible.
function layout(graph: Graph) {
  const levels = new Map<string, number>();
  const roots = graph.nodes.filter(node => !graph.edges.some(edge => edge.target === node.id));
  function walk(ids: string[]) {
    const queue = [...ids];
    ids.forEach(id => levels.set(id, 0));
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i]!;
      for (const edge of graph.edges.filter(edge => edge.source === id)) {
        if (!levels.has(edge.target)) {
          levels.set(edge.target, levels.get(id)! + 1);
          queue.push(edge.target);
        }
      }
    }
  }
  walk(roots.map(node => node.id));
  for (const node of graph.nodes) if (!levels.has(node.id)) walk([node.id]);
  const rows = new Map<number, number>();
  const nodes = graph.nodes.map(node => {
    const level = levels.get(node.id)!;
    const row = rows.get(level) ?? 0;
    rows.set(level, row + 1);
    return { ...node, x: 32 + level * 300, y: 64 + row * 156 };
  });
  return { nodes, width: Math.max(580, ...nodes.map(node => node.x + NODE_WIDTH + 84)),
    height: Math.max(300, ...nodes.map(node => node.y + NODE_HEIGHT + 76)) };
}

export function ArchitectureGraph({ graph, sources, onSource }: {
  graph: Graph; sources: RepositorySnapshot['sources']; onSource: (id: string) => void;
}) {
  const arrowId = useId();
  const [zoom, setZoom] = useState(1);
  const [selection, setSelection] = useState<{ kind: 'node'; id: string } | { kind: 'edge'; index: number } | null>(null);
  const drawing = useMemo(() => layout(graph), [graph]);
  const node = selection?.kind === 'node' ? graph.nodes.find(item => item.id === selection.id) : undefined;
  const edge = selection?.kind === 'edge' ? graph.edges[selection.index] : undefined;
  const nodeName = (id: string) => graph.nodes.find(item => item.id === id)!.label;
  const evidence = node?.citationIds ?? edge?.citationIds ?? [];
  return <section className="architecture-graph" aria-label="源码架构节点图">
    <div className="architecture-graph-heading">
      <div><h3>模块关系</h3><span>{graph.nodes.length} 个模块 · {graph.edges.length} 条关系</span></div>
      <div className="architecture-graph-zoom" role="group" aria-label="架构图缩放">
        <button type="button" aria-label="缩小架构图" disabled={zoom <= .5} onClick={() => setZoom(value => value - .25)}><Minus size={15} aria-hidden="true" /></button>
        <button type="button" aria-label="重置架构图缩放" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
        <button type="button" aria-label="放大架构图" disabled={zoom >= 1.5} onClick={() => setZoom(value => value + .25)}><Plus size={15} aria-hidden="true" /></button>
      </div>
    </div>
    <p className="architecture-graph-help">箭头表示关系方向。实线：源码依据；虚线：Agent 推断。两者均由模型标注，可点选核对引用。</p>
    <div className="architecture-graph-scroll" tabIndex={0} aria-label="架构图画布，可横向与纵向滚动">
      <div style={{ width: drawing.width * zoom, height: drawing.height * zoom }}>
        <div className="architecture-graph-canvas" style={{ width: drawing.width, height: drawing.height, transform: `scale(${zoom})` }}>
          <svg width={drawing.width} height={drawing.height} className="architecture-graph-lines" role="group" aria-label="模块之间的关系">
            <defs><marker id={arrowId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
            {graph.edges.map((item, index) => {
              const from = drawing.nodes.find(value => value.id === item.source)!;
              const to = drawing.nodes.find(value => value.id === item.target)!;
              const forward = to.x > from.x;
              let path: string, labelX: number, labelY: number;
              if (forward) {
                const x1 = from.x + NODE_WIDTH, x2 = to.x, y1 = from.y + 42, y2 = to.y + 42;
                const mid = (x1 + x2) / 2;
                path = `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
                labelX = mid; labelY = (y1 + y2) / 2 - 10;
              } else if (to.x === from.x) {
                const x = from.x + NODE_WIDTH, bend = x + 48, y1 = from.y + 42, y2 = to.y + 42;
                path = `M${x},${y1} C${bend},${y1} ${bend},${y2} ${x},${y2}`;
                labelX = bend; labelY = (y1 + y2) / 2;
              } else {
                const x1 = from.x + NODE_WIDTH / 2, x2 = to.x + NODE_WIDTH / 2;
                const top = Math.min(from.y, to.y) - 30;
                path = `M${x1},${from.y} C${x1},${top} ${x2},${top} ${x2},${to.y}`;
                labelX = (x1 + x2) / 2; labelY = top - 2;
              }
              const active = edge === item || node?.id === item.source || node?.id === item.target;
              return <g key={`${item.source}:${item.target}`} className="architecture-graph-edge" data-active={active} data-basis={item.basis}
                role="button" tabIndex={0} aria-label={`查看关系：${nodeName(item.source)} → ${nodeName(item.target)}，${item.label}`} aria-pressed={edge === item} onClick={() => setSelection({ kind: 'edge', index })} onKeyDown={event => {
                  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelection({ kind: 'edge', index }); }
                }}>
                <title>{item.label}</title>
                <path d={path} className="architecture-graph-edge-line" markerEnd={`url(#${arrowId})`} aria-hidden="true" />
                <path d={path} className="architecture-graph-edge-hit" aria-hidden="true" />
                <rect x={labelX - 58} y={labelY - 18} width={116} height={32} className="architecture-graph-edge-label-hit" aria-hidden="true" />
                <text x={labelX} y={labelY} textAnchor="middle" aria-hidden="true">{item.label.length > 10 ? `${item.label.slice(0, 9)}…` : item.label}</text>
              </g>;
            })}
          </svg>
          {drawing.nodes.map(item => <button key={item.id} type="button" className="architecture-graph-node" style={{ left: item.x, top: item.y, width: NODE_WIDTH, height: NODE_HEIGHT }} aria-label={`查看模块：${item.label}`} aria-pressed={node?.id === item.id} onClick={() => setSelection({ kind: 'node', id: item.id })} title={item.label}>
            <strong>{item.label}</strong><span>{item.citationIds.length} 处源码引用<ArrowRight size={13} aria-hidden="true" /></span>
          </button>)}
        </div>
      </div>
    </div>
    {node || edge ? <section className="architecture-graph-detail" aria-label={node ? '所选架构模块' : '所选架构关系'}>
      <div className="architecture-graph-detail-title"><h4>{node?.label ?? `${nodeName(edge!.source)} → ${nodeName(edge!.target)}`}</h4>{edge && <span>{edge.basis === 'direct' ? '源码依据 · 模型标注' : 'Agent 推断 · 待核对'}</span>}</div>
      <p>{node?.description ?? edge?.label}</p>
      <div className="code-citations">{evidence.map(id => { const source = sources.find(item => item.id === id)!; return <button key={id} type="button" aria-label={`查看${node ? '节点' : '关系'}依据 ${id}：${source.path}`} onClick={() => onSource(id)}><FileCode2 size={12} aria-hidden="true" />{source.path}<span>L{source.startLine}–{source.endLine}</span></button>; })}</div>
      {node && <ul className="architecture-graph-related">{graph.edges.map((item, index) => item.source === node.id || item.target === node.id ? <li key={index}><button type="button" onClick={() => setSelection({ kind: 'edge', index })}>{nodeName(item.source)}<ArrowRight size={13} aria-hidden="true" />{nodeName(item.target)}<span>{item.label}{item.basis === 'inferred' ? ' · 推断' : ''}</span></button></li> : null)}</ul>}
    </section> : <p className="architecture-graph-hint">选择一个模块或关系，查看职责、方向和源码依据。画布可滚动、缩放，键盘 Tab 可逐项选择。</p>}
    {graph.edges.length === 0 && <p className="architecture-graph-hint">当前片段尚不足以确认模块之间的关系，因此未生成连线。</p>}
  </section>;
}
