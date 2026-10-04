import { startOAuth, type OAuthProvider } from "../api/oauth.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";

export function OAuthLoginButtons({ navigate = (url: string) => window.location.assign(url) }: {
  navigate?: (url: string) => void;
}) {
  const action = useAbortableAction(startOAuth);
  async function begin(provider: OAuthProvider) {
    const url = await action.run({ provider, intent: "login" });
    if (url !== undefined) navigate(url);
  }
  return <div className="oauth-login">
    <p className="oauth-login-label">或使用第三方账号登录</p>
    <p>首次授权并确认后，将创建个人账号和个人空间。</p>
    <div className="oauth-login-actions">
      <button type="button" disabled={action.pending} onClick={() => void begin("github")}>使用 GitHub 登录</button>
      <button type="button" disabled={action.pending} onClick={() => void begin("feishu")}>使用飞书登录</button>
    </div>
    {action.state.phase === "error" && <p className="form-error" role="alert">{action.state.error.message}</p>}
  </div>;
}
