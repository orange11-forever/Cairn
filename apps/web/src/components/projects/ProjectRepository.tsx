import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { bindRepository, fetchGitHubConnection, fetchGitHubRepositories, fetchWorkspace, unbindRepository } from "../../api/workspace.ts";
import { useAbortableAction } from "../../hooks/useAbortableAction.ts";
import { useSession } from "../../session/SessionContext.tsx";
import { GitHubRepositoryAccess } from "../GitHubRepositoryAccess.tsx";

type DesktopHost = {
  postMessage(value: string): void;
  addEventListener(type: "message", listener: (event: MessageEvent<unknown>) => void): void;
  removeEventListener(type: "message", listener: (event: MessageEvent<unknown>) => void): void;
};
function host() { return (window as Window & { chrome?: { webview?: DesktopHost } }).chrome?.webview; }

export function ProjectRepository({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const [open, setOpen] = useState(false);
  if (!host()) return null;
  return <details className="project-repository" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>代码仓库</summary>
    {open && <RepositoryEditor key={projectId} projectId={projectId} canWrite={canWrite} />}
  </details>;
}

function RepositoryEditor({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const { session } = useSession();
  const client = useQueryClient();
  const id = useId();
  const [mode, setMode] = useState<"existing" | "clone">("existing");
  const [path, setPath] = useState("");
  const [repositoryId, setRepositoryId] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [notice, setNotice] = useState("");
  const selecting = useRef(false);
  const scope = useRef(new AbortController());
  useEffect(() => () => scope.current.abort(), []);
  const combined = (signal: AbortSignal) => AbortSignal.any([signal, session!.signal, scope.current.signal]);
  const key = ["desktop-workspace", session?.generation, projectId];
  const current = useQuery({ queryKey: key, enabled: session !== null, retry: false,
    queryFn: ({ signal }) => fetchWorkspace(projectId, combined(signal)) });
  const connection = useQuery({ queryKey: ["desktop-github", session?.generation], enabled: session !== null, retry: false,
    queryFn: ({ signal }) => fetchGitHubConnection(combined(signal)) });
  const connected = connection.data?.status === "connected";
  const repositories = useInfiniteQuery({ queryKey: ["github-repositories", session?.generation, connection.data?.account?.id],
    enabled: connected && session !== null, retry: false, initialPageParam: 1,
    queryFn: ({ signal, pageParam }) => fetchGitHubRepositories(pageParam, combined(signal)),
    getNextPageParam: last => last.nextPage ?? undefined });
  const bind = useAbortableAction(bindRepository, session?.signal);
  const unbind = useAbortableAction(unbindRepository, session?.signal);
  const pending = bind.pending || unbind.pending;
  const items = connected ? repositories.data?.pages.flatMap(page => page.items) ?? [] : [];
  const selected = items.find(item => String(item.id) === repositoryId);
  useEffect(() => { setRepositoryId(""); }, [connection.data?.account?.id]);
  useEffect(() => {
    const native = host();
    function selectedFolder(event: MessageEvent<unknown>) {
      const value = event.data;
      if (!selecting.current || typeof value !== "object" || value === null || !("type" in value) || value.type !== "cairn:repository:folder") return;
      selecting.current = false;
      if (!("path" in value) || typeof value.path !== "string" || !value.path) return;
      const separator = value.path.includes("\\") ? "\\" : "/";
      setPath(mode === "clone" ? value.path.replace(/[\\/]$/, "") + separator + (selected?.fullName.split("/")[1] ?? "repository") : value.path);
    }
    native?.addEventListener("message", selectedFolder);
    return () => native?.removeEventListener("message", selectedFolder);
  }, [mode, selected?.fullName]);
  if (!session) return null;

  async function save() {
    setNotice("");
    const result = await bind.run({ projectId, csrfToken: session!.identity.csrfToken, localPath: path,
      mode, repositoryId: selected?.id ?? null });
    if (result) { setNotice(mode === "clone" ? "仓库已克隆并关联。" : "仓库关联已保存。"); await client.invalidateQueries({ queryKey: key }); }
  }
  async function remove() {
    if (await unbind.run({ projectId, csrfToken: session!.identity.csrfToken })) {
      setConfirm(false); setNotice("已解除关联，代码文件已保留。");
      await client.invalidateQueries({ queryKey: key });
    }
  }
  const binding = current.data?.binding;
  const error = bind.state.phase === "error" ? bind.state.error : unbind.state.phase === "error" ? unbind.state.error : null;
  return <div className="repository-editor" aria-busy={pending}>
    <p>为此项目选择本机工作目录。关联按当前 Cairn 账号保存。</p>
    {current.isPending && <p role="status">正在读取仓库关联…</p>}
    {current.isError && <p className="form-error" role="alert">{current.error.message}</p>}
    {current.data && <>
      {binding ? <dl className="repository-details">
        <div><dt>仓库</dt><dd>{binding.repository?.fullName ?? "本地仓库"}</dd></div>
        {binding.account && <div><dt>关联时的 GitHub 账号</dt><dd>{binding.account.login}</dd></div>}
        <div><dt>当前分支</dt><dd>{binding.branch ?? "分离的 HEAD"}</dd></div>
        <div><dt>本地位置</dt><dd>{binding.localPath}</dd></div>
      </dl> : <p>尚未关联代码仓库</p>}
      {current.data.message && <p role="status">{current.data.message}</p>}
      {!current.data.gitAvailable && <p role="alert" className="form-error">Cairn 缺少 Git 运行组件，请修复或更新安装。</p>}
    </>}
    <button type="button" disabled={current.isFetching || pending} onClick={() => void current.refetch()}>刷新仓库状态</button>
    <GitHubRepositoryAccess />
    {canWrite && current.data && <form className="repository-form" onSubmit={event => { event.preventDefault(); void save(); }}>
      <fieldset disabled={pending || !current.data.gitAvailable}>
        <legend>{binding ? "更换仓库关联" : "选择代码仓库"}</legend>
        <div className="repository-mode">
          <label><input type="radio" name={id + "mode"} checked={mode === "existing"} onChange={() => setMode("existing")} />关联本地已有仓库</label>
          <label><input type="radio" name={id + "mode"} checked={mode === "clone"} disabled={!connected} onChange={() => setMode("clone")} />克隆 GitHub 仓库</label>
        </div>
        {connected && <>
          <label htmlFor={id + "repo"}>GitHub 仓库</label>
          <select id={id + "repo"} value={repositoryId} onChange={event => setRepositoryId(event.target.value)} required={mode === "clone"}>
            <option value="">{mode === "clone" ? "请选择仓库" : "仅关联本地目录"}</option>
            {items.map(item => <option key={item.id} value={item.id}>{item.fullName} · {item.private ? "私有" : "公开"} · {item.canPush ? "可写入" : "只读"}</option>)}
          </select>
          {repositories.isPending && <p role="status">正在加载可访问仓库…</p>}
          {repositories.isError && <p role="alert" className="form-error">{repositories.error.message}</p>}
          {repositories.data && items.length === 0 && <p>当前授权下没有可访问的仓库，请检查 GitHub 组织授权。</p>}
          {repositories.hasNextPage && <button type="button" disabled={repositories.isFetchingNextPage} onClick={() => void repositories.fetchNextPage()}>加载更多仓库</button>}
          {repositories.isError && <button type="button" onClick={() => void repositories.refetch()}>重试读取仓库</button>}
        </>}
        <label htmlFor={id + "path"}>{mode === "clone" ? "新目录完整路径" : "本地仓库目录"}</label>
        <div className="repository-path">
          <input id={id + "path"} value={path} onChange={event => setPath(event.target.value)} required autoComplete="off" spellCheck={false} aria-describedby={id + "hint"} />
          <button type="button" onClick={() => { selecting.current = true; host()?.postMessage("cairn:repository:folder"); }}>{mode === "clone" ? "选择父目录…" : "选择目录…"}</button>
        </div>
        <p id={id + "hint"}>{mode === "clone" ? "填写尚不存在的新目录；克隆不会覆盖已有目录。" : "选择包含 .git 的仓库根目录。选择 GitHub 仓库后，origin 必须与之匹配。"}</p>
        {binding && <p>更换关联后，原目录和代码文件会保留。</p>}
        <button type="submit" disabled={!path.trim() || (mode === "clone" && !selected)}>{pending ? "正在处理…" : mode === "clone" ? "克隆并关联" : "关联本地仓库"}</button>
      </fieldset>
    </form>}
    {canWrite && binding && (confirm ? <div className="repository-confirm">
      <p>确认解除此项目的本机关联？代码文件会保留。</p>
      <button type="button" disabled={pending} onClick={() => void remove()}>确认解除关联</button>
      <button type="button" disabled={pending} onClick={() => setConfirm(false)}>取消</button>
    </div> : <button type="button" disabled={pending} onClick={() => setConfirm(true)}>解除关联</button>)}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="form-error" role="alert">{error.message}{error.traceId ? `（请求编号：${error.traceId}）` : ""}</p>}
  </div>;
}
