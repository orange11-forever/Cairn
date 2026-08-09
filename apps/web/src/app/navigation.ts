export interface NavigationItem {
  to: "/documents" | "/projects" | "/ask";
  label: string;
  shortLabel: string;
  module: "knowledge" | "projects" | "execution" | "governance";
}

export const navigationItems = [
  { to: "/documents", label: "知识文档", shortLabel: "文档", module: "knowledge" },
  { to: "/projects", label: "项目任务", shortLabel: "项目", module: "projects" },
  { to: "/ask", label: "知识问答", shortLabel: "问答", module: "knowledge" },
] as const satisfies readonly NavigationItem[];
