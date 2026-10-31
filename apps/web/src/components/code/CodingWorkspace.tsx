import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import type { AssistantSettings } from '../../api/assistantSkills.ts';
import { fetchFileTree } from '../../api/workspace.ts';
import { useSession } from '../../session/SessionContext.tsx';
import { CodingPanel, type AgentComparison } from './CodingPanel.tsx';
import { RepositoryEditorPanel } from './RepositoryEditorPanel.tsx';
import { isDirty, useEditorSession } from './editorSession.ts';

export function CodingWorkspace({ projectId, localPath, assistant, modelName, onConnection }: {
  projectId: string; localPath: string; assistant?: AssistantSettings; modelName?: string; onConnection: () => void;
}) {
  const { session } = useSession();
  const editors = useEditorSession(session!.signal, projectId);
  const [comparison, setComparison] = useState<AgentComparison | null>(null);
  const [finished, setFinished] = useState<string | null>(null);
  const tree = useQuery({ queryKey: ['editor-tree', session!.generation, projectId, localPath], retry: false,
    queryFn: ({ signal }) => fetchFileTree(projectId, AbortSignal.any([signal, session!.signal])) });
  return <div className="code-editor-with-agent">
    <RepositoryEditorPanel projectId={projectId} localPath={localPath} onConnection={onConnection} agentComparison={comparison} refreshVersion={finished} />
    <CodingPanel projectId={projectId} localPath={localPath} workspaceId={tree.data?.workspaceId} assistant={assistant} modelName={modelName} dirty={editors.tabs.some(isDirty)} onCompare={setComparison} onFinished={setFinished} />
  </div>;
}
