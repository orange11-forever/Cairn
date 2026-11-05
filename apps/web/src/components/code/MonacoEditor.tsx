import { useEffect, useRef } from 'react';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';
import 'monaco-editor/esm/vs/editor/editor.all.js';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker.js?worker';

self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
monaco.editor.defineTheme('cairn-light', {
  base: 'vs', inherit: true,
  rules: [
    { token: 'comment', foreground: '64746A' },
    { token: 'keyword', foreground: '7352BA' },
    { token: 'string', foreground: 'A74C5E' },
    { token: 'number', foreground: '99651B' },
    { token: 'type', foreground: '246B91' },
  ],
  colors: {
    'editor.background': '#FFFFFF', 'editor.foreground': '#252633',
    'editor.lineHighlightBackground': '#F8F7FC', 'editor.lineHighlightBorder': '#F8F7FC',
    'editorLineNumber.foreground': '#807D91', 'editorLineNumber.activeForeground': '#6356CC',
    'editor.selectionBackground': '#EBE7FB', 'editorIndentGuide.background1': '#E9E6F2',
  },
});
monaco.editor.defineTheme('cairn-dark', {
  base: 'vs-dark', inherit: true,
  rules: [
    { token: 'comment', foreground: '8E9A9E' },
    { token: 'keyword', foreground: 'B4A7FF' },
    { token: 'string', foreground: 'B9CD8A' },
    { token: 'number', foreground: 'DBAA82' },
    { token: 'type', foreground: '79CBC0' },
  ],
  colors: {
    'editor.background': '#20212B', 'editor.foreground': '#ECECF3',
    'editor.lineHighlightBackground': '#292A37', 'editor.lineHighlightBorder': '#292A37',
    'editorLineNumber.foreground': '#9090A4', 'editorLineNumber.activeForeground': '#B4A7FF',
    'editor.selectionBackground': '#413A60', 'editorIndentGuide.background1': '#363746',
  },
});
const languages = import.meta.glob('/node_modules/monaco-editor/esm/vs/basic-languages/*/*.contribution.js', { eager: true });
void languages;
function language(path: string) {
  const name = path.split('/').pop() ?? path;
  return monaco.languages.getLanguages().find(item => item.filenames?.includes(name) || item.extensions?.includes('.' + name.split('.').pop()))?.id ?? 'plaintext';
}
export interface MonacoProps {
  path: string;
  value: string;
  original?: string;
  readOnly?: boolean;
  onChange?: (value: string) => void;
  onSave?: () => void;
}
export default function MonacoEditor({ path, value, original, readOnly = false, onChange, onSave }: MonacoProps) {
  const host = useRef<HTMLDivElement>(null);
  const latest = useRef({ onChange, onSave });
  latest.current = { onChange, onSave };
  const instance = useRef<monaco.editor.IStandaloneCodeEditor | monaco.editor.IStandaloneDiffEditor | null>(null);
  const model = useRef<monaco.editor.ITextModel | null>(null);
  useEffect(() => {
    const current = monaco.editor.createModel(value, language(path));
    model.current = current;
    const theme = () => monaco.editor.setTheme(document.documentElement.dataset.theme === 'dark' ? 'cairn-dark' : 'cairn-light');
    theme();
    const observer = new MutationObserver(theme);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const options: monaco.editor.IStandaloneEditorConstructionOptions = {
      automaticLayout: true, minimap: { enabled: false }, fontSize: 13, lineHeight: 21,
      scrollBeyondLastLine: false, readOnly, padding: { top: 14 }, tabSize: 2,
      ariaLabel: `代码编辑器 ${path}`, unicodeHighlight: { ambiguousCharacters: false },
    };
    let baseline: monaco.editor.ITextModel | undefined;
    if (original !== undefined) {
      baseline = monaco.editor.createModel(original, language(path));
      const diff = monaco.editor.createDiffEditor(host.current!, { ...options, readOnly: true, renderSideBySide: true, useInlineViewWhenSpaceIsLimited: true });
      diff.setModel({ original: baseline, modified: current });
      instance.current = diff;
    } else {
      const editor = monaco.editor.create(host.current!, { ...options, model: current });
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => latest.current.onSave?.());
      instance.current = editor;
    }
    const subscription = current.onDidChangeContent(() => latest.current.onChange?.(current.getValue()));
    return () => { subscription.dispose(); observer.disconnect(); instance.current?.dispose(); current.dispose(); baseline?.dispose(); instance.current = null; model.current = null; };
    // Document identity and view mode control lifetime; content updates preserve the cursor and undo stack.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, original]);
  useEffect(() => { if (model.current && model.current.getValue() !== value) model.current.setValue(value); }, [value]);
  useEffect(() => { instance.current?.updateOptions({ readOnly }); }, [readOnly]);
  return <div className="code-monaco" ref={host} />;
}
