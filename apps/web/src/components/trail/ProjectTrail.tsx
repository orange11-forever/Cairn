import { skipToken, useQuery } from "@tanstack/react-query";

import { projectPath } from "../../app/projectRoutes.ts";
import { projectKeys } from "../../queries/projects.ts";
import type { Project } from "../../api/projects.ts";
import { TrailBreadcrumb } from "./TrailBreadcrumb.tsx";

// 只观察页面已经授权读取的项目详情，不自己发起请求：
// useProjectQuery 的 refetchOnMount: "always" 会让面包屑挂载时触发重新读取，
// 使页面的"正在确认项目访问权限"守卫反复闪烁。与 ProjectSwitcher 的做法一致。
export function ProjectTrail({ organizationId, projectId, trail }: {
  organizationId: string; projectId: string; trail: { label: string; to?: string }[];
}) {
  const project = useQuery<Project>({
    queryKey: projectKeys.detail(organizationId, projectId),
    queryFn: skipToken,
  });
  if (project.data === undefined) return null;
  return <TrailBreadcrumb items={[{ label: project.data.name, to: projectPath(projectId, "tasks") }, ...trail]} />;
}
