// 消息的 DTO → 视图模型转换。纯函数，不碰 DOM、不碰网络。
//
// 这是 Day 5 那条分层界线的第四次出现（前三次：documents 转换、statusText、validation）：
//   后端发什么（MessageDto，含 createdAt / score / snippet / documentId）是它的事
//   组件需要什么（Message，含 text / href / label）是组件的事
// 中间这个函数就是边界，也是两边能各自演进的原因。
//
// 具体的回报：后端把 anchor 从字符串改成 { start, end } 偏移量时，
// 改动只落在这一个文件的 citationHref 里。MessageList 和 Citation 一行不动。

import type { CitationDto, MessageDto } from "../schemas/conversations.ts";
import type { CitationSource } from "../components/Citation.tsx";
import type { Message } from "../components/MessageList.tsx";

/**
 * 引用 → 可点击的链接。
 *
 * anchor 可选（有的来源切不出段落编号，见 schemas/conversations.ts 的注释），
 * 缺失时退化成"跳到文档开头"。**不**因此丢掉这条引用：
 * 能跳到文档但落在开头，仍然比没有引用有用得多。
 */
export function toCitationSource(citation: CitationDto): CitationSource {
  const base = `/documents/${citation.documentId}`;

  return {
    href: citation.anchor === undefined ? base : `${base}#${citation.anchor}`,
    // label 是给人读的定位说明。带上锚点信息，否则五条引用指向同一份文档时，
    // 用户看到五行一模一样的文字，不知道该点哪个。
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
 * 这是 Day 6 学的可辨识联合在真实数据流上的回报，出现在两个方向：
 * schema 保证了输入的形状，视图模型保证了输出的形状。
 */
export function toViewMessage(dto: MessageDto): Message {
  if (dto.role === "assistant") {
    return {
      // id 直接用后端的。它是 ResourceId（number | string），而视图模型的 id
      // 是 string（要当 React key）。String() 转换放在这里而不是让组件转：
      // 组件不该知道后端的 id 可能是数字。
      id: String(dto.id),
      role: "assistant",
      text: dto.content,
      sources: dto.citations.map(toCitationSource),
    };
  }

  return { id: String(dto.id), role: "user", text: dto.content };
}

/**
 * 造一条本地的用户消息。
 *
 * 用户的提问是**乐观更新**：不等服务器回，立刻显示在列表里。
 * 所以它的 id 必须由前端生成——这条消息在后端还不存在。
 *
 * 用 crypto.randomUUID() 而不是 Day 8 那个 `m${prev.length}` 序号：
 * 序号在"消息只增不删"的前提下够用，而今天这个前提要破了——
 * 请求失败时那条已经显示出来的提问要能被移除（否则列表里留着一条
 * 永远等不到回答的孤儿提问）。一旦有删除，序号就会重复：
 * 删掉第 2 条后下一条新消息的 prev.length 又回到 2，和历史上某条撞 key。
 * React 会因此复用错误的 DOM 节点，症状是引用块显示在错误的消息下面。
 */
export function createUserMessage(text: string): Message {
  return { id: crypto.randomUUID(), role: "user", text: text.trim() };
}
