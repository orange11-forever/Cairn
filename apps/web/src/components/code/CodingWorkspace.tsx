import { useQuery } from '@tanstack/react-query';
import { useRef, useState, type CSSProperties } from 'react';
import type { AssistantSettings } from '../../api/assistantSkills.ts';
import { fetchFileTree } from '../../api/workspace.ts';
import { useSession } from '../../session/SessionContext.tsx';
import { CodingPanel, type AgentComparison } from './CodingPanel.tsx';
import { RepositoryEditorPanel } from './RepositoryEditorPanel.tsx';
import { isDirty, useEditorSession } from './editorSession.ts';
import { TerminalPanel } from './TerminalPanel.tsx';
import { ResizeHandle } from '../ResizeHandle.tsx';

export function CodingWorkspace({ projectId, localPath, assistant, modelName, onConnection }: {
  projectId: string; localPath: string; assistant?: AssistantSettings; modelName?: string; onConnection: () => void;
}) {
  const { session } = useSession();
  const editors = useEditorSession(session!.signal, projectId);
  const [comparison, setComparison] = useState<AgentComparison | null>(null);
  const [finished, setFinished] = useState<string | null>(null);
  const workspace = useRef<HTMLDivElement>(null);
  const column = useRef<HTMLDivElement>(null);
  const agent = useRef<HTMLDivElement>(null);
  const terminal = useRef<HTMLDivElement>(null);
  const [agentWidth, setAgentWidth] = useState<number | null>(null);
  const [terminalHeight, setTerminalHeight] = useState<number | null>(null);
  const tree = useQuery({ queryKey: ['editor-tree', session!.generation, projectId, localPath], retry: false,
    queryFn: ({ signal }) => fetchFileTree(projectId, AbortSignal.any([signal, session!.signal])) });
  return <div className="code-editor-with-agent" ref={workspace} style={{ '--code-agent-width': agentWidth === null ? undefined : `${agentWidth}px` } as CSSProperties}>
    <div className="code-editor-column" ref={column} style={{ '--code-terminal-height': terminalHeight === null ? undefined : `${terminalHeight}px` } as CSSProperties}>
      <RepositoryEditorPanel projectId={projectId} localPath={localPath} onConnection={onConnection} agentComparison={comparison} refreshVersion={finished} />
      <ResizeHandle axis="y" direction={-1} className="code-height-resizer" label="调整编辑器和终端高度" pane={terminal} min={220} max={() => (column.current?.clientHeight ?? 0) - 268} onResize={setTerminalHeight} onReset={() => setTerminalHeight(null)} />
      <div className="code-terminal-pane" ref={terminal}><TerminalPanel projectId={projectId} localPath={localPath} workspaceId={tree.data?.workspaceId} branch={tree.data?.branch} /></div>
    </div>
    <ResizeHandle axis="x" direction={-1} className="code-agent-resizer" label="调整 Agent 面板宽度" pane={agent} min={240} max={() => (workspace.current?.clientWidth ?? 0) - 456} onResize={setAgentWidth} onReset={() => setAgentWidth(null)} />
    <div className="code-agent-pane" ref={agent}><CodingPanel projectId={projectId} localPath={localPath} workspaceId={tree.data?.workspaceId} assistant={assistant} modelName={modelName} dirty={editors.tabs.some(isDirty)} onCompare={setComparison} onFinished={setFinished} /></div>
  </div>;
}
