// 用户 DTO。
//
// 这个资源的校验策略和文档**相反**，对比值得记住：
//
//   文档列表：宽松。一条坏数据丢掉那一条，其余照常显示。
//   当前用户：严格。坏了就整个失败，宁可让用户重新登录。
//
// 差别不在技术，在后果。列表里少一行，用户看到的是"我的文档好像少了一个"；
// 而 role 字段解析错了如果降级成 "viewer"，管理员会看不到管理入口 ——
// 降级成 "admin" 更糟，普通人拿到了管理权限。
// 权限相关的字段没有安全的兜底值，所以不给兜底，直接拒绝。

import { z } from "zod";
import { NonEmptyStringSchema, ResourceIdSchema } from "./primitives.ts";

/**
 * 用户角色。Day 20 后端做鉴权时这套值要和数据库枚举对齐。
 *
 * 刻意不加 `.catch()`：见文件头。权限字段的兜底值只有"错得离谱"和"错得危险"两种选择。
 */
export const USER_ROLES = ["owner", "admin", "member", "viewer"] as const;
export const UserRoleSchema = z.enum(USER_ROLES);
export type UserRole = z.infer<typeof UserRoleSchema>;

/**
 * 用户 DTO。
 *
 * email 用 z.email() 而不是裸 string：邮箱是要拿去发通知的，
 * 格式错了在这里发现比在邮件服务商那里发现便宜得多。
 * （Zod 4 把它提到了顶层；旧写法 z.string().email() 仍能跑，但是遗留路径。）
 *
 * displayName 允许缺失（很多系统里它是可选的），但**不允许是空字符串** ——
 * 空字符串会在 UI 上渲染成一片空白，比明确的 undefined 更难排查。
 * 缺失时由使用处决定退回显示 email 还是显示"匿名用户"，这是展示决策，不是校验决策。
 */
export const UserDtoSchema = z.object({
  id: ResourceIdSchema,
  email: z.email(),
  displayName: NonEmptyStringSchema.optional(),
  role: UserRoleSchema,
});

export type UserDto = z.infer<typeof UserDtoSchema>;
