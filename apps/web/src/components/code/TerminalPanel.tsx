import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import { Eraser, Folder, GitBranch, Info, Play, Square, TerminalSquare } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { closeTerminal, fetchFileTree, fetchTerminal, resizeTerminal, startTerminal, writeTerminal, type TerminalSnapshot } from '../../api/workspace.ts';
import { useSession } from '../../session/SessionContext.tsx';
import '@xterm/xterm/css/xterm.css';
import '../../../styles/terminal.css';

export function TerminalPanel({ projectId, workspaceId, localPath, branch }: {
  projectId: string; workspaceId?: string; localPath: string; branch?: string | null;
}) {
  const { session } = useSession();
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const current = useRef<TerminalSnapshot | null>(null);
  const offset = useRef(0);
  const input = useRef<(data: string) => void>(() => {});
  const [snapshot, setSnapshot] = useState<TerminalSnapshot | null>(null);
  const [ready, setReady] = useState(false);
  const [allowed, setAllowed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState(0);
  const control = useRef<AbortController | null>(null);
  const running = snapshot?.status === 'running';

  useEffect(() => {
    if (!host.current || !session) return;
    const controller = new AbortController();
    control.current = controller;
    const signal = AbortSignal.any([controller.signal, session.signal]);
    let polling: ReturnType<typeof setTimeout> | undefined;
    let resizing: ReturnType<typeof setTimeout> | undefined;
    let sending = false;
    let queued = '';
    let suspended = false;
    const view = new Terminal({ cursorBlink: true, cursorStyle: 'bar', cursorWidth: 2, fontFamily: '"Cascadia Code", "JetBrains Mono", Consolas, "Liberation Mono", monospace', fontSize: 13, lineHeight: 1.5, scrollback: 2000, screenReaderMode: true, disableStdin: true, allowProposedApi: false });
    const fit = new FitAddon();
    view.loadAddon(fit);
    view.open(host.current);
    terminal.current = view;
    current.current = null;
    offset.current = 0;
    setReady(false);
    setError(null);

    function fail(cause: unknown) {
      if (signal.aborted) return;
      suspended = true;
      queued = '';
      view.options.disableStdin = true;
      setError(cause instanceof Error ? cause.message : '终端连接失败，请重新连接以核对会话状态。');
    }

    function theme() {
      if (!host.current) return;
      const styles = getComputedStyle(host.current);
      view.options.theme = {
        background: styles.getPropertyValue('--terminal-background').trim(),
        foreground: styles.getPropertyValue('--terminal-foreground').trim(),
        cursor: styles.getPropertyValue('--terminal-accent').trim(), selectionBackground: '#383452',
        black: '#1d2230', red: '#f587a3', green: '#9ac76f', yellow: '#e7bb79',
        blue: '#8caaf5', magenta: '#ab98ef', cyan: '#7bc5b4', white: '#e0e5ee',
        brightBlack: '#7d8ba7', brightRed: '#ff9cae', brightGreen: '#b9e58e', brightYellow: '#f3d398',
        brightBlue: '#a4baff', brightMagenta: '#c1b3ff', brightCyan: '#8de0c5', brightWhite: '#f5f7ff',
      };
    }

    async function send() {
      if (sending || suspended || signal.aborted) return;
      sending = true;
      try {
        while (queued && current.current?.status === 'running' && !signal.aborted) {
          const chunk = Array.from(queued).slice(0, 1024).join('');
          queued = queued.slice(chunk.length);
          await writeTerminal(projectId, current.current.id, chunk, session!.identity.csrfToken, signal);
        }
      } catch (cause) { fail(cause); }
      finally { sending = false; }
    }

    input.current = data => {
      if (suspended || signal.aborted || current.current?.status !== 'running') return;
      if (queued.length + data.length > 32768) { fail(new Error('待发送输入过长，请重新连接后分段粘贴。')); return; }
      queued += data;
      void send();
    };
    const onData = view.onData(data => input.current(data));
    view.attachCustomKeyEventHandler(event => {
      if (event.type === 'keydown' && event.ctrlKey && event.shiftKey && event.code === 'KeyC') {
        void navigator.clipboard.writeText(view.getSelection()).catch(fail);
        return false;
      }
      return true;
    });
    const onResize = view.onResize(({ cols, rows }) => {
      clearTimeout(resizing);
      resizing = setTimeout(() => {
        if (!suspended && current.current?.status === 'running') {
          void resizeTerminal(projectId, current.current.id, Math.min(cols, 500), Math.min(rows, 200), session.identity.csrfToken, signal).catch(fail);
        }
      }, 100);
    });
    const observer = new ResizeObserver(() => { if (host.current?.clientWidth) fit.fit(); });
    observer.observe(host.current);
    const themes = new MutationObserver(theme);
    themes.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });
    theme();
    if (host.current.clientWidth) fit.fit();

    async function poll() {
      try {
        const value = await fetchTerminal(projectId, offset.current, signal);
        if (signal.aborted) return;
        if (value?.id !== current.current?.id) {
          view.reset();
          queued = '';
          offset.current = 0;
          if (value?.status === 'running') {
            await resizeTerminal(projectId, value.id, Math.min(view.cols, 500), Math.min(view.rows, 200), session!.identity.csrfToken, signal);
          }
          if (value && value.startOffset > 0) {
            current.current = value;
            polling = setTimeout(() => void poll(), 0);
            return;
          }
        }
        if (value) {
          if (value.startOffset > offset.current) {
            view.reset();
            view.writeln('[较早输出已超出会话缓冲区，仅显示最近内容]');
          }
          if (value.output) await new Promise<void>(resolve => view.write(value.output, resolve));
          offset.current = value.nextOffset;
        }
        current.current = value;
        setSnapshot(value);
        setReady(true);
        view.options.disableStdin = suspended || value?.status !== 'running';
        if (!suspended) polling = setTimeout(() => void poll(), value?.status === 'running' ? 200 : 1000);
      } catch (cause) { fail(cause); }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(polling);
      clearTimeout(resizing);
      observer.disconnect();
      themes.disconnect();
      onData.dispose();
      onResize.dispose();
      view.dispose();
      terminal.current = null;
      input.current = () => {};
    };
  }, [projectId, localPath, session, connection]);

  async function start() {
    if (!session || !workspaceId || !control.current) return;
    setBusy(true);
    setError(null);
    try {
      const signal = AbortSignal.any([control.current.signal, session.signal]);
      const workspace = await fetchFileTree(projectId, signal);
      await startTerminal(projectId, { workspaceId: workspace.workspaceId, allowExecution: allowed, cols: Math.min(terminal.current?.cols ?? 100, 500), rows: Math.min(terminal.current?.rows ?? 24, 200) }, session.identity.csrfToken, signal);
      setConnection(value => value + 1);
    } catch (cause) { if (!control.current.signal.aborted) setError(cause instanceof Error ? cause.message : '无法启动终端'); }
    finally { setBusy(false); }
  }

  async function stop() {
    if (!session || !snapshot || !control.current) return;
    setBusy(true);
    control.current.abort();
    if (terminal.current) terminal.current.options.disableStdin = true;
    try {
      const result = await closeTerminal(projectId, snapshot.id, session.identity.csrfToken, session.signal);
      current.current = result;
      setSnapshot(result);
      if (terminal.current) terminal.current.options.disableStdin = true;
      setConnection(value => value + 1);
    } catch (cause) { if (!session.signal.aborted) setError(cause instanceof Error ? cause.message : '关闭终端失败'); }
    finally { setBusy(false); }
  }

  const status = error ? '连接异常' : !ready ? '正在连接' : !snapshot ? '未启动' : running ? '运行中' : snapshot.status === 'failed' ? '已中断' : snapshot.status === 'stopped' ? '已关闭' : `已退出 · ${snapshot.exitCode ?? '未知退出码'}`;
  return <section className="code-terminal" aria-label="项目交互终端" data-running={running}>
    <header className="terminal-toolbar">
      <h2><TerminalSquare size={16} aria-hidden="true" />终端</h2>
      {snapshot?.shell && <span className="terminal-shell">{snapshot.shell}</span>}
      <span className={`terminal-status${running ? ' is-running' : ''}${error ? ' is-error' : ''}`} role="status"><span aria-hidden="true" />{status}</span>
      <div className="terminal-actions">
        {snapshot && <button type="button" disabled={!ready} title="清除可见输出" onClick={() => terminal.current?.clear()}><Eraser size={14} aria-hidden="true" />清屏</button>}
        {running && <><button type="button" aria-label="中断 Ctrl+C" title="中断当前命令，保留会话" disabled={busy || !!error} onClick={() => { input.current('\x03'); terminal.current?.focus(); }}><Square size={11} aria-hidden="true" />中断<kbd>^C</kbd></button><button className="terminal-close" type="button" title="结束会话与子进程" disabled={busy} onClick={() => void stop()}>结束会话</button></>}
      </div>
    </header>
    {error && <div className="terminal-error" role="alert">{error}<button type="button" disabled={busy} onClick={() => setConnection(value => value + 1)}>重新连接</button></div>}
    {snapshot?.error && <p className="terminal-error" role="alert">{snapshot.error}</p>}
    <div className="terminal-surface">
      <div className="terminal-screen" ref={host} aria-label="终端输入与输出" hidden={!snapshot} />
      {ready && !snapshot && <div className="terminal-empty">
        <div className="terminal-prompt-preview"><span className="terminal-preview-path" title={localPath}><Folder size={14} aria-hidden="true" />{localPath}</span>{branch && <span className="terminal-preview-branch"><GitBranch size={13} aria-hidden="true" />{branch}</span>}</div>
        <div className="terminal-preview-input"><span aria-hidden="true">❯</span><p>确认执行权限后，开始输入命令。</p></div>
      </div>}
    </div>
    {ready && !running && <div className="terminal-start">
      <label><input type="checkbox" checked={allowed} onChange={event => setAllowed(event.target.checked)} />允许以当前系统用户权限执行我输入的命令。</label>
      <button type="button" disabled={!allowed || !workspaceId || busy || !!error} onClick={() => void start()}><Play size={13} aria-hidden="true" />{busy ? '正在启动…' : '启动终端'}</button>
    </div>}
    <footer className="terminal-footer">
      <span><kbd>Ctrl+C</kbd> 中断<span className="terminal-shortcut"><kbd>Ctrl+Shift+C</kbd> 复制</span></span>
      <details className="terminal-help"><summary><Info size={12} aria-hidden="true" />使用说明</summary><p>切换页面保留会话；退出账号或关闭应用会结束进程。拖动编辑器与终端之间的分隔线调整高度；窄屏可拖动命令区域右下角。终端中的文件修改需在编辑器中刷新查看。</p><p>项目目录：<code>{snapshot?.localPath ?? localPath}</code></p></details>
    </footer>
  </section>;
}
