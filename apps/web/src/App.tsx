// 应用根组件只组合路由；会话状态和页面状态留在各自的 Provider 与页面子树中。

import { AppRoutes } from "./app/AppRoutes.tsx";

export function App() {
  return <AppRoutes />;
}
