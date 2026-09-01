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

import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { MessageInput } from "./MessageInput.tsx";
import { MessageList } from "./MessageList.tsx";
import type { Message } from "./MessageList.tsx";
import { WorkspaceHeader } from "./WorkspaceHeader.tsx";
import { WorkspaceStatus } from "./WorkspaceStatus.tsx";
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

      <div className="conversation-workspace">
        <article aria-labelledby="answer-title">
          <h2 id="answer-title">对话</h2>
          {messages.length === 0 && !action.pending ? (
            <div className="assistant-empty-state" role="status" aria-label="问答工作区">
              <WorkspaceStatus
                state="empty"
                mascot={{ label: "岑宁，Cairn 问答助手", variant: "half" }}
                title="准备就绪"
                description="选择一个常见问题，或直接输入你的问题。"
                action={
                  <div className="question-suggestions">
                    <button type="button" onClick={() => void ask("值班故障如何升级？")}>
                      值班故障如何升级？
                    </button>
                    <button
                      type="button"
                      onClick={() => void ask("如何申请生产环境访问权限？")}
                    >
                      如何申请生产环境访问权限？
                    </button>
                  </div>
                }
              />
            </div>
          ) : (
            <MessageList messages={messages} pending={action.pending} />
          )}
        </article>

        {action.state.phase === "error" && (
          <p className="form-error conversation-error" role="alert">
            {action.state.error.message}
            {action.state.error.retryable && lastQuestion !== null && (
              <button type="button" className="retry-btn" onClick={() => void ask(lastQuestion)}>
                <RefreshCw aria-hidden="true" size={16} strokeWidth={1.8} />
                重试
              </button>
            )}
          </p>
        )}

        <div className="conversation-composer">
          <MessageInput
            onSubmit={(text) => void ask(text)}
            pending={action.pending}
            onCancel={action.cancel}
          />
        </div>
      </div>
    </section>
  );
}
