import { useEffect, useState } from "react";
import { register, registrationAvailability } from "../api/registration.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { validateEmail } from "../lib/validation.ts";
import { RegistrationLayout } from "./RegistrationLayout.tsx";
import { FormField, fieldAria } from "./FormField.tsx";

export function RegistrationForm() {
  const [enabled,setEnabled]=useState<boolean|null>(null);
  const [availabilityError,setAvailabilityError]=useState(false);
  const [generation,setGeneration]=useState(0);
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [displayName,setDisplayName]=useState("");
  const [error,setError]=useState<string|null>(null);
  const [message,setMessage]=useState<string|null>(null);
  const action=useAbortableAction(register);
  useEffect(()=>{const controller=new AbortController();setAvailabilityError(false);void registrationAvailability(controller.signal).then(result=>{if(!controller.signal.aborted)setEnabled(result.enabled);}).catch(()=>{if(!controller.signal.aborted)setAvailabilityError(true);});return()=>controller.abort();},[generation]);
  async function submit(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();
    const invalid=validateEmail(email) || (Array.from(password).length<12 ? "密码至少 12 位" : Array.from(password).length>128 ? "密码最多 128 位" : null);
    setError(invalid);if(invalid)return;
    const result=await action.run({email,password,displayName:displayName||null});
    if(result){setPassword("");setMessage(result.message);}
  }
  return <RegistrationLayout>
    <h1>{message ? "注册成功" : "创建 Cairn 账号"}</h1>
    {message ? <><p role="status">{message}</p><a className="registration-login-link" href="/login">前往登录</a></>
    : availabilityError ? <><p role="alert">暂时无法检查注册状态，请重试。</p><button className="retry-btn" type="button" onClick={()=>setGeneration(value=>value+1)}>重试</button></>
    : enabled===null ? <p role="status">正在检查注册状态…</p>
    : !enabled ? <p role="status">暂时无法注册，请稍后再试。</p>
    : <><p>使用邮箱和密码直接创建个人账号。邮箱仅作为登录标识，不验证邮箱归属，也不会发送邮件。</p>
      <form className="login-form" noValidate onSubmit={submit}>
        <FormField id="register-email" label="邮箱" error={null}><input id="register-email" type="email" autoComplete="email" maxLength={320} disabled={action.pending} value={email} onChange={event=>{setEmail(event.target.value);setError(null);action.reset();}} /></FormField>
        <FormField id="register-password" label="密码" hint="12–128 位，请妥善保存。" error={error}><input id="register-password" type="password" autoComplete="new-password" maxLength={256} disabled={action.pending} value={password} onChange={event=>{setPassword(event.target.value);setError(null);action.reset();}} {...fieldAria("register-password",error,true)} /></FormField>
        <FormField id="register-display-name" label="显示名（选填）" error={null}><input id="register-display-name" autoComplete="nickname" maxLength={120} disabled={action.pending} value={displayName} onChange={event=>setDisplayName(event.target.value)} /></FormField>
        {action.state.phase==="error" && <p role="alert" className="form-error">{action.state.error.message}</p>}
        <button className="login-submit" type="submit" disabled={action.pending}>{action.pending ? "正在创建…" : "创建账号"}</button>
      </form></>}
    {!message && <a className="registration-login-link" href="/login">返回登录</a>}
  </RegistrationLayout>;
}
