import { useEffect, useRef, useState } from "react";
import { cancelGitHubDevice, pollGitHubDevice, startGitHubDevice, type GitHubDeviceResult, type GitHubDeviceStarted } from "../api/workspace.ts";
import { ApiError } from "../api/errors.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { useSessionErrorReporter } from "../session/SessionContext.tsx";

export function GitHubDeviceAuthorization({ intent, label, csrfToken, signal, onComplete, disabled = false }: {
  intent: "login" | "link" | "repositories"; label: string; csrfToken?: string; signal?: AbortSignal;
  onComplete(result: GitHubDeviceResult): void; disabled?: boolean;
}) {
  const start = useAbortableAction(startGitHubDevice, signal);
  const cancel = useAbortableAction(cancelGitHubDevice, signal);
  const reportError = useSessionErrorReporter();
  const [attempt, setAttempt] = useState<(GitHubDeviceStarted & { deadline: number }) | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const complete = useRef(onComplete);
  complete.current = onComplete;
  useEffect(() => {
    if (!attempt) return;
    const controller = new AbortController();
    const currentSignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (currentSignal.aborted) return;
      try {
        if (Date.now() >= attempt!.deadline) throw new Error("验证码已过期，请重新发起授权。");
        const result = await pollGitHubDevice(attempt!.attemptId, csrfToken, currentSignal);
        if (currentSignal.aborted) return;
        if (result.status === "pending") timer = setTimeout(() => void poll(), result.interval * 1000);
        else { setAttempt(null); complete.current(result); }
      } catch (error) {
        if (currentSignal.aborted) return;
        reportError(error, currentSignal);
        setPollError(error instanceof Error ? error.message : "授权查询失败，请重新发起。");
        setAttempt(null);
      }
    }
    timer = setTimeout(() => void poll(), attempt.interval * 1000);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [attempt, csrfToken, signal, reportError]);

  async function begin() {
    setPollError(null); cancel.reset();
    const value = await start.run({ intent, csrfToken });
    if (value) setAttempt({ ...value, deadline: Date.now() + value.expiresIn * 1000 });
  }
  async function stop() {
    if (!attempt) return;
    const value = await cancel.run({ attemptId: attempt.attemptId, csrfToken });
    if (value) setAttempt(null);
  }
  function openAuthorization() {
    const host = (window as Window & { chrome?: { webview?: { postMessage(value: string): void } } }).chrome?.webview;
    if (host) host.postMessage("cairn:github:authorize");
    else window.open("https://github.com/login/device", "_blank", "noopener,noreferrer");
  }
  const error = pollError ?? (start.state.phase === "error" ? start.state.error.message : cancel.state.phase === "error" ? cancel.state.error.message : null);
  return <div className="github-device">
    {!attempt ? <button type="button" disabled={disabled || start.pending} onClick={() => void begin()}>{start.pending ? "正在请求验证码…" : label}</button> : <div className="github-device-prompt">
      <p>在 GitHub 授权页面输入验证码：</p>
      <strong className="github-device-code">{attempt.userCode}</strong>
      <p>验证码约 {Math.ceil(attempt.expiresIn / 60)} 分钟内有效。完成后会自动返回确认结果。</p>
      <div className="repository-actions">
        <button type="button" onClick={openAuthorization}>打开 GitHub 授权页面</button>
        <button type="button" disabled={cancel.pending} onClick={() => void stop()}>取消授权</button>
      </div>
      <p role="status">正在等待 GitHub 确认…</p>
    </div>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {start.state.phase === "error" && start.state.error instanceof ApiError && start.state.error.code === "reauthentication_required" && <p>请退出当前账号并重新登录后绑定。</p>}
  </div>;
}
