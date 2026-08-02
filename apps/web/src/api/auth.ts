// 登录端点。
//
// Day 9 只做到"验证凭据、拿到当前用户"。**没有 token、没有持久化**：
// 登录成功的结果只是一个内存里的 user 对象，刷新页面就没了。
//
// 这不是偷懒，是刻意把 Day 13 的题目留给 Day 13：token 存哪（不能存 localStorage）、
// HttpOnly Cookie 为什么是默认选择、CSRF 怎么防、401 怎么自动处理。
// 今天随手往 localStorage 写一个 token，Day 13 第一件事就是把它删掉——
// 而删掉的过程里很容易漏掉一处读取，那是真实项目里最常见的鉴权漏洞形状。

import { request } from "./client.ts";
import { UserDtoSchema, type UserDto } from "../schemas/users.ts";
import { parseOrThrow } from "../schemas/parse.ts";
import { z } from "zod";

/**
 * 登录响应。
 *
 * 用 parseOrThrow（全有或全无）而不是宽松解析——这条判断在 schemas/users.ts
 * 的文件头已经论证过：role 字段没有安全的兜底值。降级成 viewer 会让管理员
 * 看不到入口，降级成 admin 更糟。所以坏数据就整个失败，让用户重新登录。
 */
const LoginResponseSchema = z.object({ user: UserDtoSchema });

export interface LoginInput {
  email: string;
  password: string;
}

/**
 * 登录。
 *
 * signal 是**必需参数**而不是可选的 options 字段。
 * 这是配合 useAbortableAction 的类型约定（见那个 Hook 里 fn 的签名）：
 * 强制每个端点都把取消信号接进来，就不会出现"UI 上取消了、请求还在飞"。
 * 写成可选的话，漏传不会有任何编译错误，而症状要到用户真去点取消才暴露。
 */
export async function login({ email, password }: LoginInput, signal: AbortSignal): Promise<UserDto> {
  const raw = await request("/api/v1/login", {
    method: "POST",
    // email 在这里 trim 而不是让调用方 trim：归一化属于边界层。
    // 密码不 trim——空格是合法密码字符（见 lib/validation.ts 里同一条）。
    body: { email: email.trim(), password },
    signal,
  });

  const { user } = parseOrThrow(LoginResponseSchema, raw, "POST /api/v1/login");
  return user;
}
