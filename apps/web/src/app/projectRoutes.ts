export type ProjectModule = "tasks" | "knowledge" | "code";

const PROJECT_MODULE_PATH = /^\/projects\/([^/]+)\/(tasks|knowledge|code)(?:\/|$)/;

export function projectIdFromPath(pathname: string): string | null {
  const match = pathname.match(PROJECT_MODULE_PATH);
  return match === null ? null : decodeURIComponent(match[1]!);
}

export function projectModuleFromPath(pathname: string): ProjectModule | null {
  const match = pathname.match(PROJECT_MODULE_PATH);
  return match === null ? null : (match[2] as ProjectModule);
}

export function projectPath(projectId: string, module: ProjectModule): string {
  return `/projects/${encodeURIComponent(projectId)}/${module}`;
}
