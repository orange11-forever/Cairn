// 问答端点。
//
// Day 8 的 AssistantPanel 提交后 append 一条写死的回答。今天换成真请求，
// 于是三件之前不存在的事必须处理：等待、失败、取消。

import { request } from "./client.ts";
import { AskResponseSchema, type AskResponseDto } from "../schemas/conversations.ts";
import { parseOrThrow } from "../schemas/parse.ts";

export interface AskInput {
  question: string;
}

/**
 * 提一个问题，拿一条回答。
 *
 * 用 parseOrThrow 而不是宽松解析：一条回答是**单个关键对象**，
 * 判据是 schemas/parse.ts 文件头那句"用户能不能带着不完整的数据继续工作"。
 * 答案是不能——一条 citations 解析失败的回答，显示出来就是一个没有依据的答案，
 * 而"回答只依据已处理完成的知识文档"是这个产品的核心承诺。
 * 宁可报错说"这条回答有问题"，也不能给一个看起来有依据实际没有的答案。
 *
 * 对比 GET /api/docs 用 parseList（逐条筛）：那里丢一条文档，用户还有 99 条能用。
 * 同一个应用里两种策略并存不是不一致，是因为后果不同。
 */
export async function askQuestion(
  { question }: AskInput,
  signal: AbortSignal,
): Promise<AskResponseDto> {
  const raw = await request("/api/v1/ask", {
    method: "POST",
    body: { question: question.trim() },
    signal,
  });

  return parseOrThrow(AskResponseSchema, raw, "POST /api/v1/ask");
}
