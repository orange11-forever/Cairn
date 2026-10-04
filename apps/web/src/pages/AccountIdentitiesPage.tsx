import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchLinkedIdentities, fetchOAuthProviders, startOAuth, unlinkIdentity, type OAuthProvider } from "../api/oauth.ts";
import { OAuthNotice } from "../components/OAuthNotice.tsx";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { useSession } from "../session/SessionContext.tsx";

export function AccountIdentitiesPage() {
  const { session, logout, logoutError } = useSession();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const key = ["account-identities", session?.generation];
  const identities = useQuery({ queryKey: key, enabled: session !== null,
    queryFn: ({ signal }) => fetchLinkedIdentities(AbortSignal.any([signal, session!.signal])) });
  const providers = useQuery({ queryKey: ["oauth-providers", session?.generation], enabled: session !== null,
    queryFn: ({ signal }) => fetchOAuthProviders(AbortSignal.any([signal, session!.signal])) });
  const link = useAbortableAction(startOAuth, session?.signal);
  const unlink = useAbortableAction(unlinkIdentity, session?.signal);
  if (session === null) return null;
  const pending = link.pending || unlink.pending;
  const error = link.state.phase === "error" ? link.state.error : unlink.state.phase === "error" ? unlink.state.error : null;

  async function bind(provider: OAuthProvider) {
    if (session === null) return;
    const url = await link.run({ provider, intent: "link", csrfToken: session.identity.csrfToken });
    if (url !== undefined) window.location.assign(url);
  }
  async function remove(id: string) {
    if (session === null) return;
    await unlink.run({ id, csrfToken: session.identity.csrfToken });
    setConfirmId(null);
    await queryClient.invalidateQueries({ queryKey: key });
  }

  return <section className="identity-page" aria-labelledby="identity-title">
    <h1 id="identity-title">登录方式</h1>
    <p>把飞书和 GitHub 绑定到当前 Cairn 账号，使用任一种方式访问你的知识文档。</p>
    <p className="identity-account">当前账号：{session.user.displayName ?? session.user.email ?? "Cairn 用户"} · {session.user.email ?? "未提供邮箱"}</p>
    <OAuthNotice outcome={params.get("oauth")} />
    {identities.isPending || providers.isPending ? <p role="status">正在读取登录方式…</p> : null}
    {identities.isError || providers.isError ? <div>
      <p className="form-error" role="alert">暂时无法读取登录方式，请重试。</p>
      <button type="button" onClick={() => { void identities.refetch(); void providers.refetch(); }}>重试</button>
    </div> : null}
    {identities.data && providers.data && <>
      <ul className="identity-methods">
        <li><div><strong>邮箱密码</strong><p>{identities.data.passwordAvailable ? "可以使用" : "尚未设置"}</p></div></li>
        {providers.data.map(({ provider, enabled }) => {
          const linked = identities.data!.identities.filter(item => item.provider === provider);
          const name = provider === "github" ? "GitHub" : "飞书";
          return <li key={provider}><div><strong>{name}</strong>
            <p>{linked.length ? "已绑定" : "未绑定"}{!enabled ? " · 尚未启用" : ""}</p>
            {linked.map(item => <div key={item.id} className="identity-linked">
              <span>{item.displayName ?? name + "账号"}</span>
              {confirmId === item.id ? <div className="identity-confirm">
                <p>解绑后将无法用此账号登录。确认解绑？</p>
                <button type="button" disabled={pending} onClick={() => void remove(item.id)}>确认解绑</button>
                <button type="button" disabled={pending} onClick={() => setConfirmId(null)}>取消</button>
              </div> : <button type="button" disabled={pending} onClick={() => setConfirmId(item.id)}>解绑 {name}</button>}
            </div>)}
          </div>{linked.length === 0 && <button type="button" disabled={!enabled || pending}
            onClick={() => void bind(provider)}>绑定 {name}</button>}</li>;
        })}
      </ul>
      <p className="identity-help">绑定不会改变你的组织和权限。解绑时需保留至少一种可用的登录方式。</p>
    </>}
    {error && <p className="form-error" role="alert">{error.message}</p>}
    {(error?.code === "reauthentication_required" || error?.code === "oauth_session_invalid") &&
      <button type="button" disabled={pending} onClick={() => void logout()}>重新登录</button>}
    {logoutError && <p className="form-error" role="alert">{logoutError.message}</p>}
  </section>;
}
