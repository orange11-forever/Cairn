import { useEffect, useRef, useState } from "react";
import { verifyRegistration } from "../api/registration.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { FormField, fieldAria } from "./FormField.tsx";
import { RegistrationLayout } from "./RegistrationLayout.tsx";

export function EmailVerification() {
  const token = useRef(new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "");
  const [password, setPassword] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [verified, setVerified] = useState(false);
  const action = useAbortableAction(verifyRegistration);
  useEffect(() => {
    // Proofs remain only in component memory. Loading a page is never confirmation.
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  }, []);
  async function confirm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password) { setFieldError("请填写注册时的密码"); document.getElementById("verify-password")?.focus(); return; }
    const result = await action.run({ token: token.current, password });
    if (result) { token.current = ""; setPassword(""); setVerified(true); }
  }
  return <RegistrationLayout>
    <h1>{verified ? "邮箱已验证" : "验证邮箱"}</h1>
    {verified ? <><p role="status">账号和个人空间已创建。请使用邮箱和密码登录。</p><a className="registration-login-link" href="/login">前往登录</a></>
      : !/^[A-Za-z0-9_-]{1,128}$/.test(token.current) ? <><p>请重新打开邮件中的验证链接，或重新注册。</p><a className="registration-login-link" href="/register">重新注册</a></>
      : <><p>请输入你注册时设置的密码，再确认创建账号。验证完成后仍需登录。</p>
        <form className="login-form" onSubmit={confirm} noValidate>
          <FormField id="verify-password" label="注册时的密码" error={fieldError}>
            <input id="verify-password" disabled={action.pending} name="password" type="password" autoComplete="current-password" maxLength={256} value={password} onChange={event => { setPassword(event.target.value); setFieldError(null); action.reset(); }} {...fieldAria("verify-password", fieldError)} />
          </FormField>
          {action.state.phase === "error" && <p className="form-error" role="alert">{action.state.error.message}</p>}
          <button className="login-submit" type="submit" disabled={action.pending}>{action.pending ? "正在验证…" : "验证邮箱并创建账号"}</button>
        </form>
        <a className="registration-login-link" href="/register">重新注册</a>
      </>}
  </RegistrationLayout>;
}
