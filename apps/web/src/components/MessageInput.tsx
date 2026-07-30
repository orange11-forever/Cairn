// 提问输入框。受控组件，Day 9 补上校验、可读错误、提交中禁用、字数提示。
//
// Day 8 版本只判 `trim() === ""` 并且**安静地什么都不做**。那个行为当时标了
// 「今天只做到能收集能提交」，今天要还这笔账：用户按了发送而什么都没发生，
// 他不知道是自己的问题还是系统坏了。沉默是最差的一种错误处理。
//
// 受控组件的机制（Day 8 已讲，这里不重复）：
//   value={draft} 说"你显示的必须是这个值"，onChange 说"用户想改时去改 state"。
//   少了 onChange 输入框会变成只读——每次渲染 React 都把 value 重置回 state 的值。

import { useState } from "react";

import { FormField, fieldAria } from "./FormField.tsx";
import { QUESTION_MAX_LENGTH, validateQuestion } from "../lib/validation.ts";

interface MessageInputProps {
  /** 提交时把问题文本交出去。父组件决定拿它做什么。 */
  onSubmit: (text: string) => void;
  /** 是否正在等回答。由父组件（持有请求的那个）传进来。 */
  pending?: boolean;
  /** 取消在飞的请求。pending 为 true 时才会显示对应按钮。 */
  onCancel?: () => void;
}

export function MessageInput({ onSubmit, pending = false, onCancel }: MessageInputProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  // 剩余字数。
  //
  // 直接算，**不用 useState + useEffect 同步**，也不用 useMemo。
  // 一次减法包 memo 的开销比减法本身大——useMemo 自己要存旧依赖、做比较、
  // 存旧结果，那些工作都不是免费的。
  // "派生值就地算"是默认做法，useMemo 是需要理由才用的例外（见 DocumentsPanel）。
  const remaining = QUESTION_MAX_LENGTH - draft.trim().length;

  function handleChange(value: string) {
    setDraft(value);
    // 错误的消失可以是即时的（同 LoginForm 里那条判断）：
    // 用户正在改，说明他已经知道有问题，红字继续挂着只是噪音。
    // 反过来不成立——没提交过就不该冒出错误，那是在骂他还没打完的字。
    if (error !== null) setError(validateQuestion(value));
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    // 必须阻止默认行为：form 的默认提交会让浏览器整页刷新，
    // 单页应用里那等于把所有 state 清零——包括 UploadZone 里已选的文件，
    // 以及 Day 9 之后的 session（登录状态在内存里，刷新就回登录页）。
    event.preventDefault();

    const problem = validateQuestion(draft);
    if (problem !== null) {
      setError(problem);
      // 焦点回到输入框：用户按回车提交时焦点可能已经不在那里，
      // 而他下一步唯一想做的事就是改这段文字。
      document.getElementById("question")?.focus();
      return;
    }

    setError(null);
    onSubmit(draft.trim());
    setDraft(""); // 提交后清空草稿，光标留在输入框里，方便连着问下一个
  }

  // ⚠️ 清空草稿写在上面那个函数里（响应事件），**不是** useEffect 监听 messages 变化。
  // 那个形状是本日「不该用 Effect」的第二个样本：
  // "提交成功后清空"是一个事件的后果，不是某个状态的派生。
  // 用 Effect 实现的话，父组件因为别的原因重渲染时也可能误触发清空。

  return (
    <form className="question-form" onSubmit={handleSubmit} noValidate>
      <FormField id="question" label="你的问题" error={error}>
        <input
          id="question"
          name="question"
          type="text"
          placeholder="例如：值班故障如何升级？"
          value={draft}
          onChange={(event) => handleChange(event.target.value)}
          // 等回答时禁用输入。
          //
          // 不禁用会怎样：用户在等待期间改了问题，回答到达时显示在他已经改掉的
          // 问题下面——他会以为系统答错了。这不是理论问题，慢网络下必然发生。
          // Day 14 做流式回答时会换成更好的处理（允许打断并重新提问）。
          disabled={pending}
          {...fieldAria("question", error)}
        />
      </FormField>

      <div className="question-actions">
        {/*
          disabled 只绑 pending，**不再绑 draft.trim() === ""**。
          这是 Day 8 那一行的反转，理由变了：
            Day 8 没有错误提示，所以按钮必须先禁用，否则点了没反应像坏了。
            Day 9 有了可读错误，让用户点下去并**看到一句解释**比拦着他更有用——
            禁用的按钮不解释自己为什么禁用，这对读屏用户尤其不友好
            （他只听到"按钮，不可用"，不知道缺什么）。
          原则：能给出理由的时候给理由，给不出理由才禁用。
        */}
        <button type="submit" disabled={pending}>
          {pending ? "正在回答…" : "发送问题"}
        </button>

        {/*
          停止生成。只在等回答时出现——一个常驻的灰色"停止"按钮
          会让用户以为随时有东西可以停。
          onCancel 可选所以要判空：这个组件在没有请求的场景里也能用（测试里就是）。
        */}
        {pending && onCancel !== undefined && (
          <button type="button" className="cancel-btn" onClick={onCancel}>
            停止生成
          </button>
        )}
      </div>

      {/*
        剩余字数。只在快到上限时才显示（还剩 50 字以内）。
        全程显示"还能输入 487 字"是噪音——用户写第一句话时不需要这个信息，
        而它一直占着一行空间。只在临界时出现，出现本身就是提示。

        aria-live="polite" 让读屏在数字变化时播报，但不打断用户正在听的内容。
        用 polite 而不是 assertive：字数不是紧急信息，assertive 会打断一切。
      */}
      {remaining <= 50 && (
        <p className="question-counter" aria-live="polite">
          {remaining >= 0 ? `还能输入 ${remaining} 字` : `超出 ${-remaining} 字`}
        </p>
      )}
    </form>
  );
}
