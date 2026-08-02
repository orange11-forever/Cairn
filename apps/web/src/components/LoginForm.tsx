// 登录表单。今天最完整的一个受控表单：字段校验 + 服务端错误 + 提交中状态。
//
// ---------------------------------------------------------------------------
// 这个组件是「两类错误」的完整样本，那个区别是今天最重要的产品级概念：
//
//   字段错误（fieldErrors）—— 前端自己就知道。邮箱没有 @、密码 6 位。
//                            显示在**出错的那个字段旁边**，因为用户要改的就是它。
//                            不发请求（发了也是白发，服务器会拒）。
//
//   服务端错误（action.state）—— 只有问过后端才知道。密码不对、服务器 500、断网。
//                             显示在**表单级别**（提交按钮附近），因为它不属于
//                             任何单个字段——密码不对不代表密码字段"填错了"，
//                             用户可能是邮箱记错了。
//
// 把服务端错误挂到密码字段上是个常见的错，后果是用户盯着密码反复改，
// 而真正错的是邮箱。
// ---------------------------------------------------------------------------

import { useState } from "react";

import { FormField, fieldAria } from "./FormField.tsx";
import { login } from "../api/auth.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { PASSWORD_MIN_LENGTH, validateEmail, validatePassword } from "../lib/validation.ts";
import type { UserDto } from "../schemas/users.ts";

interface LoginFormProps {
  /** 登录成功后把用户交出去。这个组件不决定登录后干什么。 */
  onSuccess: (user: UserDto) => void;
}

interface FieldErrors {
  email: string | null;
  password: string | null;
}

const NO_ERRORS: FieldErrors = { email: null, password: null };

export function LoginForm({ onSuccess }: LoginFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>(NO_ERRORS);

  // 是否已经提交过一次。
  //
  // 它决定校验的时机，而时机是「可读错误」标准里最容易做错的一条：
  //   提交前：不校验。用户刚敲下 "d" 就被告知"邮箱缺少 @"是在骂他还没打完的字。
  //   提交后：实时校验。这时他已经知道有问题，边改边看到错误消失是有帮助的。
  //
  // 换句话说：**错误的消失可以是即时的，错误的出现不行。**
  const [submitted, setSubmitted] = useState(false);

  const action = useAbortableAction(login);

  /**
   * 算出当前的字段错误。纯函数调用，不改 state。
   *
   * 刻意**不用** useEffect 监听 email/password 变化然后 setFieldErrors。
   * 那个形状是本日「不该用 Effect」的头号样本：
   *   1. 它多一次渲染——先渲染新的输入值，再渲染错误，中间那帧显示的是过期的错误。
   *   2. 它把"错误"变成了需要同步的第二份真相，而它完全可以从输入值算出来。
   *   3. 依赖数组漏一个字段就静默失效。
   * 派生数据不该进 state。这里连 useMemo 都不用——两个字符串的校验，
   * 包 memo 的开销比校验本身还大。
   */
  function computeErrors(): FieldErrors {
    return { email: validateEmail(email), password: validatePassword(password) };
  }

  /** 用户改输入时：只在已提交过的情况下重算错误，并清掉服务端错误。 */
  function handleChange(field: "email" | "password", value: string) {
    if (field === "email") setEmail(value);
    else setPassword(value);

    // 服务端错误一定要清。留着它就成了这个样子：
    // 用户被告知"邮箱或密码不正确"，改了密码，红字还在——
    // 他会以为改完还是错的，其实那条错误说的是上一次提交。
    if (action.state.phase === "error") action.reset();

    if (!submitted) return;

    // 重算时用**新值**，不能用 state 里的 email/password——
    // setState 不是立即生效的，这个函数里读到的还是旧值。
    // 这是 React 新手最常撞的第二堵墙（第一堵是受控组件忘了 onChange）。
    const next = field === "email" ? value : email;
    const nextPassword = field === "password" ? value : password;
    setFieldErrors({ email: validateEmail(next), password: validatePassword(nextPassword) });
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setSubmitted(true);

    const errors = computeErrors();
    setFieldErrors(errors);

    // 有字段错误就不发请求。省一次往返只是次要好处，
    // 主要好处是错误的归属清楚：这时候显示的一定是字段错误，
    // 用户不会同时看到"邮箱缺少 @"和"邮箱或密码不正确"两条互相矛盾的提示。
    if (errors.email !== null || errors.password !== null) {
      // 把焦点移到第一个出错的字段。
      //
      // 这不是锦上添花：键盘和读屏用户提交后焦点还在提交按钮上，
      // 他们得反向 tab 去找哪个字段错了。而"第一个错误字段"是他们下一步唯一想去的地方。
      //
      // 用 document.getElementById 而不是 ref：这里要按"哪个字段错了"动态选目标，
      // 用 ref 得为每个字段各存一个 ref 再写一串 if。DOM 查询在这种一次性的
      // 命令式操作里更直接，而且 id 本来就已经存在（label 的 htmlFor 要用）。
      const firstInvalid = errors.email !== null ? "login-email" : "login-password";
      document.getElementById(firstInvalid)?.focus();
      return;
    }

    const user = await action.run({ email, password });
    // undefined 表示失败或被取消。错误已经在 action.state 里，UI 会自己显示，
    // 这里只需要什么都不做——尤其不能调 onSuccess。
    if (user === undefined) return;

    onSuccess(user);
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <h1 id="login-title">登录 Cairn</h1>
        <p>用企业邮箱登录，查看属于你的知识文档。</p>

        {/*
          noValidate 关掉浏览器自带的表单校验。
          理由：浏览器的原生提示（"请填写此字段"）不可定制、不同浏览器文案不同、
          而且它会在我们自己的校验之前拦下提交，导致上面那套可读错误永远不显示。
          自己校验就要自己负责到底，两套机制并存只会互相打断。
        */}
        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <FormField id="login-email" label="邮箱" error={fieldErrors.email}>
            <input
              id="login-email"
              name="email"
              // type="email" 保留：手机上它会调出带 @ 的键盘，这是真实的体验收益。
              // 它自带的校验被 noValidate 关掉了，所以不会和我们的校验打架。
              type="email"
              autoComplete="email"
              placeholder="demo@cairn.dev"
              value={email}
              onChange={(event) => handleChange("email", event.target.value)}
              {...fieldAria("login-email", fieldErrors.email)}
            />
          </FormField>

          <FormField
            id="login-password"
            label="密码"
            error={fieldErrors.password}
            hint={`至少 ${PASSWORD_MIN_LENGTH} 位`}
          >
            <input
              id="login-password"
              name="password"
              type="password"
              // autoComplete="current-password" 让密码管理器正确识别这是登录而非注册。
              // 写错成 "new-password" 会让它提示用户"要不要生成一个新密码"——
              // 在登录页上那是个令人困惑的提示。
              autoComplete="current-password"
              value={password}
              onChange={(event) => handleChange("password", event.target.value)}
              {...fieldAria("login-password", fieldErrors.password, true)}
            />
          </FormField>

          {/*
            表单级错误。位置在提交按钮**上方**——放下方的话，
            在手机上它可能落在折叠线以下，用户点了提交只看到按钮闪一下，
            不知道下面出现了一条红字。
          */}
          {action.state.phase === "error" && (
            <p className="form-error" role="alert">
              {action.state.error.message}
              {/* 401 是不可重试的（密码错了，重试一万次还是错），
                  500/断网是可重试的。给用户看的引导因此不同。 */}
              {action.state.error.retryable && "（可以再试一次）"}
            </p>
          )}

          <button type="submit" className="login-submit" disabled={action.pending}>
            {/* 文案跟着状态变，而不是只把按钮变灰。
                只变灰的话，慢网络下用户看到一个灰按钮，不知道是在提交
                还是表单坏了。一句"登录中…"消除这个歧义。 */}
            {action.pending ? "登录中…" : "登录"}
          </button>
        </form>

        {/* 演示账号是 mock 阶段的临时便利，接入真实鉴权时必须移除。 */}
        <p className="login-demo-hint">
          演示账号：<code>demo@cairn.dev</code> / <code>cairn-demo-2026</code>
        </p>
      </section>
    </main>
  );
}
