// 提问输入框。持有自己的本地 state：还没提交的草稿。
//
// 这是「受控组件」：input 的值来自 state，不是 DOM 自己记着。
//   value={draft} 说"你显示的必须是这个值"
//   onChange 说"用户想改时，去改 state"
// 少了 onChange，输入框会变成只读——用户打字没反应，因为 React 每次渲染
// 都把 value 重置回 state 里那个值。这是刚上手 React 时最常撞的一堵墙，
// 而它其实是声明式渲染的直接后果：UI 是 state 的函数，不是可以被随手改的东西。
//
// Day 9 会正经讲受控表单（校验、错误提示、提交中禁用）。今天只做到「能收集、能提交」。

import { useState } from "react";

interface MessageInputProps {
  /** 提交时把问题文本交出去。父组件决定拿它做什么。 */
  onSubmit: (text: string) => void;
}

export function MessageInput({ onSubmit }: MessageInputProps) {
  const [draft, setDraft] = useState("");

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    // 必须阻止默认行为：form 的默认提交会让浏览器整页刷新，
    // 单页应用里那等于把所有 state 清零——包括 UploadZone 里已选的文件。
    event.preventDefault();

    const text = draft.trim();
    if (text === "") return; // 空白问题不提交，也不报错，安静地什么都不做

    onSubmit(text);
    setDraft(""); // 提交后清空草稿，光标留在输入框里，方便连着问下一个
  }

  return (
    <form className="question-form" onSubmit={handleSubmit}>
      <label htmlFor="question">你的问题</label>
      <input
        id="question"
        name="question"
        type="text"
        placeholder="例如：值班故障如何升级？"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      {/*
        disabled 绑在 trim 后的空判断上，而不是 draft === ""——
        只打了几个空格时按钮该是禁用的，否则用户按下去什么都不发生，
        看起来像坏了。让"不能提交"在视觉上先说出来。
      */}
      <button type="submit" disabled={draft.trim() === ""}>
        发送问题
      </button>
    </form>
  );
}
