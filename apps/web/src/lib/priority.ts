import type { Task } from "../api/projects.ts";

export const PRIORITY_CODES: Record<Task["priority"], "P0" | "P1" | "P2" | "P3"> = {
  critical: "P0",
  high: "P1",
  medium: "P2",
  low: "P3",
};

export const PRIORITY_LABELS: Record<Task["priority"], string> = {
  critical: "紧急",
  high: "高优先级",
  medium: "中优先级",
  low: "低优先级",
};
