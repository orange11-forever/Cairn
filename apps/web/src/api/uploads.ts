// 上传端点。
//
// **今天发的不是文件本身，是文件的元数据**：`{ files: [{ name, size }] }`。
//
// 为什么：mock 后端不存二进制，收了也没地方放。而多段表单编码（multipart/form-data）、
// 分片上传、断点续传、进度条这些是 Day 19 后端上传接口的题目——
// 在没有存储层的情况下做半个 FormData，只会得到一段将来必须整个重写的代码。
//
// 今天要练的是**表单的那一半**：文件选择、客户端校验、可读的每文件错误、
// 提交中禁用、服务端 413/415 的处理。这些逻辑在换成真 FormData 时一行不用改，
// 因为它们和"body 怎么编码"无关。改动会全部落在这个文件的 request 调用上。

import { request } from "./client.ts";
import { parseOrThrow } from "../schemas/parse.ts";
import { ResourceIdSchema } from "../schemas/primitives.ts";
import { z } from "zod";

/**
 * 上传响应。
 *
 * status 是 "pending" 而不是 "completed"——上传成功只意味着**创建了处理任务**，
 * 文档还没被解析和索引。这个区别要从第一天就在类型里体现出来，
 * 否则 UI 会写成"上传成功 → 提示可以开始问答了"，而用户马上会发现问不出东西。
 * Day 21 的 worker 才会把它推进到 completed。
 */
const UploadJobSchema = z.object({
  id: ResourceIdSchema,
  documentTitle: z.string().min(1),
  status: z.literal("pending"),
});

const UploadResponseSchema = z.object({
  accepted: z.number().int().nonnegative(),
  jobs: z.array(UploadJobSchema),
});

export type UploadResponse = z.infer<typeof UploadResponseSchema>;

/** 上传只需要文件的这两个字段。和 lib/validation.ts 的 FileLike 是同一个形状。 */
export interface UploadFileInput {
  name: string;
  size: number;
}

export async function uploadDocuments(
  files: UploadFileInput[],
  signal: AbortSignal,
): Promise<UploadResponse> {
  const raw = await request("/api/v1/uploads", {
    method: "POST",
    // 显式挑字段而不是直接传 files。
    // 传进来的可能是真 File 对象，JSON.stringify(File) 的结果是 `{}`——
    // 一个空对象，服务端收到会报"每个文件必须有 name 和 size"，
    // 而排查时你盯着前端代码看不出问题（File 明明有 name）。
    // 原因是 File 的属性在原型上，不是自有可枚举属性。显式取值绕开这个坑。
    body: { files: files.map((file) => ({ name: file.name, size: file.size })) },
    signal,
    // 上传比查询慢，给更长的超时。3 秒对一个可能要传几 MB 的请求太紧。
    timeoutMs: 15000,
  });

  return parseOrThrow(UploadResponseSchema, raw, "POST /api/v1/uploads");
}
