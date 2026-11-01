import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { disconnectGitHub, fetchGitHubConnection } from "../api/workspace.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { useSession } from "../session/SessionContext.tsx";
import { GitHubDeviceAuthorization } from "./GitHubDeviceAuthorization.tsx";

export function GitHubRepositoryAccess() {
  const { session } = useSession();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const key = ["desktop-github", session?.generation];
  const query = useQuery({ queryKey: key, enabled: session !== null, retry: false,
    queryFn: ({ signal }) => fetchGitHubConnection(AbortSignal.any([signal, session!.signal])) });
  const disconnect = useAbortableAction(disconnectGitHub, session?.signal);
  if (!session) return null;
  async function refresh() {
    queryClient.removeQueries({ queryKey: ["github-repositories"] });
    await queryClient.invalidateQueries({ queryKey: key });
  }
  async function remove() {
    if (await disconnect.run(session!.identity.csrfToken)) { setConfirm(false); await refresh(); }
  }
  const connection = query.data;
  return <section className="github-repository-access" aria-label="GitHub 仓库授权">
    <h3>GitHub 仓库授权</h3>
    <p>登录与仓库访问分别授权。仓库授权包含私有仓库读写权限，实际可用范围由 GitHub 账号和组织权限决定。</p>
    {query.isPending && <p role="status">正在检查 GitHub 授权…</p>}
    {query.isError && <p className="form-error" role="alert">{query.error.message}</p>}
    {connection && <>
      <p>{connection.status === "connected" ? `已授权：${connection.account?.login}` : connection.account ? `上次授权账号：${connection.account.login}` : "尚未授权仓库访问"}</p>
      {connection.message && <p role="status">{connection.message}</p>}
      {!connection.configured ? <p>此安装包尚未配置 Cairn GitHub 授权应用，请联系发布方。仍可关联本地已有仓库。</p> : <GitHubDeviceAuthorization
        intent="repositories" csrfToken={session.identity.csrfToken} signal={session.signal}
        label={connection.account ? "重新授权仓库访问" : "授权仓库访问"} onComplete={() => void refresh()} disabled={disconnect.pending} />}
      {connection.account && (confirm ? <div className="repository-confirm">
        <p>清除此 Cairn 账号在本机保存的仓库授权？项目关联和代码文件会保留；如需在 GitHub 撤销授权，请前往 GitHub 应用设置。</p>
        <button type="button" disabled={disconnect.pending} onClick={() => void remove()}>确认清除授权</button>
        <button type="button" disabled={disconnect.pending} onClick={() => setConfirm(false)}>取消</button>
      </div> : <button type="button" onClick={() => setConfirm(true)}>清除本机仓库授权</button>)}
    </>}
    <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()}>刷新授权状态</button>
    {disconnect.state.phase === "error" && <p role="alert" className="form-error">{disconnect.state.error.message}</p>}
  </section>;
}
