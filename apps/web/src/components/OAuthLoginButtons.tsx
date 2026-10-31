import { startOAuth, type OAuthProvider } from "../api/oauth.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { GitHubDeviceAuthorization } from "./GitHubDeviceAuthorization.tsx";

export function OAuthLoginButtons({ navigate = (url: string) => window.location.assign(url) }: {
  navigate?: (url: string) => void;
}) {
  const action = useAbortableAction(startOAuth);
  const desktop = (window as Window & { chrome?: { webview?: unknown } }).chrome?.webview;
  if (desktop) return <div className="oauth-login">
    <GitHubDeviceAuthorization intent="login" label="使用 GitHub 登录" onComplete={() => navigate("/login?oauth=login_ready")} />
    <p>在系统浏览器完成 GitHub 授权后，返回 Cairn 确认登录。首次使用将创建个人账号和个人空间。</p>
    <p>飞书登录尚未启用；也可以使用本机邮箱账号登录。</p>
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
