// AI 问答面板。持有消息列表，并发真正的问答请求。
//
// 为什么 messages 放在这里而不是提到 App/AuthenticatedLayout：
// 只有这个子树需要它。状态该待在"所有需要它的组件的最近共同父节点"——
// 提得过高会让无关组件跟着重渲染，也让上层从纯布局变成状态容器。
//
// ---------------------------------------------------------------------------
// 乐观更新（optimistic update）：用户的提问**不等服务器**就先显示出来。
//
// 理由是体感。等 1.5 秒再一起显示"提问 + 回答"，用户在这 1.5 秒里
// 看不到自己刚说的话，会怀疑发送没成功（然后再点一次）。
// 先显示提问、再等回答，等待期间屏幕上有他自己的话在，这个等待才是可理解的。
//
// 代价是失败时要**回滚**：那条提问必须撤掉，否则列表里留下一条永远等不到回答的
// 孤儿提问。这个回滚就是 lib/messages.ts 里 createUserMessage 用 randomUUID
// 而不用序号的原因——一旦有删除，prev.length 做 id 就会和历史某条撞 key。
// ---------------------------------------------------------------------------

import { useState } from "react";

import { MessageInput } from "./MessageInput.tsx";
import { MessageList } from "./MessageList.tsx";
import type { Message } from "./MessageList.tsx";
import { WorkspaceHeader } from "./WorkspaceHeader.tsx";
import { askQuestion } from "../api/conversations.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import { createUserMessage, toViewMessage } from "../lib/messages.ts";

export function AssistantPanel({ parentSignal }: { parentSignal?: AbortSignal }) {
  const [messages, setMessages] = useState<Message[]>([]);

  // 上一次失败的提问文本。留着它是为了能重试——
  // 而重试要用**原文**，不能让用户重新打一遍（他的草稿在提交时已经清了）。
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);

  const action = useAbortableAction(askQuestion, parentSignal);

  async function ask(text: string) {
    const userMessage = createUserMessage(text);

    // 用函数式更新 setMessages(prev => ...) 而不是 setMessages([...messages, ...])。
    // 后者读的是本次渲染闭包里的 messages，连续两次快速提交会让第二次
    // 覆盖掉第一次——因为两次读到的都是同一个旧数组。
    setMessages((prev) => [...prev, userMessage]);
    setLastQuestion(text);

    const answer = await action.run({ question: text });

    if (answer === undefined) {
      // 失败或被取消：回滚那条乐观插入的提问。
      //
      // 按 id 过滤而不是 `prev.slice(0, -1)`：即使未来允许打断并重新提问，
      // 按 id 删除也不会误删列表末尾的另一条消息。
      setMessages((prev) => prev.filter((message) => message.id !== userMessage.id));
      return;
    }

    setMessages((prev) => [...prev, toViewMessage(answer)]);
    setLastQuestion(null); // 成功了，没有可重试的东西
  }

  return (
    <section className="assistant-panel" aria-labelledby="assistant-title">
      <WorkspaceHeader
        id="assistant-title"
        title="AI 问答"
        description="回答只依据已经处理完成的知识文档。"
      />

      <MessageInput
        // void 前缀：ask 是 async，返回一个 Promise 而 onSubmit 声明返回 void。
        // 不加 void 会有一个"返回值被忽略"的类型问题，加了它是在明确说
        // "这个 Promise 不需要被等待"——因为错误已经由 useAbortableAction 收进 state 了。
        onSubmit={(text) => void ask(text)}
        pending={action.pending}
        // 停止生成。这一下真的会终止请求——signal 一路传到了 fetch
        //（useAbortableAction → askQuestion → request → fetch），
        // 中间任何一环漏传 signal，UI 会显示"已停止"而请求还在飞。
        // 这条链路由 verify-web.mjs 的取消帧实测。
        onCancel={action.cancel}
      />

      {/*
        请求级错误。位置在输入框和回答之间——它说的是"刚才那次提问失败了"，
        挨着提问框才读得通。放在消息列表底部会看起来像一条助手消息。
      */}
      {action.state.phase === "error" && (
        <p className="form-error" role="alert">
          {action.state.error.message}
          {/*
            重试按钮只在 retryable 时出现。
            contract 错误（响应格式不对）和 4xx 都不该给重试——
            那是代码 bug 或请求本身有问题，重试一万次结果一样，
            让用户重试是骗他（ApiError.retryable 的注释里论证过）。
          */}
          {action.state.error.retryable && lastQuestion !== null && (
            <button type="button" className="retry-btn" onClick={() => void ask(lastQuestion)}>
              重试
            </button>
          )}
        </p>
      )}

      <article aria-labelledby="answer-title">
        <h2 id="answer-title">回答</h2>
        {/* pending 传下去让列表显示"正在检索…"占位。
            空着的话，用户提交后看到自己的提问下面什么都没有，
            不知道是在等，还是已经答完了而答案是空的。 */}
        <MessageList messages={messages} pending={action.pending} />
      </article>
    </section>
  );
}
