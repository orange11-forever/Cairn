import { startOAuth, type OAuthProvider } from "../api/oauth.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";

export function OAuthLoginButtons({ navigate = (url: string) => window.location.assign(url) }: {
  navigate?: (url: string) => void;
}) {
  const action = useAbortableAction(startOAuth);
  const desktop = (window as Window & { chrome?: { webview?: unknown } }).chrome?.webview;
  if (desktop) return <div className="oauth-login">
    <p>桌面版尚未接通 GitHub 和飞书登录。请创建邮箱账号，在本机登录使用；已有账号可直接登录。</p>
  </div>;
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
