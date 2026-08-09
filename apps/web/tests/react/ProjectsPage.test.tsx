import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import type { IdentityContext } from "../../src/api/auth.ts";
import { projectKeys, taskKeys } from "../../src/queries/projects.ts";
import { ProjectsPage } from "../../src/pages/ProjectsPage.tsx";
import { SessionProvider } from "../../src/session/SessionContext.tsx";

const IDENTITY: IdentityContext = {
  user: {
    id: "00000000-0000-4000-8000-000000001001",
    email: "demo@cairn.dev",
    displayName: "演示用户",
  },
  organization: {
    id: "00000000-0000-4000-8000-000000002001",
    slug: "cairn-demo",
    name: "Cairn Demo",
  },
  membership: {
    id: "00000000-0000-4000-8000-000000003001",
    role: "owner",
  },
  csrfToken: "csrf-project-token",
};

const PROJECT = {
  id: "00000000-0000-4000-8000-000000004001",
  name: "知识库迁移",
  description: "把团队资料迁入统一知识层。",
  createdAt: "2026-08-01T08:00:00Z",
  updatedAt: "2026-08-08T08:00:00Z",
};

const PROJECT_B = {
  id: "00000000-0000-4000-8000-000000004002",
  name: "搜索体验升级",
  description: "缩短团队查找资料的路径。",
  createdAt: "2026-08-03T08:00:00Z",
  updatedAt: "2026-08-08T09:00:00Z",
};

const TASK = {
  id: "00000000-0000-4000-8000-000000005001",
  projectId: PROJECT.id,
  parentTaskId: null,
  stageId: null,
  title: "核对迁移清单",
  status: "todo" as const,
  priority: "high" as const,
  dueAt: "2026-08-12T08:00:00Z",
  acceptanceCriteria: "全部资料都有负责人并通过抽查。",
  createdAt: "2026-08-02T08:00:00Z",
  updatedAt: "2026-08-08T08:00:00Z",
};

const TASK_B = {
  id: "00000000-0000-4000-8000-000000005002",
  projectId: PROJECT_B.id,
  parentTaskId: null,
  stageId: null,
  title: "整理搜索词表",
  status: "todo" as const,
  priority: "medium" as const,
  dueAt: null,
  acceptanceCriteria: "覆盖团队常用术语。",
  createdAt: "2026-08-04T08:00:00Z",
  updatedAt: "2026-08-08T09:00:00Z",
};

const TASK_PAGE_2 = {
  ...TASK_B,
  projectId: PROJECT.id,
  title: "复核迁移结果",
};

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function requestDetails(input: RequestInfo | URL, init?: RequestInit) {
  if (input instanceof Request) {
    return { url: new URL(input.url), method: input.method, headers: input.headers };
  }
  return {
    url: new URL(String(input)),
    method: init?.method ?? "GET",
    headers: new Headers(init?.headers),
  };
}

function renderProjects(queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/projects"]}>
          <SessionProvider restoredIdentity={IDENTITY}>
            <ProjectsPage />
          </SessionProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("loading projects shows a workbench-shaped skeleton", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

  renderProjects();

  const workspace = screen.getByRole("region", { name: "项目工作区" });
  expect(workspace).toHaveAttribute("aria-busy", "true");
  expect(within(workspace).getByText("正在加载项目")).toBeInTheDocument();
  expect(workspace.querySelectorAll(".project-skeleton").length).toBeGreaterThan(1);
});

test("an organization with no projects gets a clear empty state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({ items: [], nextCursor: null })),
  );

  renderProjects();

  expect(await screen.findByRole("heading", { name: "还没有项目" })).toBeInTheDocument();
  expect(screen.getByText("项目创建后会显示在这里。")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /创建/ })).toBeNull();
});

test("a failed project request exposes retry and recovers", async () => {
  let attempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse(
          { code: "database_unavailable", message: "项目暂时无法加载", traceId: "trace-projects" },
          503,
        );
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  expect(await screen.findByRole("alert")).toHaveTextContent("项目暂时无法加载");
  await user.click(screen.getByRole("button", { name: "重新加载项目" }));

  expect(await screen.findByRole("heading", { name: "还没有项目" })).toBeInTheDocument();
  expect(attempts).toBe(2);
});

test("a background project refresh failure keeps the rail and exposes a contextual retry", async () => {
  let projectRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        projectRequests += 1;
        if (projectRequests === 2) {
          return jsonResponse(
            { code: "database_unavailable", message: "项目列表刷新失败", traceId: "trace-project-refresh" },
            503,
          );
        }
        return jsonResponse({
          items: projectRequests === 1 ? [PROJECT] : [PROJECT, PROJECT_B],
          nextCursor: null,
        });
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();
  const { queryClient } = renderProjects();

  expect(await screen.findByRole("button", { name: /知识库迁移/ })).toBeInTheDocument();
  await queryClient.invalidateQueries({
    queryKey: projectKeys.list(IDENTITY.organization.id),
    exact: true,
  });

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("项目列表可能不是最新");
  expect(alert).toHaveTextContent("项目列表刷新失败");
  expect(screen.getByRole("button", { name: /知识库迁移/ })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重试刷新项目" }));

  expect(await screen.findByRole("button", { name: /搜索体验升级/ })).toBeInTheDocument();
  expect(screen.queryByText("项目列表可能不是最新")).toBeNull();
  expect(projectRequests).toBe(3);
});

test("a background project refresh failure keeps the empty state and exposes a contextual retry", async () => {
  let projectRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        projectRequests += 1;
        if (projectRequests === 2) {
          return jsonResponse(
            { code: "database_unavailable", message: "项目列表刷新失败", traceId: "trace-empty-project-refresh" },
            503,
          );
        }
        return jsonResponse({
          items: projectRequests === 1 ? [] : [PROJECT],
          nextCursor: null,
        });
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();
  const { queryClient } = renderProjects();

  expect(await screen.findByRole("heading", { name: "还没有项目" })).toBeInTheDocument();
  await queryClient.invalidateQueries({
    queryKey: projectKeys.list(IDENTITY.organization.id),
    exact: true,
  });

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("项目列表可能不是最新");
  expect(alert).toHaveTextContent("项目列表刷新失败");
  expect(screen.getByRole("heading", { name: "还没有项目" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重试刷新项目" }));

  expect(await screen.findByRole("button", { name: /知识库迁移/ })).toBeInTheDocument();
  expect(screen.queryByText("项目列表可能不是最新")).toBeNull();
  expect(projectRequests).toBe(3);
});

test("the selected project shows an explicit empty task workspace", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );

  renderProjects();

  const projectButton = await screen.findByRole("button", { name: /知识库迁移/ });
  expect(projectButton).toHaveAttribute("aria-pressed", "true");
  expect(await screen.findByRole("heading", { name: "这个项目还没有任务" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /创建任务/ })).toBeNull();
});

test("a failed task request exposes retry inside the selected project", async () => {
  let taskAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      taskAttempts += 1;
      if (taskAttempts === 1) {
        return jsonResponse(
          { code: "database_unavailable", message: "任务暂时无法加载", traceId: "trace-tasks" },
          503,
        );
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  expect(await screen.findByRole("alert")).toHaveTextContent("任务暂时无法加载");
  await user.click(screen.getByRole("button", { name: "重新加载任务" }));

  expect(await screen.findByRole("heading", { name: "这个项目还没有任务" })).toBeInTheDocument();
  expect(taskAttempts).toBe(2);
});

test("task rows show status, priority, due date, acceptance criteria, and legal actions", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      return jsonResponse({ items: [TASK], nextCursor: null });
    }),
  );

  renderProjects();

  const task = await screen.findByRole("article", { name: "核对迁移清单" });
  expect(within(task).getByText("待处理")).toBeInTheDocument();
  expect(within(task).getByText("高优先级")).toBeInTheDocument();
  expect(within(task).getByText(/2026.*8.*12/)).toBeInTheDocument();
  expect(within(task).getByText("全部资料都有负责人并通过抽查。")).toBeInTheDocument();
  expect(within(task).getByRole("button", { name: "开始任务" })).toBeEnabled();
  expect(within(task).queryByRole("button", { name: /完成|阻塞|取消/ })).toBeNull();
});

test("a pending status transition disables actions and invalidates only the selected task query", async () => {
  const transition = deferred<Response>();
  let taskRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url, method, headers } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      if (url.pathname === `/api/v1/tasks/${TASK.id}/status` && method === "PATCH") {
        expect(headers.get("X-CSRF-Token")).toBe(IDENTITY.csrfToken);
        return transition.promise;
      }
      taskRequests += 1;
      return jsonResponse({
        items: [taskRequests === 1 ? TASK : { ...TASK, status: "in_progress" }],
        nextCursor: null,
      });
    }),
  );
  const user = userEvent.setup();
  const { queryClient } = renderProjects();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await user.click(await screen.findByRole("button", { name: "开始任务" }));

  expect(screen.getByRole("button", { name: "正在更新" })).toBeDisabled();
  transition.resolve(jsonResponse({ ...TASK, status: "in_progress" }));

  expect(await screen.findByText("进行中")).toBeInTheDocument();
  await waitFor(() =>
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: taskKeys.list(IDENTITY.organization.id, PROJECT.id),
      exact: true,
      refetchType: "all",
    }),
  );
  expect(taskRequests).toBe(2);
});

test("a committed transition with a failed task refresh keeps old data and exposes refresh retry", async () => {
  let taskRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      if (url.pathname === `/api/v1/tasks/${TASK.id}/status` && method === "PATCH") {
        return jsonResponse({ ...TASK, status: "in_progress" });
      }
      taskRequests += 1;
      if (taskRequests === 2) {
        return jsonResponse(
          { code: "database_unavailable", message: "任务列表刷新失败", traceId: "trace-task-refresh" },
          503,
        );
      }
      return jsonResponse({
        items: [taskRequests === 1 ? TASK : { ...TASK, status: "in_progress" }],
        nextCursor: null,
      });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  await user.click(await screen.findByRole("button", { name: "开始任务" }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("任务更新已提交，但列表刷新失败");
  expect(alert).toHaveTextContent("当前数据可能不是最新");
  expect(alert).toHaveTextContent("任务列表刷新失败");
  expect(screen.getByText("待处理")).toBeInTheDocument();
  expect(screen.queryByText("任务状态更新失败")).toBeNull();
  expect(screen.getByRole("button", { name: "开始任务" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重试刷新任务" }));

  expect(await screen.findByText("进行中")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "开始任务" })).toBeNull();
  expect(screen.getByRole("button", { name: "完成任务" })).toBeEnabled();
  expect(screen.queryByText("当前数据可能不是最新")).toBeNull();
  expect(taskRequests).toBe(3);
});

test("a retained task refresh error keeps stale actions disabled after switching projects", async () => {
  let projectATaskRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT, PROJECT_B], nextCursor: null });
      }
      if (url.pathname === `/api/v1/tasks/${TASK.id}/status` && method === "PATCH") {
        return jsonResponse({ ...TASK, status: "in_progress" });
      }
      if (url.pathname === `/api/v1/projects/${PROJECT.id}/tasks`) {
        projectATaskRequests += 1;
        if (projectATaskRequests === 2 || projectATaskRequests === 3) {
          return jsonResponse(
            { code: "database_unavailable", message: "任务列表刷新失败", traceId: "trace-task-remount" },
            503,
          );
        }
        return jsonResponse({
          items: [projectATaskRequests === 1 ? TASK : { ...TASK, status: "in_progress" }],
          nextCursor: null,
        });
      }
      return jsonResponse({ items: [TASK_B], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  await user.click(await screen.findByRole("button", { name: "开始任务" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("任务更新已提交，但列表刷新失败");
  await user.click(screen.getByRole("button", { name: /搜索体验升级/ }));

  const projectBTask = await screen.findByRole("article", { name: TASK_B.title });
  expect(within(projectBTask).getByRole("button", { name: "开始任务" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: /知识库迁移/ }));

  const projectATask = await screen.findByRole("article", { name: TASK.title });
  expect(await screen.findByRole("alert")).toHaveTextContent("任务列表可能不是最新");
  expect(within(projectATask).getByRole("button", { name: "开始任务" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重试刷新任务" }));

  expect(await within(projectATask).findByText("进行中")).toBeInTheDocument();
  expect(within(projectATask).queryByRole("button", { name: "开始任务" })).toBeNull();
  expect(within(projectATask).getByRole("button", { name: "完成任务" })).toBeEnabled();
  expect(screen.queryByText("任务列表可能不是最新")).toBeNull();
  expect(projectATaskRequests).toBe(4);
});

test("a delayed transition invalidates and refetches its initiating project after selection changes", async () => {
  const transition = deferred<Response>();
  let projectATaskRequests = 0;
  let projectBTaskRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT, PROJECT_B], nextCursor: null });
      }
      if (url.pathname === `/api/v1/tasks/${TASK.id}/status` && method === "PATCH") {
        return transition.promise;
      }
      if (url.pathname === `/api/v1/projects/${PROJECT.id}/tasks`) {
        projectATaskRequests += 1;
        return jsonResponse({
          items: [projectATaskRequests === 1 ? TASK : { ...TASK, status: "in_progress" }],
          nextCursor: null,
        });
      }
      projectBTaskRequests += 1;
      return jsonResponse({ items: [TASK_B], nextCursor: null });
    }),
  );
  const user = userEvent.setup();
  const { queryClient } = renderProjects();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  await user.click(await screen.findByRole("button", { name: "开始任务" }));
  await user.click(screen.getByRole("button", { name: /搜索体验升级/ }));

  const projectBTask = await screen.findByRole("article", { name: TASK_B.title });
  expect(within(projectBTask).getByRole("button", { name: "开始任务" })).toBeEnabled();
  transition.resolve(jsonResponse({ ...TASK, status: "in_progress" }));

  await waitFor(() => expect(projectATaskRequests).toBe(2));
  expect(projectBTaskRequests).toBe(1);
  expect(invalidate).toHaveBeenCalledTimes(1);
  expect(invalidate).toHaveBeenCalledWith({
    queryKey: taskKeys.list(IDENTITY.organization.id, PROJECT.id),
    exact: true,
    refetchType: "all",
  });
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a delayed transition failure does not leak its pending or error state into another project", async () => {
  const transition = deferred<Response>();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT, PROJECT_B], nextCursor: null });
      }
      if (url.pathname === `/api/v1/tasks/${TASK.id}/status` && method === "PATCH") {
        return transition.promise;
      }
      if (url.pathname === `/api/v1/projects/${PROJECT.id}/tasks`) {
        return jsonResponse({ items: [TASK], nextCursor: null });
      }
      return jsonResponse({ items: [TASK_B], nextCursor: null });
    }),
  );
  const user = userEvent.setup();
  const { queryClient } = renderProjects();

  await user.click(await screen.findByRole("button", { name: "开始任务" }));
  await user.click(screen.getByRole("button", { name: /搜索体验升级/ }));

  const projectBTask = await screen.findByRole("article", { name: TASK_B.title });
  expect(within(projectBTask).getByRole("button", { name: "开始任务" })).toBeEnabled();
  transition.resolve(jsonResponse(
    { code: "database_unavailable", message: "任务状态更新失败", traceId: "trace-transition" },
    503,
  ));

  await waitFor(() => {
    const mutation = queryClient.getMutationCache().getAll().at(-1);
    expect(mutation?.state.status).toBe("error");
  });
  expect(screen.queryByText("任务状态更新失败")).toBeNull();
  expect(within(projectBTask).getByRole("button", { name: "开始任务" })).toBeEnabled();
});

test("project pagination keeps the first page while loading, failing, and retrying the next cursor", async () => {
  const nextPage = deferred<Response>();
  let nextPageAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        if (url.searchParams.get("cursor") === null) {
          return jsonResponse({ items: [PROJECT], nextCursor: "projects-page-2" });
        }
        expect(url.searchParams.get("cursor")).toBe("projects-page-2");
        nextPageAttempts += 1;
        if (nextPageAttempts === 1) return nextPage.promise;
        return jsonResponse({ items: [PROJECT_B], nextCursor: null });
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  await user.click(await screen.findByRole("button", { name: "加载更多项目" }));
  expect(screen.getByRole("button", { name: "正在加载更多项目" })).toBeDisabled();
  expect(screen.getByRole("button", { name: /知识库迁移/ })).toBeInTheDocument();
  nextPage.resolve(jsonResponse(
    { code: "database_unavailable", message: "更多项目暂时无法加载", traceId: "trace-project-page" },
    503,
  ));

  expect(await screen.findByRole("alert")).toHaveTextContent("更多项目暂时无法加载");
  expect(screen.queryByText("项目列表可能不是最新")).toBeNull();
  expect(screen.queryByRole("button", { name: "重试刷新项目" })).toBeNull();
  expect(screen.getByRole("button", { name: /知识库迁移/ })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重新加载更多项目" }));

  expect(await screen.findByRole("button", { name: /搜索体验升级/ })).toBeInTheDocument();
  expect(screen.getByText("已加载 2 个")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /加载更多项目/ })).toBeNull();
});

test("task pagination keeps the first page while loading, failing, and retrying the next cursor", async () => {
  const nextPage = deferred<Response>();
  let nextPageAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      if (url.searchParams.get("cursor") === null) {
        return jsonResponse({ items: [TASK], nextCursor: "tasks-page-2" });
      }
      expect(url.searchParams.get("cursor")).toBe("tasks-page-2");
      nextPageAttempts += 1;
      if (nextPageAttempts === 1) return nextPage.promise;
      return jsonResponse({ items: [TASK_PAGE_2], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  await user.click(await screen.findByRole("button", { name: "加载更多任务" }));
  expect(screen.getByRole("button", { name: "正在加载更多任务" })).toBeDisabled();
  expect(screen.getByRole("article", { name: TASK.title })).toBeInTheDocument();
  nextPage.resolve(jsonResponse(
    { code: "database_unavailable", message: "更多任务暂时无法加载", traceId: "trace-task-page" },
    503,
  ));

  expect(await screen.findByRole("alert")).toHaveTextContent("更多任务暂时无法加载");
  expect(screen.getByRole("article", { name: TASK.title })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重新加载更多任务" }));

  expect(await screen.findByRole("article", { name: TASK_PAGE_2.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /加载更多任务/ })).toBeNull();
});
