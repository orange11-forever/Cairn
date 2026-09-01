// 消息列表。纯展示：消息数组进来，对话记录出去。

import { Citation } from "./Citation.tsx";
import type { CitationSource } from "./Citation.tsx";
import { MascotFigure } from "./MascotFigure.tsx";
import { useAutoScroll } from "../hooks/useAutoScroll.ts";

/**
 * 一条消息。
 *
 * 形状刻意和 schemas/conversations.ts 的后端 DTO 分开：
 * 这是**视图模型**，只含渲染需要的字段。后端发什么是它的事，组件需要什么是组件的事，
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
  /** 是否正在等回答。为 true 时在列表末尾显示一条占位。 */
  pending?: boolean;
}

export function MessageList({ messages, pending = false }: MessageListProps) {
  // 自动滚动传**条数**而不是数组本身——
  // 数组每次渲染都是新引用（setMessages 返回新数组），用它做依赖等于每次渲染都滚。
  // 条数是原始值，只在真的多了一条时才触发。详见 hooks/useAutoScroll.ts。
  //
  // 返回的是一个 **ref 回调**（函数），不是 ref 对象。
  // 因为下面的滚动容器是条件渲染的，而条件渲染的节点只有 ref 回调能可靠地
  // 捕捉到"它出现了"——那个坑的完整记录在 useAutoScroll.ts 里。
  const attachScroll = useAutoScroll(messages.length);

  if (messages.length === 0 && !pending) {
    return <p className="message-empty">还没有提问。问一个问题试试。</p>;
  }

  return (
    // 滚动容器包在 ol 外面。
    //
    // 为什么不直接把 ref 挂 ol 上并给它 overflow：可以，但把滚动职责放在
    // 一个专门的 div 上更清楚——ol 负责语义（有序列表），div 负责视口。
    // 混在一起时，将来给列表加 padding 或 border 会改变 scrollHeight 的含义，
    // 那种 bug 表现为"自动滚动总差一点"。
    <div className="message-scroll" ref={attachScroll}>
      {/*
        ol：对话有严格顺序，第 3 句只有在第 2 句之后才说得通。

        aria-label 是写测试时补上的：页面上现在有两个列表（对话记录 + 引用来源），
        两个都没有名字，读屏用户听到的是"列表，2 项"——不知道是哪个列表。
        测试里"按角色找 list"因此拿到两个匹配而失败，那个失败指向的是一个
        真实的可访问性问题，不是测试写法问题。
      */}
      <ol id="message-list" className="message-list" aria-label="对话记录">
        {messages.map((message) => (
          // data-role 给 CSS 做左右分栏和配色的挂钩，同时是测试的选择器依据
          <li key={message.id} data-role={message.role}>
            {message.role === "assistant" ? (
              <MascotFigure
                className="message-mascot"
                label="岑宁，Cairn 助手"
                state="success"
              />
            ) : null}
            <div className="message-bubble">
              <span className="message-author">
                {message.role === "assistant" ? "岑宁" : "你"}
              </span>
              <p className="message-text">{message.text}</p>
            {/*
              联合类型的回报：这个分支里 message.sources 必然存在，不用判空。
              如果哪天 user 消息也要带引用，改的是上面的类型，
              编译器会把所有需要跟着改的地方列出来。
            */}
              {message.role === "assistant" && <Citation sources={message.sources} />}
            </div>
          </li>
        ))}

        {/*
          等待占位。放在 ol 里面而不是外面，因为它在视觉上占的是"下一条消息"的位置，
          而且这样自动滚动会把它一起滚进视野——用户看到的是"我的提问 + 正在检索"，
          两条挨着，等待的对象很清楚。

          data-role="pending" 而不是复用 "assistant"：CSS 和测试都要能区分
          "一条真回答"和"一个占位"。复用的话，断言"有一条 assistant 消息"
          会在还没答完时就通过。
        */}
        {pending && (
          <li data-role="pending" className="message-pending">
            <MascotFigure
              className="message-mascot"
              label="岑宁，Cairn 助手"
              state="thinking"
            />
            <div className="message-bubble">
              <span className="message-author">岑宁</span>
              <p className="message-text" aria-live="polite">正在检索知识文档…</p>
            </div>
          </li>
        )}
      </ol>
    </div>
  );
}
