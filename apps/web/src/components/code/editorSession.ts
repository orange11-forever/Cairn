import { useSyncExternalStore } from 'react';
import type { FileDocument } from '../../api/workspace.ts';

export interface EditorDraft {
  id: string;
  document: Omit<FileDocument, 'revision'> & { revision: string | null };
  content: string;
  savedRevision?: string;
}
interface ProjectEditors { tabs: EditorDraft[]; active: string | null; events: string[] }
const empty: ProjectEditors = { tabs: [], active: null, events: [] };
const stores = new WeakMap<AbortSignal, ReturnType<typeof createStore>>();
function createStore(signal: AbortSignal) {
  let projects = new Map<string, ProjectEditors>();
  const listeners = new Set<() => void>();
  const beforeUnload = (event: BeforeUnloadEvent) => {
    if ([...projects.values()].some(project => project.tabs.some(isDirty))) event.preventDefault();
  };
  window.addEventListener('beforeunload', beforeUnload);
  signal.addEventListener('abort', () => {
    projects = new Map();
    window.removeEventListener('beforeunload', beforeUnload);
    listeners.forEach(listener => listener());
  }, { once: true });
  return {
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    get(projectId: string) { return projects.get(projectId) ?? empty; },
    update(projectId: string, apply: (value: ProjectEditors) => ProjectEditors) {
      if (signal.aborted) return;
      projects.set(projectId, apply(projects.get(projectId) ?? empty));
      listeners.forEach(listener => listener());
    },
  };
}
export function isDirty(draft: EditorDraft) { return draft.document.revision === null || draft.content !== draft.document.content; }
export function useEditorSession(signal: AbortSignal, projectId: string) {
  let store = stores.get(signal);
  if (!store) { store = createStore(signal); stores.set(signal, store); }
  const snapshot = useSyncExternalStore(store.subscribe, () => store.get(projectId));
  return { ...snapshot, update: (apply: (value: ProjectEditors) => ProjectEditors) => store.update(projectId, apply) };
}
