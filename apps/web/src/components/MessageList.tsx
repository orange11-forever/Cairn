// 消息列表。纯展示：消息数组进来，对话记录出去。

import { Citation } from "./Citation.tsx";
import type { CitationSource } from "./Citation.tsx";

/**
 * 一条消息。
 *
 * 形状刻意和 schemas/conversations.ts 的后端 DTO 分开：
 * 这是**视图模型**，只含渲染需要的字段。Day 7 学到的 DTO vs 领域模型那条界线
 * 在这里第三次出现——后端发什么是它的事，组件需要什么是组件的事，
 * 中间那层转换（lib/）是两边都能独立演进的原因。
 *
 * 引用只出现在 assistant 消息上：用户提的问题不带引用。
 * 用可辨识联合表达，而不是给 user 消息也挂一个永远为空的 sources 字段——
 * 那样每个消费者都得判空，而"用户消息也可能有引用"这种情况根本不存在。
 */
export type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; text: string; sources: CitationSource[] };

interface MessageListProps {
  messages: Message[];
}

export function MessageList({ messages }: MessageListProps) {
  if (messages.length === 0) {
    return <p className="message-empty">还没有提问。问一个问题试试。</p>;
  }

  return (
    // ol：对话有严格顺序，第 3 句只有在第 2 句之后才说得通
    <ol id="message-list" className="message-list">
      {messages.map((message) => (
        // data-role 给 CSS 做左右分栏和配色的挂钩，同时是测试的选择器依据
        <li key={message.id} data-role={message.role}>
          <p className="message-text">{message.text}</p>
          {/*
            联合类型的回报：这个分支里 message.sources 必然存在，不用判空。
            如果哪天 user 消息也要带引用，改的是上面的类型，
            编译器会把所有需要跟着改的地方列出来。
          */}
          {message.role === "assistant" && <Citation sources={message.sources} />}
        </li>
      ))}
    </ol>
  );
}
