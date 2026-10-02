import { useState } from "react";
import { finalizeOAuthLogin, type IdentityContext } from "../api/auth.ts";
import { ApiError } from "../api/errors.ts";
import { useSession } from "../session/SessionContext.tsx";

export function OAuthFinalize({ onSuccess }: { onSuccess(identity: IdentityContext): void }) {
  const { restartLogin } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function complete() {
    setBusy(true); setError(null);
    try { onSuccess(await finalizeOAuthLogin(new AbortController().signal)); }
    catch (failure) { setError(failure instanceof ApiError ? failure.message : "暂时无法完成登录，请重试"); }
    finally { setBusy(false); }
  }
  return <main className="session-status-page"><section className="session-restore-error">
    <h1>第三方身份已验证</h1><p>确认后进入已绑定的 Cairn 账号。</p>
    {error && <p role="alert" className="form-error">{error}</p>}
    <button type="button" className="retry-btn" disabled={busy} onClick={() => void complete()}>{busy ? "正在登录…" : "完成登录"}</button>
    <button type="button" className="retry-btn" disabled={busy} onClick={() => void restartLogin()}>重新开始登录</button>
  </section></main>;
}
