export interface NavigationItem {
  to: "/projects";
  label: string;
  shortLabel: string;
  module: "knowledge" | "projects" | "execution" | "governance";
}

export const navigationItems = [
  { to: "/projects", label: "项目任务", shortLabel: "项目", module: "projects" },
] as const satisfies readonly NavigationItem[];
