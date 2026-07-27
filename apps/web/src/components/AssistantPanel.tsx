// AI 问答面板。持有消息列表的本地 state。
//
// 今天不发请求：提交一个问题只会把它 append 到本地消息列表，
// 外加一条写死的助手回答（保留 Day 2 静态 HTML 里那段文案和引用，
// 好让 CSS 仍有真实内容可排版）。真正的问答链路 Day 10 之后接。
//
// 为什么 messages 放在这里而不是提到 App：
// 只有这个子树需要它。状态该待在"所有需要它的组件的最近共同父节点"——
// 提得过高会让无关组件跟着重渲染，也让 App 从纯布局变成状态容器。

import { useState } from "react";

import { MessageInput } from "./MessageInput.tsx";
import { MessageList } from "./MessageList.tsx";
import type { Message } from "./MessageList.tsx";

// Day 2 静态 HTML 里那条写死的回答，原样搬过来当占位。
const PLACEHOLDER_ANSWER = "严重故障需要先通知当班负责人，再按照升级矩阵联系服务负责人。";
const PLACEHOLDER_SOURCES = [
  { href: "/documents/on-call#section-4", label: "值班流程，第 4 节" },
];

export function AssistantPanel() {
  const [messages, setMessages] = useState<Message[]>([]);

  function handleSubmit(text: string) {
    // 用函数式更新 setMessages(prev => ...) 而不是 setMessages([...messages, ...])。
    // 后者读的是本次渲染闭包里的 messages，连续两次快速提交会让第二次
    // 覆盖掉第一次——因为两次读到的都是同一个旧数组。函数式更新拿到的
    // 一定是最新值，这是 React 状态更新"异步批处理"的直接后果。
    setMessages((prev) => {
      // id 必须稳定且唯一，因为它是列表的 key。
      // 不用 Date.now()：连续提交可能落在同一毫秒，产生重复 key。
      // 用累加的序号——prev.length 在这里够用（消息只增不删）；
      // Day 10 接真接口后 id 该由后端给，或者用 crypto.randomUUID()。
      const base = prev.length;
      const question: Message = { id: `m${base}`, role: "user", text };
      const answer: Message = {
        id: `m${base + 1}`,
        role: "assistant",
        text: PLACEHOLDER_ANSWER,
        sources: PLACEHOLDER_SOURCES,
      };
      return [...prev, question, answer];
    });
  }

  return (
    <section className="assistant-panel" aria-labelledby="assistant-title">
      <h2 id="assistant-title">AI 问答</h2>
      <p>回答只依据已经处理完成的知识文档。</p>

      <MessageInput onSubmit={handleSubmit} />

      <article aria-labelledby="answer-title">
        <h2 id="answer-title">回答</h2>
        <MessageList messages={messages} />
      </article>
    </section>
  );
}
