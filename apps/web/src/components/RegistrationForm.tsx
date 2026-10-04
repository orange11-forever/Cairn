import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Mail } from "lucide-react";
import { register, registrationAvailability, resendRegistration } from "../api/registration.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { validateEmail } from "../lib/validation.ts";
import { FormField, fieldAria } from "./FormField.tsx";
import { RegistrationLayout } from "./RegistrationLayout.tsx";

const passwordError = (value: string) => Array.from(value).length < 12 ? "密码至少 12 位" : Array.from(value).length > 128 ? "密码最多 128 位" : null;
export function RegistrationForm() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [availabilityError, setAvailabilityError] = useState(false);
  const [availabilityGeneration, setAvailabilityGeneration] = useState(0);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [errors, setErrors] = useState<{ email: string | null; password: string | null }>({ email: null, password: null });
  const [pendingReceipt, setPendingReceipt] = useState<string | null>(null);
  const [resendPassword, setResendPassword] = useState("");
  const [message, setMessage] = useState("");
  const [retryAt, setRetryAt] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const submitted = useRef(false);
  const send = useAbortableAction(register);
  const resend = useAbortableAction(resendRegistration);

  useEffect(() => {
    const controller = new AbortController();
    setAvailabilityError(false);
    void registrationAvailability(controller.signal).then(result => {
      if (!controller.signal.aborted) setEnabled(result.enabled);
    }).catch(() => { if (!controller.signal.aborted) setAvailabilityError(true); });
    return () => controller.abort();
  }, [availabilityGeneration]);
  useEffect(() => {
    if (!retryAt) return;
    const update = () => setSeconds(Math.max(0, Math.ceil((retryAt - Date.now()) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [retryAt]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); submitted.current = true;
    const next = { email: validateEmail(email), password: passwordError(password) };
    setErrors(next);
    if (next.email || next.password) {
      document.getElementById(next.email ? "register-email" : "register-password")?.focus(); return;
    }
    const result = await send.run({ email, password, displayName: displayName || null });
    if (!result) return;
    setPendingReceipt(result.registrationReceipt);
    setPassword("");
    setMessage(result.message);
    setRetryAt(Date.now() + result.resendAfterSeconds * 1000);
  }
  async function resendMail(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const invalid = passwordError(resendPassword);
    setErrors({ email: null, password: invalid });
    if (invalid) { document.getElementById("resend-password")?.focus(); return; }
    const result = await resend.run({ email: email.trim(), password: resendPassword, registrationReceipt: pendingReceipt! });
    if (result) {
      setResendPassword("");
      setMessage(result.message); setRetryAt(Date.now() + result.resendAfterSeconds * 1000);
    }
  }
  useEffect(() => {
    const failure = pendingReceipt ? resend.state : send.state;
    if (failure.phase === "error" && failure.error.retryAfterSeconds) setRetryAt(Date.now() + failure.error.retryAfterSeconds * 1000);
  }, [pendingReceipt, resend.state, send.state]);

  return <RegistrationLayout>
    <h1>{pendingReceipt ? "查收验证邮件" : "创建 Cairn 账号"}</h1>
    {availabilityError ? <><p className="form-error" role="alert">暂时无法检查注册状态，请重试。</p><button className="retry-btn" type="button" onClick={() => setAvailabilityGeneration(value => value + 1)}>重试</button></>
      : enabled === null ? <p role="status">正在检查注册状态…</p>
      : !enabled ? <p role="status">暂时无法注册，请稍后再试。</p>
      : pendingReceipt ? <>
        <p>验证邮件将发送到 <strong className="registration-email">{email.trim()}</strong>。打开邮件链接，输入注册时的密码，确认后再登录。</p>
        <p className="registration-notice" role="status">{message}</p>
        <form className="login-form" noValidate onSubmit={resendMail}>
          <FormField id="resend-password" label="注册时的密码" hint="重发前请重新输入密码；邮箱和密码不会被修改。" error={errors.password}>
            <input id="resend-password" disabled={resend.pending} type="password" autoComplete="current-password" maxLength={256} value={resendPassword} onChange={event => { setResendPassword(event.target.value); setErrors({ email: null, password: null }); resend.reset(); }} {...fieldAria("resend-password", errors.password, true)} />
          </FormField>
          {resend.state.phase === "error" && <p className="form-error" role="alert">{resend.state.error.message}</p>}
          <button className="login-submit" type="submit" disabled={resend.pending || seconds > 0}>{resend.pending ? "正在发送…" : seconds > 0 ? `重新发送（${seconds} 秒后）` : "重新发送验证邮件"}</button>
        </form>
        <p>未收到邮件？请检查垃圾邮件，或稍后重新发送。链接有效期为 30 分钟。</p>
      </> : <>
        <p>验证邮箱后，拥有自己的个人账号和知识空间。</p>
        <form className="login-form" noValidate onSubmit={submit}>
          <FormField id="register-email" label="邮箱" error={errors.email}>
            <input id="register-email" disabled={send.pending} type="email" name="email" autoComplete="email" maxLength={320} value={email} onChange={event => { setEmail(event.target.value); send.reset(); if (submitted.current) setErrors(value => ({ ...value, email: validateEmail(event.target.value) })); }} {...fieldAria("register-email", errors.email)} />
          </FormField>
          <FormField id="register-password" label="密码" hint="12–128 位，验证时需要再次输入。" error={errors.password}>
            <input id="register-password" disabled={send.pending} type="password" name="password" autoComplete="new-password" maxLength={256} value={password} onChange={event => { setPassword(event.target.value); send.reset(); if (submitted.current) setErrors(value => ({ ...value, password: passwordError(event.target.value) })); }} {...fieldAria("register-password", errors.password, true)} />
          </FormField>
          <FormField id="register-display-name" label="显示名（选填）" error={null}>
            <input id="register-display-name" disabled={send.pending} name="displayName" autoComplete="nickname" maxLength={120} value={displayName} onChange={event => setDisplayName(event.target.value)} />
          </FormField>
          {send.state.phase === "error" && <p className="form-error" role="alert">{send.state.error.message}</p>}
          <button className="login-submit" type="submit" disabled={send.pending || seconds > 0}><Mail aria-hidden="true" size={17} />{send.pending ? "正在发送…" : seconds > 0 ? `请等待 ${seconds} 秒` : "发送验证邮件"}</button>
        </form>
      </>}
    <a className="registration-login-link" href="/login">返回登录</a>
    {pendingReceipt && <Link className="registration-login-link" to="/register" onClick={() => { resend.cancel(); send.cancel(); setPendingReceipt(null); setResendPassword(""); setErrors({ email: null, password: null }); setRetryAt(0); setSeconds(0); }}>使用其他邮箱</Link>}
  </RegistrationLayout>;
}
