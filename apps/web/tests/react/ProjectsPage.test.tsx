import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import type { IdentityContext } from "../../src/api/auth.ts";
import { projectKeys, taskKeys } from "../../src/queries/projects.ts";
import { ProjectsPage } from "../../src/pages/ProjectsPage.tsx";
import {
  SessionProvider,
  useSession,
} from "../../src/session/SessionContext.tsx";

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
  revision: 1,
  name: "知识库迁移",
  description: "把团队资料迁入统一知识层。",
  createdAt: "2026-08-01T08:00:00Z",
  updatedAt: "2026-08-08T08:00:00Z",
};

const PROJECT_B = {
  id: "00000000-0000-4000-8000-000000004002",
  revision: 1,
  name: "搜索体验升级",
  description: "缩短团队查找资料的路径。",
  createdAt: "2026-08-03T08:00:00Z",
  updatedAt: "2026-08-08T09:00:00Z",
};

const TASK = {
  id: "00000000-0000-4000-8000-000000005001",
  projectId: PROJECT.id,
  revision: 1,
  description: null,
  assigneeUserId: null,
  parentTaskId: null,
  stageId: null,
  milestoneId: null,
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
  revision: 1,
  description: null,
  assigneeUserId: null,
  parentTaskId: null,
  stageId: null,
  milestoneId: null,
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

// Additive structure reads use complete fixtures. Existing task requests still
// pass through each scenario's own HTTP handler and exact assertions.
function structureFixture(input: RequestInfo | URL): Response | undefined {
  const request = input instanceof Request ? input : new Request(input);
  if (request.method !== "GET") return;
  const path = new URL(request.url).pathname;
  if (/\/projects\/[^/]+\/(stages|milestones)$/.test(path)) return jsonResponse({items: [], nextCursor: null});
  if (path === `/api/v1/projects/${PROJECT.id}`) return jsonResponse(PROJECT);
  if (path === `/api/v1/projects/${PROJECT_B.id}`) return jsonResponse(PROJECT_B);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function requestDetails(input: RequestInfo | URL, init?: RequestInit) {
  if (input instanceof Request) {
    return {
      url: new URL(input.url),
      method: input.method,
      headers: input.headers,
    };
  }
  return {
    url: new URL(String(input)),
    method: init?.method ?? "GET",
    headers: new Headers(init?.headers),
  };
}

function renderProjects(
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
  identity = IDENTITY,
) {
  const sessionSignal = { current: null as AbortSignal | null };

  function SessionProbe() {
    const { session, status } = useSession();
    const location = useLocation();
    if (session !== null) sessionSignal.current = session.signal;
    return (
      <div hidden>
        <output data-testid="session-status">{status}</output>
        <output data-testid="session-location">{location.pathname}</output>
      </div>
    );
  }

  return {
    queryClient,
    sessionSignal,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/projects"]}>
          <SessionProvider
            restoredIdentity={identity}
            sessionApi={{
              restore: async () => identity,
              logout: async () => undefined,
            }}
          >
            <ProjectsPage />
            <SessionProbe />
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
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => undefined)),
  );

  renderProjects();

  const workspace = screen.getByRole("region", { name: "项目工作区" });
  expect(workspace).toHaveAttribute("aria-busy", "true");
  expect(within(workspace).getByText("正在加载项目")).toBeInTheDocument();
  expect(
    workspace.querySelectorAll(".project-skeleton").length,
  ).toBeGreaterThan(1);
  expect(screen.queryByRole("img", { name: /岑宁/ })).toBeNull();
});

test("node selection opens existing details and graph refresh keeps the list in sync", async () => {
  let task = {...TASK};
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const {url} = requestDetails(input);
    if (url.pathname.endsWith("/task-graph")) return jsonResponse({
      project: PROJECT, readAt:"2026-10-23T13:00:00Z", stages:[], milestones:[], dependencies:[],
      tasks:[{id:task.id, projectId:task.projectId, title:task.title, revision:task.revision, status:task.status, stageId:null, milestoneId:null}],
    });
    const fixture = structureFixture(input);
    if (fixture) return fixture;
    if (url.pathname === "/api/v1/projects") return jsonResponse({items:[PROJECT],nextCursor:null});
    if (url.pathname === `/api/v1/tasks/${TASK.id}`) return jsonResponse(task);
    if (url.pathname.endsWith("/tasks")) return jsonResponse({items:[task],nextCursor:null});
    return jsonResponse({items:[],nextCursor:null});
  }));
  const user = userEvent.setup();
  renderProjects(undefined, {...IDENTITY, membership:{...IDENTITY.membership,role:"viewer"}});
  await screen.findByRole("heading",{name:TASK.title});
  await user.click(screen.getByRole("button",{name:"节点图"}));
  await user.click(await screen.findByRole("button",{name:`查看任务：${TASK.title}，待处理`}));
  expect(await screen.findByRole("heading",{name:"任务详情"})).toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"关闭详情"}));
  task = {...task, title:"外部窗口更新后的任务", revision:2};
  await user.click(screen.getByRole("button",{name:"刷新节点图"}));
  await screen.findByRole("button",{name:/查看任务：外部窗口更新后的任务/});
  await user.click(screen.getByRole("button",{name:"任务列表"}));
  expect(await screen.findByRole("heading",{name:task.title})).toBeInTheDocument();
});

test("an organization with no projects gets a clear empty state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse({ items: [], nextCursor: null })),
  );

  renderProjects();

  expect(
    await screen.findByRole("heading", { name: "还没有项目" }),
  ).toBeInTheDocument();
  expect(screen.getByText("项目创建后会显示在这里。")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /岑宁/ })).toHaveAttribute(
    "data-variant",
    "full",
  );
  expect(screen.getByRole("button", { name: "创建第一个项目" })).toBeInTheDocument();
});

test("an empty workspace can create its first real project and enter the task workspace", async () => {
  let created = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const request = input instanceof Request ? input : new Request(input);
    const {url, method} = requestDetails(input);
    if (url.pathname === "/api/v1/projects" && method === "POST") {
      expect(request.headers.get("X-CSRF-Token")).toBe(IDENTITY.csrfToken);
      expect(await request.json()).toEqual({name:PROJECT.name,description:PROJECT.description});
      created = true;
      return jsonResponse(PROJECT,201);
    }
    const fixture=structureFixture(input); if(fixture)return fixture;
    if(url.pathname === "/api/v1/projects") return jsonResponse({items:created?[PROJECT]:[],nextCursor:null});
    return jsonResponse({items:[],nextCursor:null});
  }));
  const user=userEvent.setup();renderProjects();
  await user.click(await screen.findByRole("button",{name:"创建第一个项目"}));
  await user.type(screen.getByRole("textbox",{name:"项目名称"}),PROJECT.name);
  await user.type(screen.getByRole("textbox",{name:"项目说明（选填）"}),PROJECT.description);
  await user.click(screen.getByRole("button",{name:"创建项目"}));
  expect(await screen.findByRole("heading",{name:PROJECT.name})).toBeInTheDocument();
  expect(screen.getByRole("button",{name:"创建任务"})).toBeInTheDocument();
});

test("first-project creation never posts again when only the list refresh failed", async () => {
  let created=false, failRefresh=true, posts=0;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const {url,method}=requestDetails(input);
    if(url.pathname==="/api/v1/projects"&&method==="POST"){created=true;posts++;return jsonResponse(PROJECT,201);}
    const fixture=structureFixture(input);if(fixture)return fixture;
    if(url.pathname==="/api/v1/projects"){
      if(created&&failRefresh)return jsonResponse({code:"database_unavailable",message:"列表读取失败",traceId:"first-project-refresh"},503);
      return jsonResponse({items:created?[PROJECT]:[],nextCursor:null});
    }
    return jsonResponse({items:[],nextCursor:null});
  }));
  const user=userEvent.setup();renderProjects();
  await user.click(await screen.findByRole("button",{name:"创建第一个项目"}));
  await user.type(screen.getByRole("textbox",{name:"项目名称"}),PROJECT.name);
  await user.click(screen.getByRole("button",{name:"创建项目"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("项目已创建");
  expect(screen.queryByRole("button",{name:"创建项目"})).not.toBeInTheDocument();
  failRefresh=false;
  await user.click(screen.getByRole("button",{name:"重新读取项目"}));
  await screen.findByRole("heading",{name:PROJECT.name});
  expect(posts).toBe(1);
});

test("read-only users do not get a first-project creation control",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>jsonResponse({items:[],nextCursor:null})));
  renderProjects(undefined,{...IDENTITY,membership:{...IDENTITY.membership,role:"viewer"}});
  await screen.findByRole("heading",{name:"还没有项目"});
  expect(screen.queryByRole("button",{name:"创建第一个项目"})).not.toBeInTheDocument();
});

test("a lost creation response requires list reconciliation and cannot send a duplicate POST",async()=>{
  let created=false, posts=0;
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const {url,method}=requestDetails(input);
    if(url.pathname==="/api/v1/projects"&&method==="POST"){created=true;posts++;throw new TypeError("response lost");}
    const fixture=structureFixture(input);if(fixture)return fixture;
    if(url.pathname==="/api/v1/projects")return jsonResponse({items:created?[PROJECT]:[],nextCursor:null});
    return jsonResponse({items:[],nextCursor:null});
  }));
  const user=userEvent.setup();renderProjects();
  await user.click(await screen.findByRole("button",{name:"创建第一个项目"}));
  await user.type(screen.getByRole("textbox",{name:"项目名称"}),PROJECT.name);
  await user.click(screen.getByRole("button",{name:"创建项目"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("未收到创建确认");
  expect(screen.queryByRole("button",{name:"创建项目"})).not.toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"核对项目列表"}));
  await screen.findByText(/已读取全部可访问项目/);
  expect(screen.getByRole("textbox",{name:"项目名称"})).toHaveValue(PROJECT.name);
  expect(screen.getByRole("textbox",{name:"项目名称"})).toBeDisabled();
  expect(screen.queryByRole("button",{name:"创建项目"})).not.toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"关闭并查看项目列表"}));
  await screen.findByRole("heading",{name:PROJECT.name});
  expect(posts).toBe(1);
});

test("a failed project request exposes retry and recovers", async () => {
  let attempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      attempts += 1;
      if (attempts === 1) {
        return jsonResponse(
          {
            code: "database_unavailable",
            message: "项目暂时无法加载",
            traceId: "trace-projects",
          },
          503,
        );
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "项目暂时无法加载",
  );
  await user.click(screen.getByRole("button", { name: "重新加载项目" }));

  expect(
    await screen.findByRole("heading", { name: "还没有项目" }),
  ).toBeInTheDocument();
  expect(attempts).toBe(2);
});

test("a background project refresh failure keeps the rail and exposes a contextual retry", async () => {
  let projectRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        projectRequests += 1;
        if (projectRequests === 2) {
          return jsonResponse(
            {
              code: "database_unavailable",
              message: "项目列表刷新失败",
              traceId: "trace-project-refresh",
            },
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

  expect(
    await screen.findByRole("button", { name: /知识库迁移/ }),
  ).toBeInTheDocument();
  await queryClient.invalidateQueries({
    queryKey: projectKeys.list(IDENTITY.organization.id),
    exact: true,
  });

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("项目列表可能不是最新");
  expect(alert).toHaveTextContent("项目列表刷新失败");
  expect(
    screen.getByRole("button", { name: /知识库迁移/ }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重试刷新项目" }));

  expect(
    await screen.findByRole("button", { name: /搜索体验升级/ }),
  ).toBeInTheDocument();
  expect(screen.queryByText("项目列表可能不是最新")).toBeNull();
  expect(projectRequests).toBe(3);
});

test("a background project refresh failure keeps the empty state and exposes a contextual retry", async () => {
  let projectRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        projectRequests += 1;
        if (projectRequests === 2) {
          return jsonResponse(
            {
              code: "database_unavailable",
              message: "项目列表刷新失败",
              traceId: "trace-empty-project-refresh",
            },
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

  expect(
    await screen.findByRole("heading", { name: "还没有项目" }),
  ).toBeInTheDocument();
  await queryClient.invalidateQueries({
    queryKey: projectKeys.list(IDENTITY.organization.id),
    exact: true,
  });

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("项目列表可能不是最新");
  expect(alert).toHaveTextContent("项目列表刷新失败");
  expect(
    screen.getByRole("heading", { name: "还没有项目" }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重试刷新项目" }));

  expect(
    await screen.findByRole("button", { name: /知识库迁移/ }),
  ).toBeInTheDocument();
  expect(screen.queryByText("项目列表可能不是最新")).toBeNull();
  expect(projectRequests).toBe(3);
});

test("the selected project shows an explicit empty task workspace", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );

  renderProjects();

  const projectButton = await screen.findByRole("button", {
    name: /知识库迁移/,
  });
  expect(projectButton).toHaveAttribute("aria-pressed", "true");
  expect(
    await screen.findByRole("heading", { name: "这个项目还没有任务" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("img", { name: /岑宁/ })).toBeNull();
  expect(screen.getByRole("button", { name: "创建任务" })).toBeInTheDocument();
});

test("project selectors control the labelled task region and announce only user changes", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT, PROJECT_B], nextCursor: null });
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  const firstRegionId = `project-task-workspace-${PROJECT.id}`;
  const secondRegionId = `project-task-workspace-${PROJECT_B.id}`;
  const firstButton = await screen.findByRole("button", { name: /知识库迁移/ });
  const secondButton = screen.getByRole("button", { name: /搜索体验升级/ });
  const switcher = screen.getByLabelText("切换项目");
  const announcement = document.querySelector(
    ".project-selection-announcement",
  );
  const firstRegion = screen.getByRole("region", { name: PROJECT.name });

  expect(firstRegion).toHaveAttribute("id", firstRegionId);
  expect(firstRegion).toHaveAttribute(
    "aria-labelledby",
    `${firstRegionId}-heading`,
  );
  expect(firstButton).toHaveAttribute("aria-controls", firstRegionId);
  expect(secondButton).toHaveAttribute("aria-controls", firstRegionId);
  expect(switcher).toHaveAttribute("aria-controls", firstRegionId);
  expect(announcement).toHaveAttribute("aria-live", "polite");
  expect(announcement).toBeEmptyDOMElement();

  await user.click(firstButton);

  expect(screen.getByRole("region", { name: PROJECT.name })).toHaveAttribute(
    "id",
    firstRegionId,
  );
  expect(announcement).toBeEmptyDOMElement();

  await user.click(secondButton);

  expect(
    await screen.findByRole("region", { name: PROJECT_B.name }),
  ).toHaveAttribute("id", secondRegionId);
  expect(secondButton).toHaveAttribute("aria-controls", secondRegionId);
  expect(switcher).toHaveAttribute("aria-controls", secondRegionId);
  expect(announcement).toHaveTextContent(`已选择项目：${PROJECT_B.name}`);

  await user.selectOptions(switcher, PROJECT.id);

  expect(
    await screen.findByRole("region", { name: PROJECT.name }),
  ).toHaveAttribute("id", firstRegionId);
  expect(announcement).toHaveTextContent(`已选择项目：${PROJECT.name}`);
});

test("the selected project links to its real knowledge workspace", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url } = requestDetails(input, init);
      return url.pathname === "/api/v1/projects"
        ? jsonResponse({ items: [PROJECT], nextCursor: null })
        : jsonResponse({ items: [], nextCursor: null });
    }),
  );

  renderProjects();

  expect(
    await screen.findByRole("link", { name: "打开知识工作区" }),
  ).toHaveAttribute("href", `/projects/${PROJECT.id}/knowledge`);
});

test("a failed task request exposes retry inside the selected project", async () => {
  let taskAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      taskAttempts += 1;
      if (taskAttempts === 1) {
        return jsonResponse(
          {
            code: "database_unavailable",
            message: "任务暂时无法加载",
            traceId: "trace-tasks",
          },
          503,
        );
      }
      return jsonResponse({ items: [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "任务暂时无法加载",
  );
  expect(screen.queryByRole("img", { name: /岑宁/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "重新加载任务" }));

  expect(
    await screen.findByRole("heading", { name: "这个项目还没有任务" }),
  ).toBeInTheDocument();
  expect(taskAttempts).toBe(2);
});

test("task rows show status, priority, due date, acceptance criteria, and legal actions", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
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
  expect(
    within(task).getByText("全部资料都有负责人并通过抽查。"),
  ).toBeInTheDocument();
  expect(within(task).getByRole("button", { name: "开始任务" })).toBeEnabled();
  expect(
    within(task).queryByRole("button", { name: /完成|阻塞|取消/ }),
  ).toBeNull();
});

test("task rows safely render an offset RFC3339 leap-second due date", async () => {
  const dueAt = "1991-01-01T00:59:60+01:00";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      return jsonResponse({ items: [{ ...TASK, dueAt }], nextCursor: null });
    }),
  );
  const expectedDate = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date("1990-12-31T23:59:59Z"));

  renderProjects();

  const task = await screen.findByRole("article", { name: "核对迁移清单" });
  expect(within(task).getByText(expectedDate)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("viewer membership renders project tasks without mutation controls", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const url = new URL(input instanceof Request ? input.url : String(input));
      return url.pathname === "/api/v1/projects"
        ? jsonResponse({ items: [PROJECT], nextCursor: null })
        : jsonResponse({ items: [TASK], nextCursor: null });
    }),
  );

  renderProjects(undefined, {
    ...IDENTITY,
    membership: { ...IDENTITY.membership, role: "viewer" },
  });

  const task = await screen.findByRole("article", { name: "核对迁移清单" });
  expect(within(task).queryByRole("button", { name: "开始任务" })).toBeNull();
  expect(within(task).getByText("只读权限")).toBeInTheDocument();
});

test("an unknown membership role fails closed without mutation controls", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const url = new URL(input instanceof Request ? input.url : String(input));
      return url.pathname === "/api/v1/projects"
        ? jsonResponse({ items: [PROJECT], nextCursor: null })
        : jsonResponse({ items: [TASK], nextCursor: null });
    }),
  );

  renderProjects(undefined, {
    ...IDENTITY,
    membership: {
      ...IDENTITY.membership,
      role: "future_role" as IdentityContext["membership"]["role"],
    },
  });

  const task = await screen.findByRole("article", { name: "核对迁移清单" });
  expect(within(task).getByText("待处理")).toBeInTheDocument();
  expect(within(task).queryByRole("button", { name: "开始任务" })).toBeNull();
  expect(within(task).getByText("只读权限")).toBeInTheDocument();
});

test("concealed transition failure explains that edit permission may have changed", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request = input instanceof Request ? input : new Request(input);
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      if (request.method === "PATCH") {
        return jsonResponse(
          {
            code: "not_found",
            message: "资源不存在",
            traceId: "trace-revoked-write",
          },
          404,
        );
      }
      return jsonResponse({ items: [TASK], nextCursor: null });
    }),
  );

  renderProjects();
  await user.click(await screen.findByRole("button", { name: "开始任务" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "项目不存在或你已失去编辑权限，请刷新项目列表",
  );
});

test("a pending status transition disables actions and refreshes the scoped task queries", async () => {
  const transition = deferred<Response>();
  let taskRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url, method, headers } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      if (
        url.pathname === `/api/v1/tasks/${TASK.id}/status` &&
        method === "PATCH"
      ) {
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
    expect(invalidate).toHaveBeenCalledWith(
      {
        queryKey: taskKeys.list(IDENTITY.organization.id, PROJECT.id),
        exact: true,
        refetchType: "all",
      },
      { throwOnError: true },
    ),
  );
  expect(taskRequests).toBe(2);
});

test("a committed transition with a failed task refresh keeps old data and exposes refresh retry", async () => {
  let taskRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      if (
        url.pathname === `/api/v1/tasks/${TASK.id}/status` &&
        method === "PATCH"
      ) {
        return jsonResponse({ ...TASK, status: "in_progress" });
      }
      taskRequests += 1;
      if (taskRequests === 2) {
        return jsonResponse(
          {
            code: "database_unavailable",
            message: "任务列表刷新失败",
            traceId: "trace-task-refresh",
          },
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
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT, PROJECT_B], nextCursor: null });
      }
      if (
        url.pathname === `/api/v1/tasks/${TASK.id}/status` &&
        method === "PATCH"
      ) {
        return jsonResponse({ ...TASK, status: "in_progress" });
      }
      if (url.pathname === `/api/v1/projects/${PROJECT.id}/tasks`) {
        projectATaskRequests += 1;
        if (projectATaskRequests === 2 || projectATaskRequests === 3) {
          return jsonResponse(
            {
              code: "database_unavailable",
              message: "任务列表刷新失败",
              traceId: "trace-task-remount",
            },
            503,
          );
        }
        return jsonResponse({
          items: [
            projectATaskRequests === 1
              ? TASK
              : { ...TASK, status: "in_progress" },
          ],
          nextCursor: null,
        });
      }
      return jsonResponse({ items: [TASK_B], nextCursor: null });
    }),
  );
  const user = userEvent.setup();

  renderProjects();

  await user.click(await screen.findByRole("button", { name: "开始任务" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "任务更新已提交，但列表刷新失败",
  );
  await user.click(screen.getByRole("button", { name: /搜索体验升级/ }));

  const projectBTask = await screen.findByRole("article", {
    name: TASK_B.title,
  });
  expect(
    within(projectBTask).getByRole("button", { name: "开始任务" }),
  ).toBeEnabled();
  await user.click(screen.getByRole("button", { name: /知识库迁移/ }));

  const projectATask = await screen.findByRole("article", { name: TASK.title });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "任务列表可能不是最新",
  );
  expect(
    within(projectATask).getByRole("button", { name: "开始任务" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重试刷新任务" }));

  expect(await within(projectATask).findByText("进行中")).toBeInTheDocument();
  expect(
    within(projectATask).queryByRole("button", { name: "开始任务" }),
  ).toBeNull();
  expect(
    within(projectATask).getByRole("button", { name: "完成任务" }),
  ).toBeEnabled();
  expect(screen.queryByText("任务列表可能不是最新")).toBeNull();
  expect(projectATaskRequests).toBe(4);
});

test("a delayed transition is cancelled and cannot update old caches after project selection changes", async () => {
  const transition = deferred<Response>();
  let transitionSignal: AbortSignal | undefined;
  let projectATaskRequests = 0;
  let projectBTaskRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT, PROJECT_B], nextCursor: null });
      }
      if (
        url.pathname === `/api/v1/tasks/${TASK.id}/status` &&
        method === "PATCH"
      ) {
        transitionSignal =
          input instanceof Request ? input.signal : (init?.signal ?? undefined);
        return transition.promise;
      }
      if (url.pathname === `/api/v1/projects/${PROJECT.id}/tasks`) {
        projectATaskRequests += 1;
        return jsonResponse({
          items: [
            projectATaskRequests === 1
              ? TASK
              : { ...TASK, status: "in_progress" },
          ],
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

  const projectBTask = await screen.findByRole("article", {
    name: TASK_B.title,
  });
  expect(
    within(projectBTask).getByRole("button", { name: "开始任务" }),
  ).toBeEnabled();
  transition.resolve(jsonResponse({ ...TASK, status: "in_progress" }));

  expect(transitionSignal?.aborted).toBe(true);
  await waitFor(() =>
    expect(queryClient.getMutationCache().getAll().at(-1)?.state.status).toBe(
      "success",
    ),
  );
  expect(projectATaskRequests).toBe(1);
  expect(projectBTaskRequests).toBe(1);
  expect(invalidate).not.toHaveBeenCalled();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a delayed transition failure does not leak its pending or error state into another project", async () => {
  const transition = deferred<Response>();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT, PROJECT_B], nextCursor: null });
      }
      if (
        url.pathname === `/api/v1/tasks/${TASK.id}/status` &&
        method === "PATCH"
      ) {
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

  const projectBTask = await screen.findByRole("article", {
    name: TASK_B.title,
  });
  expect(
    within(projectBTask).getByRole("button", { name: "开始任务" }),
  ).toBeEnabled();
  transition.resolve(
    jsonResponse(
      {
        code: "database_unavailable",
        message: "任务状态更新失败",
        traceId: "trace-transition",
      },
      503,
    ),
  );

  await waitFor(() => {
    const mutation = queryClient.getMutationCache().getAll().at(-1);
    expect(mutation?.state.status).toBe("error");
  });
  expect(screen.queryByText("任务状态更新失败")).toBeNull();
  expect(
    within(projectBTask).getByRole("button", { name: "开始任务" }),
  ).toBeEnabled();
});

test("a session-invalid task transition clears the authenticated mutation boundary", async () => {
  let transitionRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url, method } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      }
      if (url.pathname === `/api/v1/projects/${PROJECT.id}/tasks`) {
        return jsonResponse({ items: [TASK], nextCursor: null });
      }
      if (
        url.pathname === `/api/v1/tasks/${TASK.id}/status` &&
        method === "PATCH"
      ) {
        transitionRequests += 1;
        return jsonResponse(
          {
            code: "session_invalid",
            message: "会话已过期",
            traceId: "trace-task-transition-session",
          },
          401,
        );
      }
      throw new Error(`unexpected request: ${method} ${url.pathname}`);
    }),
  );
  const user = userEvent.setup();
  const { queryClient, sessionSignal } = renderProjects();

  await user.click(await screen.findByRole("button", { name: "开始任务" }));

  await waitFor(() =>
    expect(screen.getByTestId("session-status")).toHaveTextContent("anonymous"),
  );
  expect(screen.getByTestId("session-location")).toHaveTextContent("/login");
  expect(transitionRequests).toBe(1);
  expect(sessionSignal.current?.aborted).toBe(true);
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
});

test("project pagination keeps the first page while loading, failing, and retrying the next cursor", async () => {
  const nextPage = deferred<Response>();
  let nextPageAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const { url } = requestDetails(input, init);
      if (url.pathname === "/api/v1/projects") {
        if (url.searchParams.get("cursor") === null) {
          return jsonResponse({
            items: [PROJECT],
            nextCursor: "projects-page-2",
          });
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
  expect(
    screen.getByRole("button", { name: "正在加载更多项目" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: /知识库迁移/ }),
  ).toBeInTheDocument();
  nextPage.resolve(
    jsonResponse(
      {
        code: "database_unavailable",
        message: "更多项目暂时无法加载",
        traceId: "trace-project-page",
      },
      503,
    ),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "更多项目暂时无法加载",
  );
  expect(screen.queryByText("项目列表可能不是最新")).toBeNull();
  expect(screen.queryByRole("button", { name: "重试刷新项目" })).toBeNull();
  expect(
    screen.getByRole("button", { name: /知识库迁移/ }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重新加载更多项目" }));

  expect(
    await screen.findByRole("button", { name: /搜索体验升级/ }),
  ).toBeInTheDocument();
  expect(screen.getByText("已加载 2 个")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /加载更多项目/ })).toBeNull();
});

test("task pagination keeps the first page while loading, failing, and retrying the next cursor", async () => {
  const nextPage = deferred<Response>();
  let nextPageAttempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
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
  expect(
    screen.getByRole("button", { name: "正在加载更多任务" }),
  ).toBeDisabled();
  expect(screen.getByRole("article", { name: TASK.title })).toBeInTheDocument();
  nextPage.resolve(
    jsonResponse(
      {
        code: "database_unavailable",
        message: "更多任务暂时无法加载",
        traceId: "trace-task-page",
      },
      503,
    ),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "更多任务暂时无法加载",
  );
  expect(screen.getByRole("article", { name: TASK.title })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重新加载更多任务" }));

  expect(
    await screen.findByRole("article", { name: TASK_PAGE_2.title }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /加载更多任务/ })).toBeNull();
});

test("create and edit task fields through real SDK requests and preserve conflict drafts", async () => {
  let task = {
    ...TASK,
    revision: 1,
    description: null as string | null,
    assigneeUserId: null as string | null,
  };
  let created = false;
  let stale = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request =
        input instanceof Request ? input : new Request(String(input), init);
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/projects")
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      if (url.pathname.endsWith("/assignees"))
        return jsonResponse({
          items: [
            {
              userId: IDENTITY.user.id,
              displayName: "演示用户",
              role: "owner",
            },
          ],
          nextCursor: null,
        });
      if (url.pathname.endsWith("/dependencies"))
        return jsonResponse({ items: [], nextCursor: null });
      if (url.pathname.endsWith("/tasks")) {
        if (request.method === "POST") {
          expect(request.headers.get("X-CSRF-Token")).toBe(IDENTITY.csrfToken);
          const body = await request.json();
          task = { ...task, ...body };
          created = true;
          return jsonResponse(task, 201);
        }
        return jsonResponse({ items: created ? [task] : [], nextCursor: null });
      }
      if (request.method === "PATCH") {
        const body = await request.json();
        expect(body.expectedRevision).toBe(task.revision);
        if (stale)
          return jsonResponse(
            {
              code: "revision_conflict",
              message: "请重新读取任务",
              traceId: "edit-conflict",
            },
            409,
          );
        task = { ...task, ...body, revision: task.revision + 1 };
      }
      return jsonResponse(task);
    }),
  );
  const user = userEvent.setup();
  renderProjects();
  await user.click(await screen.findByRole("button", { name: "创建任务" }));
  await user.type(screen.getByLabelText("任务标题"), "新建任务");
  await user.type(screen.getByLabelText("任务描述"), "交付证据");
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  expect(
    await screen.findByRole("heading", { name: "新建任务", level: 3 }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看任务：新建任务" }));
  await user.clear(await screen.findByLabelText("任务标题"));
  await user.type(screen.getByLabelText("任务标题"), "更新任务");
  await user.selectOptions(screen.getByLabelText("负责人"), IDENTITY.user.id);
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  expect(
    await screen.findByRole("heading", { name: "更新任务", level: 3 }),
  ).toBeInTheDocument();
  expect(task.assigneeUserId).toBe(IDENTITY.user.id);
  stale = true;
  await user.clear(screen.getByLabelText("任务标题"));
  await user.type(screen.getByLabelText("任务标题"), "保留本地草稿");
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("重新读取");
  expect(screen.getByLabelText("任务标题")).toHaveValue("保留本地草稿");
  await user.click(
    screen.getByRole("button", { name: "重新读取最新版本（替换草稿）" }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("任务标题")).toHaveValue("更新任务"),
  );
});

test("a committed create with failed list refresh cannot submit duplicate writes", async () => {
  let created = false;
  let failRefresh = true;
  let writes = 0;
  const task = { ...TASK, title: "成功创建待刷新" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request =
        input instanceof Request ? input : new Request(String(input), init);
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/projects")
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      if (url.pathname.endsWith("/assignees"))
        return jsonResponse({ items: [], nextCursor: null });
      if (request.method === "POST") {
        writes++;
        created = true;
        return jsonResponse(task, 201);
      }
      if (created && failRefresh)
        return jsonResponse(
          {
            code: "database_unavailable",
            message: "列表刷新失败",
            traceId: "create-refresh",
          },
          503,
        );
      return jsonResponse({ items: created ? [task] : [], nextCursor: null });
    }),
  );
  const user = userEvent.setup();
  renderProjects();
  await user.click(await screen.findByRole("button", { name: "创建任务" }));
  await user.type(screen.getByLabelText("任务标题"), task.title);
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "任务已保存，但刷新失败",
  );
  expect(screen.getByRole("button", { name: "保存任务" })).toBeDisabled();
  failRefresh = false;
  await user.click(
    within(screen.getByRole("form", { name: "创建任务" })).getByRole("button", {
      name: "重试刷新任务",
    }),
  );
  expect(
    await screen.findByRole("heading", { name: task.title, level: 3 }),
  ).toBeInTheDocument();
  expect(writes).toBe(1);
});

test("editing clears nullable fields explicitly and converts local due time to a timezone", async () => {
  let task = {
    ...TASK,
    description: "原描述",
    assigneeUserId: IDENTITY.user.id,
  };
  let patch: Record<string, unknown> = {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request =
        input instanceof Request ? input : new Request(String(input), init);
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/projects")
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      if (path.endsWith("/tasks"))
        return jsonResponse({ items: [task], nextCursor: null });
      if (path.endsWith("/assignees"))
        return jsonResponse({
          items: [
            {
              userId: IDENTITY.user.id,
              displayName: "演示用户",
              role: "owner",
            },
          ],
          nextCursor: null,
        });
      if (path.endsWith("/dependencies"))
        return jsonResponse({ items: [], nextCursor: null });
      if (request.method === "PATCH") {
        patch = await request.json();
        task = { ...task, ...patch, revision: 2 };
      }
      return jsonResponse(task);
    }),
  );
  const user = userEvent.setup();
  renderProjects();
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  await user.clear(await screen.findByLabelText("任务描述"));
  await user.clear(screen.getByLabelText("验收标准"));
  await user.selectOptions(screen.getByLabelText("负责人"), "");
  await user.selectOptions(screen.getByLabelText("优先级"), "critical");
  await user.click(screen.getByRole("button", { name: "无到期时间" }));
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  await waitFor(() =>
    expect(patch).toEqual({
      expectedRevision: 1,
      expectedProjectRevision: 1,
      description: null,
      acceptanceCriteria: null,
      assigneeUserId: null,
      dueAt: null,
      priority: "critical",
    }),
  );
});

test("read-only details expose dependencies while edit and assignment controls stay unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request =
        input instanceof Request ? input : new Request(String(input), init);
      const path = new URL(request.url).pathname;
      expect(request.method).toBe("GET");
      if (path === "/api/v1/projects")
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      if (path.endsWith("/tasks"))
        return jsonResponse({ items: [TASK], nextCursor: null });
      if (path.endsWith("/dependencies"))
        return jsonResponse({
          items: [
            {
              id: "00000000-0000-4000-8000-000000009001",
              predecessorTaskId: TASK_PAGE_2.id,
              successorTaskId: TASK.id,
              createdAt: TASK.createdAt,
            },
          ],
          nextCursor: null,
        });
      return jsonResponse(TASK);
    }),
  );
  const user = userEvent.setup();
  renderProjects(undefined, {
    ...IDENTITY,
    membership: { ...IDENTITY.membership, role: "viewer" },
  });
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  expect(
    await screen.findByRole("region", { name: "前置依赖" }),
  ).toHaveTextContent(TASK_PAGE_2.id);
  expect(screen.queryByRole("button", { name: "保存任务" })).toBeNull();
  expect(screen.queryByRole("button", { name: "添加依赖" })).toBeNull();
  expect(screen.queryByLabelText("负责人")).toBeNull();
});

test("project switching cancels pending task detail and discards its old editor", async () => {
  const pending = deferred<Response>();
  let detailSignal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request =
        input instanceof Request ? input : new Request(String(input), init);
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/projects")
        return jsonResponse({ items: [PROJECT, PROJECT_B], nextCursor: null });
      if (path === `/api/v1/tasks/${TASK.id}`) {
        detailSignal = request.signal;
        return pending.promise;
      }
      return jsonResponse({
        items: path.includes(PROJECT_B.id) ? [TASK_B] : [TASK],
        nextCursor: null,
      });
    }),
  );
  const user = userEvent.setup();
  renderProjects();
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  await screen.findByText("正在读取任务详情");
  await user.click(screen.getByRole("button", { name: /搜索体验升级/ }));
  expect(
    await screen.findByRole("article", { name: TASK_B.title }),
  ).toBeInTheDocument();
  expect(detailSignal?.aborted).toBe(true);
  pending.resolve(jsonResponse(TASK));
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "任务详情" })).toBeNull(),
  );
});

test("dependency pages must finish loading before writes and candidate pages remain available", async () => {
  const second = { ...TASK_PAGE_2 };
  const edge = {
    id: "00000000-0000-4000-8000-000000009101",
    predecessorTaskId: second.id,
    successorTaskId: TASK.id,
    createdAt: TASK.createdAt,
  };
  let secondPage = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request =
        input instanceof Request ? input : new Request(String(input), init);
      const url = new URL(request.url);
      if (url.pathname === "/api/v1/projects")
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      if (url.pathname.endsWith("/tasks"))
        return jsonResponse({
          items: [TASK, second],
          nextCursor: "more-candidates",
        });
      if (url.pathname.endsWith("/assignees"))
        return jsonResponse({ items: [], nextCursor: "more-members" });
      if (url.pathname.endsWith("/dependencies")) {
        if (url.searchParams.has("cursor")) {
          secondPage = true;
          return jsonResponse({ items: [], nextCursor: null });
        }
        return jsonResponse({ items: [edge], nextCursor: "more-edges" });
      }
      return jsonResponse(TASK);
    }),
  );
  const user = userEvent.setup();
  renderProjects();
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  const details = await screen.findByRole("region", { name: "任务详情" });
  const remove = await within(details).findByRole("button", {
    name: `删除依赖：${second.title}`,
  });
  expect(remove).toBeDisabled();
  expect(screen.queryByText("尚无前置依赖。")).toBeNull();
  expect(
    within(details).getByRole("button", { name: "加载更多负责人" }),
  ).toBeInTheDocument();
  expect(
    within(details).getByRole("button", { name: "加载更多候选任务" }),
  ).toBeInTheDocument();
  await user.click(
    within(details).getByRole("button", { name: "加载更多依赖" }),
  );
  await waitFor(() => expect(remove).toBeEnabled());
  expect(secondPage).toBe(true);
  expect(
    within(details).queryByRole("option", { name: second.title }),
  ).toBeNull();
});

function installStatusBoundary({
  conflict = false,
  conflictOn = "status",
  failure = null,
  statusPending,
  editPending,
  dependencyPending,
}: {
  conflict?: boolean;
  conflictOn?: "status" | "edit" | "dependency";
  failure?: "detail" | "dependencies" | "list" | null;
  statusPending?: ReturnType<typeof deferred<Response>>;
  editPending?: ReturnType<typeof deferred<Response>>;
  dependencyPending?: ReturnType<typeof deferred<Response>>;
} = {}) {
  let current = {
    ...TASK,
    status: TASK.status as import("../../src/api/projects.ts").TaskStatus,
  };
  let committed = false;
  let failRefresh = failure !== null;
  let conflictOnce = conflict;
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  let edges: Record<string, unknown>[] = [];
  const problem = (code: string, status: number) =>
    jsonResponse(
      {
        code,
        message:
          code === "revision_conflict"
            ? "任务已被更新，请重新读取最新版本"
            : "刷新读取失败",
        traceId: "status-recovery",
      },
      status,
    );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request =
        input instanceof Request ? input : new Request(String(input), init);
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/projects")
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      if (request.method === "GET") {
        if (path.endsWith("/assignees"))
          return jsonResponse({ items: [], nextCursor: null });
        const read = path.endsWith("/tasks")
          ? "list"
          : path.endsWith("/dependencies")
            ? "dependencies"
            : "detail";
        if (committed && failRefresh && read === failure)
          return problem("database_unavailable", 503);
        if (read === "list")
          return jsonResponse({
            items: [current, TASK_PAGE_2],
            nextCursor: null,
          });
        if (read === "dependencies")
          return jsonResponse({ items: edges, nextCursor: null });
        return jsonResponse(current);
      }
      const body = (await request.json()) as Record<string, unknown>;
      writes.push({ path, body });
      const operation = path.endsWith("/status")
        ? "status"
        : path.endsWith("/dependencies")
          ? "dependency"
          : "edit";
      if (operation === conflictOn && conflictOnce) {
        conflictOnce = false;
        current = { ...current, revision: 2, title: "服务器最新任务" };
      }
      if (body.expectedRevision !== current.revision)
        return problem("revision_conflict", 409);
      if (path.endsWith("/status")) {
        if (statusPending) {
          const response = await statusPending.promise;
          current = await response.clone().json();
          committed = true;
          return response;
        }
        current = {
          ...current,
          status: body.status as typeof current.status,
          revision: current.revision + 1,
        };
        committed = true;
        return jsonResponse(current);
      }
      if (path.endsWith("/dependencies")) {
        const response = dependencyPending
          ? await dependencyPending.promise
          : jsonResponse(
              {
                id: "00000000-0000-4000-8000-000000009201",
                predecessorTaskId: TASK_PAGE_2.id,
                successorTaskId: TASK.id,
                createdAt: TASK.createdAt,
              },
              201,
            );
        edges = [await response.clone().json()];
        current = { ...current, revision: current.revision + 1 };
        committed = true;
        return response;
      }
      if (editPending) {
        const response = await editPending.promise;
        current = await response.clone().json();
        committed = true;
        return response;
      }
      const { expectedRevision: _expectedRevision, ...fields } = body;
      current = { ...current, ...fields, revision: current.revision + 1 };
      committed = true;
      return jsonResponse(current);
    }),
  );
  return {
    writes,
    clearFailure() {
      failRefresh = false;
    },
  };
}

function taskAction(name: string, title = TASK.title) {
  return within(screen.getByRole("article", { name: title })).getByRole(
    "button",
    { name },
  );
}

test("status409 blocks stale writes until explicit latest-version reread", async () => {
  const boundary = installStatusBoundary({ conflict: true });
  const user = userEvent.setup();
  renderProjects();
  await screen.findByRole("article", { name: TASK.title });
  await user.click(taskAction("开始任务"));
  await screen.findByRole("alert");
  expect(taskAction("开始任务")).toBeDisabled();
  await user.click(taskAction("开始任务"));
  expect(boundary.writes).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "重新读取最新任务" }));
  await screen.findByRole("article", { name: "服务器最新任务" });
  await user.click(taskAction("开始任务", "服务器最新任务"));
  await waitFor(() => expect(boundary.writes).toHaveLength(2));
  expect(boundary.writes.map((write) => write.body.expectedRevision)).toEqual([
    1, 2,
  ]);
});

test("status409 retains dirty editor until a reread explicitly discloses draft replacement", async () => {
  const boundary = installStatusBoundary({ conflict: true });
  const user = userEvent.setup();
  renderProjects();
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  await user.clear(await screen.findByLabelText("任务标题"));
  await user.type(screen.getByLabelText("任务标题"), "本地状态冲突草稿");
  await user.click(taskAction("开始任务"));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("任务标题")).toHaveValue("本地状态冲突草稿");
  expect(screen.getByRole("button", { name: "保存任务" })).toBeDisabled();
  expect(screen.getByLabelText("添加前置任务")).toBeDisabled();
  expect(screen.getByText("重新读取会替换当前草稿。")).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "重新读取最新版本（替换草稿）" }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("任务标题")).toHaveValue("服务器最新任务"),
  );
  await user.clear(screen.getByLabelText("任务标题"));
  await user.type(screen.getByLabelText("任务标题"), "继续编辑");
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  await waitFor(() => expect(boundary.writes).toHaveLength(2));
  expect(boundary.writes[1]?.body.expectedRevision).toBe(2);
});

test("pending status disables detail/dependency writes and healthy completion preserves/rebases dirty draft", async () => {
  const pending = deferred<Response>();
  const boundary = installStatusBoundary({ statusPending: pending });
  const user = userEvent.setup();
  renderProjects();
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  await user.clear(await screen.findByLabelText("任务标题"));
  await user.type(screen.getByLabelText("任务标题"), "状态后继续的草稿");
  await user.click(taskAction("开始任务"));
  expect(taskAction("正在更新")).toBeDisabled();
  expect(screen.getByRole("button", { name: "保存任务" })).toBeDisabled();
  expect(screen.getByLabelText("添加前置任务")).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  expect(boundary.writes).toHaveLength(1);
  pending.resolve(
    jsonResponse({ ...TASK, status: "in_progress", revision: 2 }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "保存任务" })).toBeEnabled(),
  );
  expect(screen.getByLabelText("任务标题")).toHaveValue("状态后继续的草稿");
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  await waitFor(() => expect(boundary.writes).toHaveLength(2));
  expect(boundary.writes[1]?.body.expectedRevision).toBe(2);
});

test.each(["detail", "dependencies", "list"] as const)(
  "committed status with %s refresh failure blocks all writes until disclosed reread, without duplicate status requests",
  async (failure) => {
    const boundary = installStatusBoundary({ failure });
    const user = userEvent.setup();
    renderProjects();
    await user.click(
      await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
    );
    await user.clear(await screen.findByLabelText("任务标题"));
    await user.type(screen.getByLabelText("任务标题"), "已提交状态时保留草稿");
    await user.click(taskAction("开始任务"));
    await screen.findByText(/任务更新已提交，但.*刷新失败/);
    expect(screen.queryByText("任务状态更新失败")).toBeNull();
    expect(screen.getByLabelText("任务标题")).toHaveValue(
      "已提交状态时保留草稿",
    );
    expect(screen.getByRole("button", { name: "保存任务" })).toBeDisabled();
    expect(screen.getByLabelText("添加前置任务")).toBeDisabled();
    expect(
      taskAction(failure === "list" ? "开始任务" : "完成任务"),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "保存任务" }));
    expect(boundary.writes).toHaveLength(1);
    expect(screen.getByText("重新读取会替换当前草稿。")).toBeInTheDocument();
    boundary.clearFailure();
    await user.click(
      screen.getByRole("button", { name: "重新读取最新版本（替换草稿）" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "保存任务" })).toBeEnabled(),
    );
    expect(screen.getByLabelText("任务标题")).toHaveValue(TASK.title);
    expect(screen.getByLabelText("添加前置任务")).toBeEnabled();
    expect(boundary.writes).toHaveLength(1);
    await user.clear(screen.getByLabelText("任务标题"));
    await user.type(screen.getByLabelText("任务标题"), "恢复后继续编辑");
    await user.click(screen.getByRole("button", { name: "保存任务" }));
    await waitFor(() => expect(boundary.writes).toHaveLength(2));
    expect(boundary.writes[1]?.body.expectedRevision).toBe(2);
    expect(
      boundary.writes.filter((write) => write.path.endsWith("/status")),
    ).toHaveLength(1);
  },
);

test.each(["edit", "dependency"] as const)(
  "pending %s write also blocks status and the other detail controls",
  async (kind) => {
    const pending = deferred<Response>();
    const boundary = installStatusBoundary(
      kind === "edit"
        ? { editPending: pending }
        : { dependencyPending: pending },
    );
    const user = userEvent.setup();
    renderProjects();
    await user.click(
      await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
    );
    await screen.findByLabelText("任务标题");
    if (kind === "edit") {
      await user.clear(screen.getByLabelText("任务标题"));
      await user.type(screen.getByLabelText("任务标题"), "真实编辑");
      await user.click(screen.getByRole("button", { name: "保存任务" }));
    } else {
      await user.selectOptions(
        screen.getByLabelText("添加前置任务"),
        TASK_PAGE_2.id,
      );
      await user.click(screen.getByRole("button", { name: "添加依赖" }));
    }
    expect(taskAction("开始任务")).toBeDisabled();
    expect(screen.getByLabelText("添加前置任务")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /保存任务|正在保存/ }),
    ).toBeDisabled();
    expect(boundary.writes).toHaveLength(1);
    pending.resolve(
      kind === "edit"
        ? jsonResponse({ ...TASK, revision: 2 })
        : jsonResponse(
            {
              id: "00000000-0000-4000-8000-000000009201",
              predecessorTaskId: TASK_PAGE_2.id,
              successorTaskId: TASK.id,
              createdAt: TASK.createdAt,
            },
            201,
          ),
    );
    await waitFor(() => expect(taskAction("开始任务")).toBeEnabled());
  },
);

test.each(["edit", "dependency"] as const)(
  "committed %s with a detail refresh failure blocks status until explicit draft replacement",
  async (kind) => {
    const boundary = installStatusBoundary({ failure: "detail" });
    const user = userEvent.setup();
    renderProjects();
    await user.click(
      await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
    );
    await screen.findByLabelText("任务标题");
    if (kind === "edit") {
      await user.clear(screen.getByLabelText("任务标题"));
      await user.type(screen.getByLabelText("任务标题"), "真实编辑");
      await user.click(screen.getByRole("button", { name: "保存任务" }));
    } else {
      await user.selectOptions(
        screen.getByLabelText("添加前置任务"),
        TASK_PAGE_2.id,
      );
      await user.click(screen.getByRole("button", { name: "添加依赖" }));
    }
    await screen.findByText(/更新已提交，但刷新失败/);
    expect(
      taskAction("开始任务", kind === "edit" ? "真实编辑" : TASK.title),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存任务" })).toBeDisabled();
    expect(screen.getByLabelText("添加前置任务")).toBeDisabled();
    expect(boundary.writes).toHaveLength(1);
    boundary.clearFailure();
    await user.click(
      screen.getAllByRole("button", {
        name: "重新读取最新版本（替换草稿）",
      })[0]!,
    );
    await waitFor(() =>
      expect(
        taskAction("开始任务", kind === "edit" ? "真实编辑" : TASK.title),
      ).toBeEnabled(),
    );
    expect(boundary.writes).toHaveLength(1);
  },
);

test.each(["edit", "dependency"] as const)(
  "%s revision conflict blocks sibling and status writes until explicit reread",
  async (kind) => {
    const boundary = installStatusBoundary({
      conflict: true,
      conflictOn: kind,
    });
    const user = userEvent.setup();
    renderProjects();
    await user.click(
      await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
    );
    await user.clear(await screen.findByLabelText("任务标题"));
    await user.type(screen.getByLabelText("任务标题"), "冲突保留草稿");
    if (kind === "edit")
      await user.click(screen.getByRole("button", { name: "保存任务" }));
    else {
      await user.selectOptions(
        screen.getByLabelText("添加前置任务"),
        TASK_PAGE_2.id,
      );
      await user.click(screen.getByRole("button", { name: "添加依赖" }));
    }
    await screen.findByRole("alert");
    expect(taskAction("开始任务")).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存任务" })).toBeDisabled();
    expect(screen.getByLabelText("添加前置任务")).toBeDisabled();
    expect(screen.getByLabelText("任务标题")).toHaveValue("冲突保留草稿");
    await user.click(
      screen.getByRole("button", { name: "重新读取最新版本（替换草稿）" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("任务标题")).toHaveValue("服务器最新任务"),
    );
    expect(taskAction("开始任务", "服务器最新任务")).toBeEnabled();
    expect(boundary.writes).toHaveLength(1);
  },
);

function installDraftBoundary(
  initial: import("../../src/api/projects.ts").Task,
) {
  let current = { ...initial };
  const writes: Record<string, unknown>[] = [];
  let edges: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const fixture = structureFixture(input);
      if (fixture) return fixture;
      const request =
        input instanceof Request ? input : new Request(String(input), init);
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/projects")
        return jsonResponse({ items: [PROJECT], nextCursor: null });
      if (request.method === "GET") {
        if (path.endsWith("/assignees"))
          return jsonResponse({ items: [], nextCursor: null });
        if (path.endsWith("/dependencies"))
          return jsonResponse({ items: edges, nextCursor: null });
        if (path.endsWith("/tasks"))
          return jsonResponse({
            items: [current, TASK_PAGE_2],
            nextCursor: null,
          });
        return jsonResponse(current);
      }
      const body = (await request.json()) as Record<string, unknown>;
      writes.push(body);
      if (body.expectedRevision !== current.revision)
        return jsonResponse(
          {
            code: "revision_conflict",
            message: "请重新读取",
            traceId: "lineage",
          },
          409,
        );
      if (path.endsWith("/dependencies")) {
        current = { ...current, revision: current.revision + 1 };
        edges = [
          {
            id: "00000000-0000-4000-8000-000000009301",
            predecessorTaskId: TASK_PAGE_2.id,
            successorTaskId: TASK.id,
            createdAt: TASK.createdAt,
          },
        ];
        return jsonResponse(edges[0], 201);
      }
      const { expectedRevision: _revision, ...fields } = body;
      current = { ...current, ...fields, revision: current.revision + 1 };
      return jsonResponse(current);
    }),
  );
  return {
    writes,
    get current() {
      return current;
    },
    external(next: Partial<typeof current>) {
      current = { ...current, ...next };
    },
  };
}

test.each(["status", "dependency"] as const)(
  "inactive stale draft cannot be rebased by an owned %s write",
  async (kind) => {
    const server = {
      ...TASK,
      revision: 2,
      title: "外部标题",
      description: "外部描述",
    };
    const boundary = installDraftBoundary(server);
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    queryClient.setQueryData(
      taskKeys.detail(IDENTITY.organization.id, PROJECT.id, TASK.id),
      TASK,
    );
    const user = userEvent.setup();
    renderProjects(queryClient);
    await user.click(
      await screen.findByRole("button", { name: "查看任务：外部标题" }),
    );
    await screen.findByLabelText("任务标题");
    await waitFor(() =>
      expect(
        queryClient.getQueryData<import("../../src/api/projects.ts").Task>(
          taskKeys.detail(IDENTITY.organization.id, PROJECT.id, TASK.id),
        )?.revision,
      ).toBe(2),
    );
    await user.clear(screen.getByLabelText("任务标题"));
    await user.type(screen.getByLabelText("任务标题"), "保留的旧版本草稿");
    if (kind === "status") await user.click(taskAction("开始任务", "外部标题"));
    else {
      await user.selectOptions(
        screen.getByLabelText("添加前置任务"),
        TASK_PAGE_2.id,
      );
      await user.click(screen.getByRole("button", { name: "添加依赖" }));
    }
    await waitFor(() => expect(boundary.current.revision).toBe(3));
    await screen.findByText(/草稿.*旧版本/);
    expect(screen.getByRole("button", { name: "保存任务" })).toBeDisabled();
    expect(screen.getByLabelText("任务标题")).toHaveValue("保留的旧版本草稿");
    expect(boundary.current.title).toBe("外部标题");
    expect(boundary.current.description).toBe("外部描述");
    expect(boundary.writes).toHaveLength(1);
    await user.click(
      screen.getByRole("button", { name: "重新读取最新版本（替换草稿）" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("任务标题")).toHaveValue("外部标题"),
    );
    expect(screen.getByLabelText("任务描述")).toHaveValue("外部描述");
  },
);

test("intervening external revision breaks a repeated owned-write draft lineage", async () => {
  const boundary = installDraftBoundary(TASK);
  const user = userEvent.setup();
  const { queryClient } = renderProjects();
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  await user.clear(await screen.findByLabelText("任务标题"));
  await user.type(screen.getByLabelText("任务标题"), "本地未提交标题");
  await user.click(taskAction("开始任务"));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "保存任务" })).toBeEnabled(),
  );
  boundary.external({
    revision: 3,
    title: "外部第三版本",
    description: "第三版描述",
  });
  await queryClient.invalidateQueries({
    queryKey: taskKeys.list(IDENTITY.organization.id, PROJECT.id),
    exact: true,
  });
  await queryClient.invalidateQueries({
    queryKey: taskKeys.detail(IDENTITY.organization.id, PROJECT.id, TASK.id),
    exact: true,
  });
  await user.selectOptions(
    screen.getByLabelText("添加前置任务"),
    TASK_PAGE_2.id,
  );
  await user.click(screen.getByRole("button", { name: "添加依赖" }));
  await waitFor(() => expect(boundary.current.revision).toBe(4));
  await screen.findByText(/草稿.*旧版本/);
  expect(screen.getByRole("button", { name: "保存任务" })).toBeDisabled();
  expect(boundary.current.title).toBe("外部第三版本");
  expect(boundary.writes).toHaveLength(2);
});

test("title-only PATCH preserves untouched due seconds/fractions and empty optional strings", async () => {
  const initial = {
    ...TASK,
    dueAt: "2026-10-06T12:34:56.789Z",
    description: "",
    acceptanceCriteria: "",
  };
  const boundary = installDraftBoundary(initial);
  const user = userEvent.setup();
  renderProjects();
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  await user.clear(await screen.findByLabelText("任务标题"));
  await user.type(screen.getByLabelText("任务标题"), "只改标题");
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  await waitFor(() => expect(boundary.writes).toHaveLength(1));
  expect(boundary.writes[0]).toEqual({
    expectedRevision: 1,
    expectedProjectRevision: 1,
    title: "只改标题",
  });
  expect(boundary.current.dueAt).toBe(initial.dueAt);
  expect(boundary.current.description).toBe("");
  expect(boundary.current.acceptanceCriteria).toBe("");
});

test("an unchanged edit sends no revision-only PATCH", async () => {
  const boundary = installDraftBoundary(TASK);
  const user = userEvent.setup();
  renderProjects();
  await user.click(
    await screen.findByRole("button", { name: `查看任务：${TASK.title}` }),
  );
  await screen.findByLabelText("任务标题");
  await user.click(screen.getByRole("button", { name: "保存任务" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "没有需要保存的更改",
  );
  expect(boundary.writes).toHaveLength(0);
  expect(boundary.current.revision).toBe(1);
});

test.each(["owner","admin","member"] as const)("existing %s projects expose a general creation entry",async role=>{
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>structureFixture(input)??jsonResponse(new URL(input instanceof Request?input.url:String(input)).pathname==="/api/v1/projects"?{items:[PROJECT],nextCursor:null}:{items:[],nextCursor:null})));
  renderProjects(undefined,{...IDENTITY,membership:{...IDENTITY.membership,role}});
  expect(await screen.findByRole("button",{name:"创建项目"})).toBeEnabled();
});

test("existing-project creation loads later pages before selecting the exact newly created ID",async()=>{
  const createdProject={...PROJECT_B,id:"00000000-0000-4000-8000-000000004003",name:"新增项目"};let posts=0;const cursors:(string|null)[]=[];
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const request=input instanceof Request?input:new Request(input);const url=new URL(request.url);
    if(url.pathname==="/api/v1/projects"){
      if(request.method==="POST"){posts++;return jsonResponse(createdProject,201);}
      const cursor=url.searchParams.get("cursor");cursors.push(cursor);
      return jsonResponse(cursor==="second"?{items:[PROJECT_B],nextCursor:"third"}:cursor==="third"?{items:[createdProject],nextCursor:null}:{items:[PROJECT],nextCursor:"second"});
    }
    return structureFixture(input)??jsonResponse({items:[],nextCursor:null});
  }));
  const user=userEvent.setup();renderProjects();await user.click(await screen.findByRole("button",{name:"创建项目"}));await user.type(screen.getByRole("textbox",{name:"项目名称"}),createdProject.name);await user.click(screen.getByRole("button",{name:"创建项目"}));
  expect(await screen.findByRole("heading",{name:createdProject.name})).toBeVisible();expect(cursors).toEqual([null,null,"second","third"]);expect(posts).toBe(1);expect(screen.queryByRole("form",{name:"创建项目"})).not.toBeInTheDocument();
});

test("cancelling general creation keeps the selected task workspace and its unsaved input mounted",async()=>{
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const request=input instanceof Request?input:new Request(input);const path=new URL(request.url).pathname;const fixture=structureFixture(input);if(fixture)return fixture;
    if(path==="/api/v1/projects")return jsonResponse({items:[PROJECT,PROJECT_B],nextCursor:null});
    if(path===`/api/v1/tasks/${TASK.id}`)return jsonResponse(TASK);
    if(path===`/api/v1/projects/${PROJECT.id}/tasks`)return jsonResponse({items:[TASK],nextCursor:null});
    return jsonResponse({items:[],nextCursor:null});
  }));
  const user=userEvent.setup();renderProjects();await user.click(await screen.findByRole("button",{name:`查看任务：${TASK.title}`}));const editor=await screen.findByRole("form",{name:"编辑任务"});await user.clear(within(editor).getByLabelText("任务标题"));await user.type(within(editor).getByLabelText("任务标题"),"保留未保存的任务输入");
  await user.click(screen.getByRole("button",{name:"创建项目"}));expect(screen.getByRole("form",{name:"编辑任务"})).toBe(editor);await user.type(screen.getByRole("textbox",{name:"项目名称"}),"尚未创建");await user.click(screen.getByRole("button",{name:"取消"}));
  expect(screen.getByRole("form",{name:"编辑任务"})).toBe(editor);expect(within(editor).getByLabelText("任务标题")).toHaveValue("保留未保存的任务输入");expect(screen.getByRole("heading",{name:PROJECT.name})).toBeVisible();
});

test("known general creation success with refresh failure can only reread and never post twice",async()=>{
  let posts=0,created=false,fail=true;vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const request=input instanceof Request?input:new Request(input);const url=new URL(request.url);
    if(url.pathname==="/api/v1/projects"){
      if(request.method==="POST"){posts++;created=true;return jsonResponse(PROJECT_B,201);}
      if(created&&fail)return jsonResponse({code:"database_unavailable",message:"列表读取失败",traceId:"general-refresh"},503);
      return jsonResponse({items:created?[PROJECT,PROJECT_B]:[PROJECT],nextCursor:null});
    }return structureFixture(input)??jsonResponse({items:[],nextCursor:null});
  }));const user=userEvent.setup();renderProjects();await user.click(await screen.findByRole("button",{name:"创建项目"}));await user.type(screen.getByRole("textbox",{name:"项目名称"}),PROJECT_B.name);await user.click(screen.getByRole("button",{name:"创建项目"}));expect(await screen.findByRole("alert")).toHaveTextContent("项目已创建");expect(screen.getByRole("textbox",{name:"项目名称"})).toHaveValue(PROJECT_B.name);expect(screen.queryByRole("button",{name:"创建项目"})).not.toBeInTheDocument();fail=false;await user.click(screen.getByRole("button",{name:"重新读取项目"}));expect(await screen.findByRole("heading",{name:PROJECT_B.name})).toBeVisible();expect(posts).toBe(1);
});

test("unknown general creation inspects all pages while preserving the locked submission until explicit close",async()=>{
  let posts=0;const cursors:(string|null)[]=[];vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    const request=input instanceof Request?input:new Request(input);const url=new URL(request.url);
    if(url.pathname==="/api/v1/projects"){
      if(request.method==="POST"){posts++;throw new TypeError("lost acknowledgement");}
      const cursor=url.searchParams.get("cursor");cursors.push(cursor);return jsonResponse(cursor==="later"?{items:[PROJECT_B],nextCursor:null}:{items:[PROJECT],nextCursor:"later"});
    }return structureFixture(input)??jsonResponse({items:[],nextCursor:null});
  }));const user=userEvent.setup();renderProjects();await user.click(await screen.findByRole("button",{name:"创建项目"}));await user.type(screen.getByRole("textbox",{name:"项目名称"}),PROJECT_B.name);await user.click(screen.getByRole("button",{name:"创建项目"}));expect(await screen.findByRole("alert")).toHaveTextContent("未收到创建确认");await user.click(screen.getByRole("button",{name:"核对项目列表"}));expect(await screen.findByText(/已读取全部可访问项目/)).toBeVisible();expect(within(screen.getByRole("list",{name:"已读取的完整项目列表"})).getByText(PROJECT_B.name)).toBeVisible();expect(cursors).toEqual([null,null,"later"]);expect(screen.getByRole("textbox",{name:"项目名称"})).toHaveValue(PROJECT_B.name);expect(screen.getByRole("textbox",{name:"项目名称"})).toBeDisabled();expect(screen.queryByRole("button",{name:"创建项目"})).not.toBeInTheDocument();expect(screen.getByRole("heading",{name:PROJECT.name})).toBeVisible();await user.click(screen.getByRole("button",{name:"关闭并查看项目列表"}));expect(screen.queryByRole("textbox",{name:"项目名称"})).not.toBeInTheDocument();expect(posts).toBe(1);
});

test("viewer with existing projects has no general creation entry",async()=>{
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>structureFixture(input)??jsonResponse(new URL(input instanceof Request?input.url:String(input)).pathname==="/api/v1/projects"?{items:[PROJECT],nextCursor:null}:{items:[],nextCursor:null})));
  renderProjects(undefined,{...IDENTITY,membership:{...IDENTITY.membership,role:"viewer"}});await screen.findByRole("heading",{name:PROJECT.name});expect(screen.queryByRole("button",{name:"创建项目"})).not.toBeInTheDocument();
});
