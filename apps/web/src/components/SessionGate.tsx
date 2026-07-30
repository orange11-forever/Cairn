// 登录门。未登录只能看到登录页，登录后才是工作台。
//
// ---------------------------------------------------------------------------
// 为什么做成门，而不是把登录表单当第三块面板并排放在工作台里：
//
// 并排放的唯一好处是 verify-web.mjs 的八帧不用加登录前置步骤。
// 那是拿产品结构去迁就测试脚本，而这笔账 Day 13 接真鉴权时要还——
// 那天要改的是同一批文件，等于同一件事做两遍。
//
// 代价是真的：八帧现在都依赖"先登录成功"，登录一坏它们全红。
// 但那**是对的**——真实用户也进不去。测试该反映真实入口。
// 关键的界线是：八帧的**断言一行没改**，改的只是到达被测状态的路径。
// 改断言 = 换裁判（Day 7/Day 8 两次学到的那条），加前置步骤 = 走真实入口。
// ---------------------------------------------------------------------------
//
// session 存在内存里，刷新即丢。Day 13 才做持久化——今天不碰 localStorage，
// 理由见 api/auth.ts 的文件头。

import { useState } from "react";

import { LoginForm } from "./LoginForm.tsx";
import { Workspace } from "./Workspace.tsx";
import type { UserDto } from "../schemas/users.ts";

export function SessionGate() {
  // null = 未登录。用 null 而不是加一个 isLoggedIn 布尔：
  // 两个字段能表达出 `{ isLoggedIn: true, user: null }` 这种非法组合，
  // 而"登录了但不知道是谁"没有任何合理的处理方式。
  // 同 Day 7 可辨识联合那条思路，这里是它最小的形式。
  const [user, setUser] = useState<UserDto | null>(null);

  if (user === null) {
    return <LoginForm onSuccess={setUser} />;
  }

  // 退出直接 setUser(null)。
  //
  // 注意这一下会让整个 Workspace 子树卸载，于是里面所有本地 state
  //（草稿、已选文件、消息列表）都随之消失——这正是想要的行为：
  // 退出后下一个人登录时，不该看到上一个人打了一半的问题。
  //
  // 而这个"免费"得到的清理正是把 session 放在这里的回报。
  // 如果 session 放在更下面、或者用一个全局变量，就得手动一处处清，
  // 而漏掉一处的症状是跨用户的数据泄漏——Day 18 会正经讲这类问题。
  return <Workspace user={user} onLogout={() => setUser(null)} />;
}
