// 消息的 DTO → 视图模型转换。纯函数，不碰 DOM、不碰网络。
//
// DTO 与视图模型保持明确边界：
//   后端发什么（MessageDto，含 createdAt / score / snippet / documentId）是它的事
//   组件需要什么（Message，含 text / label）是组件的事
// 中间这个函数就是边界，也是两边能各自演进的原因。
//
// 具体的回报：后端调整引用定位结构时，改动只落在这个文件的标签转换里。
// MessageList 和 Citation 一行不动。

import type { AskResponseDto, CitationDto } from "../schemas/conversations.ts";
import type { CitationSource } from "../components/Citation.tsx";
import type { Message } from "../components/MessageList.tsx";

/**
 * 引用 → 可读标签。
 *
 * anchor 可选（有的来源切不出段落编号，见 schemas/conversations.ts 的注释）。
 * 还没有文档详情路由，因此不构造目标 URL；仍保留来源标签。
 */
export function toCitationSource(citation: CitationDto): CitationSource {
  return {
    // label 是给人读的定位说明。带上锚点信息，否则五条引用指向同一份文档时，
    // 用户看到五行一模一样的文字，无法区分来源位置。
    label:
      citation.anchor === undefined
        ? citation.documentTitle
        : `${citation.documentTitle}，${citation.anchor}`,
  };
}

/**
 * 后端的一条消息 → 组件用的一条消息。
 *
 * 入参是可辨识联合（MessageDtoSchema 用 discriminatedUnion 建的），
 * 所以 assistant 分支里 citations 必然存在，不用判空。
 * schema 保证了输入的形状，视图模型保证了输出的形状。
 */
export function toViewMessage(dto: AskResponseDto): Message {
  if (dto.kind === "not_found") {
    return {
      id: dto.id,
      role: "assistant",
      text: "未在知识文档中找到相关内容。",
      sources: [],
    };
  }

  return {
    id: dto.id,
    role: "assistant",
    text: dto.content,
    sources: dto.citations.map(toCitationSource),
  };
}

/**
 * 造一条本地的用户消息。
 *
 * 用户的提问是**乐观更新**：不等服务器回，立刻显示在列表里。
 * 所以它的 id 必须由前端生成——这条消息在后端还不存在。
 *
 * 用 crypto.randomUUID() 而不是基于数组长度的序号：
 * 序号在"消息只增不删"的前提下够用，而今天这个前提要破了——
 * 请求失败时那条已经显示出来的提问要能被移除（否则列表里留着一条
 * 永远等不到回答的孤儿提问）。一旦有删除，序号就会重复：
 * 删掉第 2 条后下一条新消息的 prev.length 又回到 2，和历史上某条撞 key。
 * React 会因此复用错误的 DOM 节点，症状是引用块显示在错误的消息下面。
 */
export function createUserMessage(text: string): Message {
  return { id: crypto.randomUUID(), role: "user", text: text.trim() };
}
