// 应用根组件。只做一件事：把渲染交给登录门。
//
// 这条约束是 Day 8 验收「无超大页面组件」的落点，Day 9 加登录时它受到了第一次
// 真实的压力：session 状态放哪？放这里最"顺手"（整棵树都能拿到），
// 但那样 App 就从纯组合变成了状态容器，而下一个"顺手"的东西
//（当前选中的文档、Toast 队列、主题偏好）会跟着进来。半年后它两千行、谁都不敢改。
//
// 所以 session 放在 SessionGate 里——它是"所有需要它的组件的最近共同父节点"，
// 而 App 之上不需要知道有没有人登录。Day 8 那条布局组合搬到了 Workspace.tsx。
//
// 判断标准没变：这个文件里如果出现了 useState 或 await，就说明状态或请求
// 被提得太高了，该往下推到真正需要它的那个子树。今天它仍然一个都没有。

import { SessionGate } from "./components/SessionGate.tsx";

export function App() {
  return <SessionGate />;
}
