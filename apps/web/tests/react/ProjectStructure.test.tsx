import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectsPage } from "../../src/pages/ProjectsPage.tsx";
import { TaskEditor } from "../../src/components/projects/TaskEditor.tsx";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { SessionProvider, useSession } from "../../src/session/SessionContext.tsx";
import { LoginForm } from "../../src/components/LoginForm.tsx";
const org = "00000000-0000-4000-8000-000000002001";
const project = {
  id: "00000000-0000-4000-8000-000000004001",
  name: "Structure project",
  description: "Project goal",
  revision: 1,
  createdAt: "2026-10-08T00:00:00Z",
  updatedAt: "2026-10-08T00:00:00Z"
};
const stage = {
  archived: false,
  id: "00000000-0000-4000-8000-000000006001",
  projectId: project.id,
  name: "Design",
  position: 0,
  revision: 1,
  createdAt: project.createdAt,
  updatedAt: project.updatedAt
};
const milestone = {
  archived: false,
  id: "00000000-0000-4000-8000-000000007001",
  projectId: project.id,
  name: "Review",
  stageId: stage.id,
  revision: 1,
  description: null,
  acceptanceCriteria: null,
  dueAt: null,
  createdAt: project.createdAt,
  updatedAt: project.updatedAt
};
const identity = {
  user: {
    id: "00000000-0000-4000-8000-000000001001",
    email: "demo@cairn.dev",
    displayName: "Demo"
  },
  organization: {
    id: org,
    name: "Demo",
    slug: "demo"
  },
  membership: {
    id: "00000000-0000-4000-8000-000000003001",
    role: "owner" as const
  },
  csrfToken: "csrf"
};
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: {
    "Content-Type": "application/json"
  }
});
afterEach(() => vi.unstubAllGlobals());
function setup(handler: (request: Request) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => handler(input instanceof Request ? input : new Request(input, init))));
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false
      },
      mutations: {
        retry: false
      }
    }
  });
  return client;
}
function page(client: QueryClient) {
  return render(<QueryClientProvider client={client}><MemoryRouter><SessionProvider restoredIdentity={identity} sessionApi={{
        restore: async () => identity,
        logout: async () => undefined
      }}><ProjectsPage /></SessionProvider></MemoryRouter></QueryClientProvider>);
}
test.each([false, true])("task create409 retains grouping and protects siblings; explicit reread recovers (failed first read=%s)", async failFirstRead => {
  let version = 1;
  let failRead = false;
  let projectReads = 0;
  const writes: Record<string, unknown>[] = [];
  const sibling = {
    id: "00000000-0000-4000-8000-000000005002",
    projectId: project.id,
    revision: 1,
    parentTaskId: null,
    status: "todo",
    description: null,
    assigneeUserId: null,
    priority: "medium",
    title: "Sibling",
    stageId: null,
    milestoneId: null,
    dueAt: null,
    acceptanceCriteria: null,
    createdAt: project.createdAt,
    updatedAt: project.updatedAt
  };
  let created: typeof sibling | null = null;
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [project],
      nextCursor: null
    });
    if (request.method === "POST" && path.endsWith("/tasks")) {
      const body = await request.json();
      writes.push(body);
      if (writes.length === 1) {
        version = 2;
        failRead = failFirstRead;
        return response({
          code: "revision_conflict",
          message: "Project changed",
          traceId: "create-conflict"
        }, 409);
      }
      version = 3;
      created = {
        ...sibling,
        ...body,
        id: "00000000-0000-4000-8000-000000005003",
        status: "backlog"
      };
      return response(created, 201);
    }
    if (path.endsWith("/stages")) return response({
      items: [stage],
      nextCursor: null
    });
    if (path.endsWith("/milestones")) return response({
      items: [milestone],
      nextCursor: null
    });
    if (path.endsWith("/tasks")) return response({
      items: created ? [sibling, created] : [sibling],
      nextCursor: null
    });
    if (path.endsWith("/assignees")) return response({
      items: [],
      nextCursor: null
    });
    projectReads++;
    return failRead ? response({
      code: "database_unavailable",
      message: "Refresh unavailable",
      traceId: "refresh"
    }, 503) : response({
      ...project,
      revision: version
    });
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "创建任务"
  }));
  await userEvent.type(screen.getByLabelText("任务标题"), "Retained title");
  await userEvent.selectOptions(screen.getByLabelText("所属阶段"), stage.id);
  await userEvent.selectOptions(screen.getByLabelText("所属里程碑"), milestone.id);
  await userEvent.click(screen.getByRole("button", {
    name: "保存任务"
  }));
  await screen.findByText("Project changed");
  expect(screen.getByLabelText("任务标题")).toHaveValue("Retained title");
  expect(screen.getByLabelText("所属阶段")).toHaveValue(stage.id);
  expect(screen.getByLabelText("所属里程碑")).toHaveValue(milestone.id);
  expect(screen.getByRole("button", {
    name: "保存任务"
  })).toBeDisabled();
  expect(screen.getByRole("button", {
    name: "创建阶段"
  })).toBeDisabled();
  expect(screen.getByRole("button", {
    name: "创建里程碑"
  })).toBeDisabled();
  expect(screen.getByRole("button", {
    name: "开始任务"
  })).toBeDisabled();
  const beforeReads = projectReads;
  await userEvent.click(screen.getByRole("button", {
    name: "重新读取最新版本（替换草稿）"
  }));
  if (failFirstRead) {
    await screen.findByText("Refresh unavailable");
    expect(screen.getByLabelText("任务标题")).toHaveValue("Retained title");
    expect(screen.getByLabelText("所属阶段")).toHaveValue(stage.id);
    expect(screen.getByLabelText("所属里程碑")).toHaveValue(milestone.id);
    expect(screen.getByRole("button", {
      name: "保存任务"
    })).toBeDisabled();
    expect(writes).toHaveLength(1);
    failRead = false;
    await userEvent.click(screen.getByRole("button", {
      name: "重新读取最新版本（替换草稿）"
    }));
  }
  await waitFor(() => expect(screen.getByLabelText("任务标题")).toHaveValue(""));
  expect(projectReads).toBeGreaterThan(beforeReads);
  expect(screen.getByLabelText("所属阶段")).toHaveValue("");
  expect(screen.getByLabelText("所属里程碑")).toHaveValue("");
  await userEvent.type(screen.getByLabelText("任务标题"), "Fresh title");
  await userEvent.selectOptions(screen.getByLabelText("所属阶段"), stage.id);
  await userEvent.selectOptions(screen.getByLabelText("所属里程碑"), milestone.id);
  await userEvent.click(screen.getByRole("button", {
    name: "保存任务"
  }));
  await waitFor(() => expect(screen.queryByLabelText("任务标题")).not.toBeInTheDocument());
  expect(writes).toHaveLength(2);
  expect(writes[0]).toMatchObject({
    title: "Retained title",
    stageId: stage.id,
    milestoneId: milestone.id,
    expectedProjectRevision: 1
  });
  expect(writes[1]).toMatchObject({
    title: "Fresh title",
    stageId: stage.id,
    milestoneId: milestone.id,
    expectedProjectRevision: 2
  });
});
test.each(["stage create", "stage edit", "milestone create", "milestone edit", "task grouping", "stage archive", "milestone restore"])("current %s 401 expires the session, removes protected state and routes to real login", async operation => {
  const task = {
    id: "00000000-0000-4000-8000-000000005001",
    projectId: project.id,
    revision: 1,
    parentTaskId: null,
    status: "todo",
    description: "Keep",
    assigneeUserId: null,
    priority: "medium",
    title: "Evidence",
    stageId: stage.id,
    milestoneId: milestone.id,
    dueAt: null,
    acceptanceCriteria: null,
    createdAt: project.createdAt,
    updatedAt: project.updatedAt
  };
  const observed: {
    signal: AbortSignal | null;
  } = {
    signal: null
  };
  let writes = 0;
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (request.method === "POST" || request.method === "PATCH") {
      writes++;
      return response({
        code: "session_invalid",
        message: "Expired",
        traceId: "current"
      }, 401);
    }
    if (path.endsWith("/projects")) return response({
      items: [project],
      nextCursor: null
    });
    if (path.endsWith("/stages")) return response({
      items: [stage],
      nextCursor: null
    });
    if (path.endsWith("/milestones")) return response({
      items: [{...milestone, archived: operation === "milestone restore"}],
      nextCursor: null
    });
    if (path.endsWith("/tasks")) return response({
      items: [task],
      nextCursor: null
    });
    if (path.endsWith("/assignees") || path.endsWith("/dependencies")) return response({
      items: [],
      nextCursor: null
    });
    if (path.includes("/tasks/")) return response(task);
    return response(project);
  });
  client.setQueryData(["protected-secret"], "private draft");
  function Probe() {
    const {
      status,
      session
    } = useSession();
    const location = useLocation();
    if (session) observed.signal = session.signal;
    return <><output data-testid="expiry-status">{status}</output><output data-testid="expiry-path">{location.pathname}</output></>;
  }
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects"]}><SessionProvider restoredIdentity={identity} sessionApi={{
        restore: async () => identity,
        logout: async () => undefined
      }}><Probe /><Routes><Route path="/projects" element={<ProjectsPage />} /><Route path="/login" element={<LoginForm onSuccess={() => undefined} />} /></Routes></SessionProvider></MemoryRouter></QueryClientProvider>);
  if (operation === "stage archive") {
    await userEvent.click(await screen.findByRole("button", {name: "归档阶段：Design"}));
    await userEvent.click(screen.getByRole("button", {name: "确认归档"}));
  } else if (operation === "milestone restore") {
    await userEvent.click(await screen.findByLabelText("显示归档项"));
    await userEvent.click(await screen.findByRole("button", {name: "恢复里程碑：Review"}));
  } else if (operation === "task grouping") {
    await userEvent.click(await screen.findByRole("button", {
      name: "查看任务：Evidence"
    }));
    await userEvent.selectOptions(await screen.findByLabelText("所属里程碑"), "");
    await userEvent.selectOptions(screen.getByLabelText("所属阶段"), "");
    await userEvent.click(screen.getByRole("button", {
      name: "保存任务"
    }));
  } else if (operation.startsWith("stage")) {
    await userEvent.click(await screen.findByRole("button", {
      name: operation.endsWith("create") ? "创建阶段" : "编辑阶段：Design"
    }));
    await userEvent.clear(screen.getByLabelText("阶段名称"));
    await userEvent.type(screen.getByLabelText("阶段名称"), "Private draft");
    await userEvent.click(screen.getByRole("button", {
      name: "保存阶段"
    }));
  } else {
    await userEvent.click(await screen.findByRole("button", {
      name: operation.endsWith("create") ? "创建里程碑" : "编辑里程碑：Review"
    }));
    await userEvent.clear(screen.getByLabelText("里程碑名称"));
    await userEvent.type(screen.getByLabelText("里程碑名称"), "Private draft");
    await userEvent.click(screen.getByRole("button", {
      name: "保存里程碑"
    }));
  }
  await waitFor(() => expect(screen.getByTestId("expiry-status")).toHaveTextContent("anonymous"));
  await waitFor(() => expect(screen.getByTestId("expiry-path")).toHaveTextContent("/login"));
  expect(observed.signal?.aborted).toBe(true);
  expect(screen.getByTestId("expiry-path")).toHaveTextContent("/login");
  expect(screen.queryByRole("region", {
    name: "项目工作区"
  })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("阶段名称")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("里程碑名称")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("任务标题")).not.toBeInTheDocument();
  expect(client.getQueryCache().getAll()).toHaveLength(0);
  expect(client.getMutationCache().getAll()).toHaveLength(0);
  expect(screen.getByRole("button", {
    name: "登录"
  })).toBeEnabled();
  expect(writes).toBe(1);
});
test("stage create sends displayed project revision; conflict keeps input until explicit reread", async () => {
  const bodies: unknown[] = [];
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [project],
      nextCursor: null
    });
    if (path.endsWith("/stages") && request.method === "POST") {
      bodies.push(await request.json());
      return response({
        code: "revision_conflict",
        message: "Changed",
        traceId: "r"
      }, 409);
    }
    if (path.endsWith("/stages") || path.endsWith("/milestones") || path.endsWith("/tasks")) return response({
      items: [],
      nextCursor: null
    });
    return response(project);
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "创建阶段"
  }));
  await userEvent.type(screen.getByLabelText("阶段名称"), "Design");
  await userEvent.click(screen.getByRole("button", {
    name: "保存阶段"
  }));
  await screen.findByText("Changed");
  expect(bodies).toEqual([{
    name: "Design",
    position: 0,
    expectedProjectRevision: 1
  }]);
  expect(screen.getByLabelText("阶段名称")).toHaveValue("Design");
  expect(screen.getByRole("button", {
    name: "保存阶段"
  })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", {
    name: "重新读取项目结构（替换草稿）"
  }));
  await waitFor(() => expect(screen.queryByLabelText("阶段名称")).not.toBeInTheDocument());
});
test("task grouping sends both IDs and project revision without erasing a title draft", async () => {
  const bodies: unknown[] = [];
  const controller = new AbortController();
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/stages")) return response({
      items: [stage],
      nextCursor: null
    });
    if (path.endsWith("/milestones")) return response({
      items: [milestone],
      nextCursor: null
    });
    if (path.endsWith("/assignees")) return response({
      items: [],
      nextCursor: null
    });
    if (path.endsWith("/tasks") && request.method === "POST") {
      const body = await request.json();
      bodies.push(body);
      return response({
        id: "00000000-0000-4000-8000-000000005001",
        projectId: project.id,
        revision: 1,
        parentTaskId: null,
        status: "backlog",
        createdAt: project.createdAt,
        updatedAt: project.updatedAt,
        ...body
      }, 201);
    }
    return response(project);
  });
  render(<QueryClientProvider client={client}><TaskEditor organizationId={org} projectId={project.id} csrfToken="csrf" signal={controller.signal} onSaved={async () => true} /></QueryClientProvider>);
  await userEvent.type(screen.getByLabelText("任务标题"), "Keep draft");
  await screen.findByRole("option", {
    name: "Review"
  });
  await userEvent.selectOptions(screen.getByLabelText("所属阶段"), stage.id);
  await userEvent.selectOptions(screen.getByLabelText("所属里程碑"), milestone.id);
  expect(screen.getByLabelText("任务标题")).toHaveValue("Keep draft");
  await userEvent.click(screen.getByRole("button", {
    name: "保存任务"
  }));
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0]).toMatchObject({
    title: "Keep draft",
    stageId: stage.id,
    milestoneId: milestone.id,
    expectedProjectRevision: 1
  });
});
test("a structure conflict stays blocked after cancelling its form until explicit reread", async () => {
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [project],
      nextCursor: null
    });
    if (request.method === "POST") return response({
      code: "revision_conflict",
      message: "Changed",
      traceId: "r"
    }, 409);
    if (path.endsWith("/stages") || path.endsWith("/milestones") || path.endsWith("/tasks")) return response({
      items: [],
      nextCursor: null
    });
    return response(project);
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "创建阶段"
  }));
  await userEvent.type(screen.getByLabelText("阶段名称"), "Design");
  await userEvent.click(screen.getByRole("button", {
    name: "保存阶段"
  }));
  await screen.findByText("Changed");
  await userEvent.click(screen.getByRole("button", {
    name: "取消编辑"
  }));
  expect(screen.getByRole("button", {
    name: "创建阶段"
  })).toBeDisabled();
  expect(screen.getByRole("button", {
    name: "创建任务"
  })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", {
    name: "重新读取项目结构（替换草稿）"
  }));
  await waitFor(() => expect(screen.getByRole("button", {
    name: "创建阶段"
  })).toBeEnabled());
});
test("milestone name-only edit preserves untouched empty strings and due precision", async () => {
  const bodies: unknown[] = [];
  const initial = {
    ...milestone,
    description: "",
    acceptanceCriteria: "",
    dueAt: "2026-10-09T01:02:03.123456+08:00"
  };
  let stored = initial;
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [project],
      nextCursor: null
    });
    if (request.method === "PATCH") {
      const body = await request.json();
      bodies.push(body);
      stored = {
        ...stored,
        name: body.name,
        revision: 2
      };
      return response(stored);
    }
    if (path.endsWith("/stages")) return response({
      items: [stage],
      nextCursor: null
    });
    if (path.endsWith("/milestones")) return response({
      items: [stored],
      nextCursor: null
    });
    if (path.endsWith("/tasks")) return response({
      items: [],
      nextCursor: null
    });
    return response({
      ...project,
      revision: bodies.length ? 2 : 1
    });
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "编辑里程碑：Review"
  }));
  await userEvent.clear(screen.getByLabelText("里程碑名称"));
  await userEvent.type(screen.getByLabelText("里程碑名称"), "Ready");
  await userEvent.click(screen.getByRole("button", {
    name: "保存里程碑"
  }));
  await screen.findByText("项目结构已保存。");
  expect(bodies).toEqual([{
    name: "Ready",
    expectedRevision: 1,
    expectedProjectRevision: 1
  }]);
});
test("committed structure create with failed refresh blocks duplicate and other writes until reread", async () => {
  let writes = 0;
  let fail = false;
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [project],
      nextCursor: null
    });
    if (request.method === "POST") {
      writes++;
      fail = true;
      return response(stage, 201);
    }
    if (fail && path.endsWith("/stages")) return response({
      code: "database_unavailable",
      message: "Offline",
      traceId: "r"
    }, 503);
    if (path.endsWith("/stages")) return response({
      items: writes ? [stage] : [],
      nextCursor: null
    });
    if (path.endsWith("/milestones") || path.endsWith("/tasks")) return response({
      items: [],
      nextCursor: null
    });
    return response({
      ...project,
      revision: writes ? 2 : 1
    });
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "创建阶段"
  }));
  await userEvent.type(screen.getByLabelText("阶段名称"), "Design");
  await userEvent.click(screen.getByRole("button", {
    name: "保存阶段"
  }));
  await screen.findByText("项目结构已保存，但刷新失败。请重新读取后再操作。");
  expect(screen.getByRole("button", {
    name: "保存阶段"
  })).toBeDisabled();
  expect(screen.getByRole("button", {
    name: "创建任务"
  })).toBeDisabled();
  expect(writes).toBe(1);
  fail = false;
  await userEvent.click(screen.getByRole("button", {
    name: "重新读取项目结构（替换草稿）"
  }));
  await waitFor(() => expect(screen.queryByLabelText("阶段名称")).not.toBeInTheDocument());
  expect(writes).toBe(1);
});
test("committed task creation treats a missing refreshed project revision as refresh failure", async () => {
  let writes = 0;
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [project],
      nextCursor: null
    });
    if (request.method === "POST") {
      writes++;
      const body = await request.json();
      return response({
        ...body,
        id: "00000000-0000-4000-8000-000000005001",
        projectId: project.id,
        revision: 1,
        parentTaskId: null,
        status: "backlog",
        createdAt: project.createdAt,
        updatedAt: project.updatedAt
      }, 201);
    }
    if (path.endsWith("/stages") || path.endsWith("/milestones") || path.endsWith("/tasks") || path.endsWith("/assignees")) return response({
      items: [],
      nextCursor: null
    });
    return response({
      ...project,
      revision: writes ? null : 1
    });
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "创建任务"
  }));
  await userEvent.type(screen.getByLabelText("任务标题"), "Confirmed create");
  await userEvent.click(screen.getByRole("button", {
    name: "保存任务"
  }));
  await screen.findByText("任务已保存，但刷新失败。请重新读取后再操作。");
  expect(screen.getByRole("button", {
    name: "保存任务"
  })).toBeDisabled();
  expect(screen.getByRole("button", {
    name: "创建阶段"
  })).toBeDisabled();
  expect(screen.getByRole("button", {
    name: "创建里程碑"
  })).toBeDisabled();
  expect(screen.getByRole("button", {
    name: "重试刷新任务"
  })).toBeEnabled();
  expect(writes).toBe(1);
});
test("structure lists and grouping selectors load subsequent pages without replacing a title draft", async () => {
  const secondStage = {
    ...stage,
    id: "00000000-0000-4000-8000-000000006002",
    name: "Delivery",
    position: 1
  };
  const secondMilestone = {
    ...milestone,
    id: "00000000-0000-4000-8000-000000007002",
    name: "Release",
    stageId: secondStage.id
  };
  const cursors: string[] = [];
  const client = setup(async request => {
    const url = new URL(request.url);
    const path = url.pathname;
    const cursor = url.searchParams.get("cursor");
    if (cursor) cursors.push(cursor);
    if (path.endsWith("/stages")) return response({
      items: [cursor ? secondStage : stage],
      nextCursor: cursor ? null : "next-stage"
    });
    if (path.endsWith("/milestones")) return response({
      items: [cursor ? secondMilestone : milestone],
      nextCursor: cursor ? null : "next-milestone"
    });
    if (path.endsWith("/assignees")) return response({
      items: [],
      nextCursor: null
    });
    return response(project);
  });
  render(<QueryClientProvider client={client}><TaskEditor organizationId={org} projectId={project.id} csrfToken="csrf" signal={new AbortController().signal} onSaved={async () => true} /></QueryClientProvider>);
  await userEvent.type(screen.getByLabelText("任务标题"), "Keep pagination draft");
  await userEvent.click(await screen.findByRole("button", {
    name: "加载更多阶段选项"
  }));
  await userEvent.click(await screen.findByRole("button", {
    name: "加载更多里程碑选项"
  }));
  await screen.findByRole("option", {
    name: "Release"
  });
  await userEvent.selectOptions(screen.getByLabelText("所属阶段"), secondStage.id);
  await userEvent.selectOptions(screen.getByLabelText("所属里程碑"), secondMilestone.id);
  expect(screen.getByLabelText("任务标题")).toHaveValue("Keep pagination draft");
  expect(cursors).toEqual(["next-stage", "next-milestone"]);
});
test.each([201, 401])("switching project cancels a pending structure write and ignores late HTTP %s", async lateStatus => {
  const secondProject = {
    ...project,
    id: "00000000-0000-4000-8000-000000004002",
    name: "Second scope"
  };
  let release!: (response: Response) => void;
  let pendingSignal: AbortSignal | undefined;
  const pending = new Promise<Response>(resolve => {
    release = resolve;
  });
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [project, secondProject],
      nextCursor: null
    });
    if (request.method === "POST") {
      pendingSignal = request.signal;
      return pending;
    }
    if (path.endsWith("/stages") || path.endsWith("/milestones") || path.endsWith("/tasks")) return response({
      items: [],
      nextCursor: null
    });
    return response(path.includes(secondProject.id) ? secondProject : project);
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "创建阶段"
  }));
  await userEvent.type(screen.getByLabelText("阶段名称"), "Old scope draft");
  await userEvent.click(screen.getByRole("button", {
    name: "保存阶段"
  }));
  await waitFor(() => expect(pendingSignal).toBeDefined());
  await userEvent.selectOptions(screen.getByLabelText("切换项目"), secondProject.id);
  await screen.findByRole("heading", {
    name: "Second scope"
  });
  expect(pendingSignal!.aborted).toBe(true);
  release(lateStatus === 201 ? response(stage, 201) : response({
    code: "session_invalid",
    message: "Expired",
    traceId: "late"
  }, 401));
  await new Promise(resolve => setTimeout(resolve, 20));
  expect(screen.getByRole("heading", {
    name: "Second scope"
  })).toBeInTheDocument();
  expect(screen.queryByLabelText("阶段名称")).not.toBeInTheDocument();
  expect(screen.queryByText("项目结构已保存。")).not.toBeInTheDocument();
});
test("milestone create and stage edit submit their real fields with refreshed project revision", async () => {
  const writes: unknown[] = [];
  let version = 1;
  let storedStage = stage;
  let storedMilestone: typeof milestone | null = null;
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [project],
      nextCursor: null
    });
    if (request.method === "POST") {
      const body = await request.json();
      writes.push(body);
      storedMilestone = {
        ...milestone,
        ...body
      };
      version++;
      return response(storedMilestone, 201);
    }
    if (request.method === "PATCH") {
      const body = await request.json();
      writes.push(body);
      storedStage = {
        ...storedStage,
        ...body,
        revision: 2
      };
      version++;
      return response(storedStage);
    }
    if (path.endsWith("/stages")) return response({
      items: [storedStage],
      nextCursor: null
    });
    if (path.endsWith("/milestones")) return response({
      items: storedMilestone ? [storedMilestone] : [],
      nextCursor: null
    });
    if (path.endsWith("/tasks")) return response({
      items: [],
      nextCursor: null
    });
    return response({
      ...project,
      revision: version
    });
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "创建里程碑"
  }));
  await userEvent.type(screen.getByLabelText("里程碑名称"), "Ready");
  await userEvent.type(screen.getByLabelText("里程碑说明"), "Scope");
  await userEvent.type(screen.getByLabelText("里程碑验收标准"), "Pass");
  await userEvent.selectOptions(screen.getByLabelText("里程碑所属阶段"), stage.id);
  await userEvent.click(screen.getByRole("button", {
    name: "保存里程碑"
  }));
  await screen.findByText("项目结构已保存。");
  await userEvent.click(screen.getByRole("button", {
    name: "编辑阶段：Design"
  }));
  await userEvent.clear(screen.getByLabelText("阶段名称"));
  await userEvent.type(screen.getByLabelText("阶段名称"), "Deliver");
  await userEvent.clear(screen.getByLabelText("排序位置"));
  await userEvent.type(screen.getByLabelText("排序位置"), "9");
  await userEvent.click(screen.getByRole("button", {
    name: "保存阶段"
  }));
  await screen.findByText("项目结构已保存。");
  expect(writes).toEqual([{
    name: "Ready",
    description: "Scope",
    acceptanceCriteria: "Pass",
    stageId: stage.id,
    dueAt: null,
    expectedProjectRevision: 1
  }, {
    name: "Deliver",
    position: 9,
    expectedRevision: 1,
    expectedProjectRevision: 2
  }]);
});
test("repeated task regroup, clear and regroup saves keep the current editor revision writable", async () => {
  const task = {
    id: "00000000-0000-4000-8000-000000005001",
    projectId: project.id,
    revision: 1,
    parentTaskId: null,
    status: "todo",
    description: null,
    assigneeUserId: null,
    priority: "medium",
    title: "Evidence",
    stageId: stage.id,
    milestoneId: milestone.id,
    dueAt: null,
    acceptanceCriteria: null,
    createdAt: project.createdAt,
    updatedAt: project.updatedAt
  };
  let stored = task;
  let projectRevision = 1;
  const bodies: unknown[] = [];
  const otherStage = {
    ...stage,
    id: "00000000-0000-4000-8000-000000006002",
    name: "Delivery",
    position: 1
  };
  const otherMilestone = {
    ...milestone,
    id: "00000000-0000-4000-8000-000000007002",
    name: "Release",
    stageId: otherStage.id
  };
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({
      items: [{
        ...project,
        revision: projectRevision
      }],
      nextCursor: null
    });
    if (request.method === "PATCH") {
      const body = await request.json();
      bodies.push(body);
      stored = {
        ...stored,
        ...body,
        revision: stored.revision + 1
      };
      projectRevision++;
      await new Promise(resolve => setTimeout(resolve, 10));
      return response(stored);
    }
    if (path.endsWith("/stages")) return response({
      items: [stage, otherStage],
      nextCursor: null
    });
    if (path.endsWith("/milestones")) return response({
      items: [milestone, otherMilestone],
      nextCursor: null
    });
    if (path.endsWith("/tasks")) return response({
      items: [stored],
      nextCursor: null
    });
    if (path.endsWith("/dependencies") || path.endsWith("/assignees")) return response({
      items: [],
      nextCursor: null
    });
    if (path.includes("/tasks/")) {
      await new Promise(resolve => setTimeout(resolve, 10));
      return response(stored);
    }
    return response({
      ...project,
      revision: projectRevision
    });
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {
    name: "查看任务：Evidence"
  }));
  await screen.findByLabelText("所属阶段");
  for (const [stageId, milestoneId] of [[otherStage.id, otherMilestone.id], ["", ""], [stage.id, milestone.id]]) {
    await waitFor(() => expect(screen.getByLabelText("所属阶段")).toBeEnabled());
    await userEvent.selectOptions(screen.getByLabelText("所属阶段"), stageId!);
    await userEvent.selectOptions(screen.getByLabelText("所属里程碑"), milestoneId!);
    await userEvent.click(screen.getByRole("button", {
      name: "保存任务"
    }));
    await waitFor(() => expect(screen.getByRole("button", {
      name: "保存任务"
    })).toBeEnabled());
  }
  expect(bodies).toEqual([{
    expectedRevision: 1,
    expectedProjectRevision: 1,
    stageId: otherStage.id,
    milestoneId: otherMilestone.id
  }, {
    expectedRevision: 2,
    expectedProjectRevision: 2,
    stageId: null,
    milestoneId: null
  }, {
    expectedRevision: 3,
    expectedProjectRevision: 3,
    stageId: stage.id,
    milestoneId: milestone.id
  }]);
  expect(screen.queryByText("草稿基于旧版本，请重新读取最新版本后再保存。")).not.toBeInTheDocument();
});

test("archive confirmation cancels, protects drafts, filters archived objects and restores", async () => {
  let stored = stage;
  let version = 1;
  const writes: unknown[] = [];
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (request.method === "PATCH") {
      const body = await request.json();
      writes.push(body);
      stored = {...stored, archived: body.archived, revision: stored.revision + 1};
      version++;
      return response(stored);
    }
    if (path.endsWith("/projects")) return response({items: [project], nextCursor: null});
    if (path.endsWith("/stages")) return response({items: [stored], nextCursor: null});
    if (path.endsWith("/tasks") || path.endsWith("/milestones")) return response({items: [], nextCursor: null});
    return response({...project, revision: version});
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {name: "编辑阶段：Design"}));
  await userEvent.type(screen.getByLabelText("阶段名称"), " draft");
  expect(screen.getByRole("button", {name: "归档阶段：Design"})).toBeDisabled();
  expect(screen.getByLabelText("阶段名称")).toHaveValue("Design draft");
  await userEvent.click(screen.getByRole("button", {name: "取消编辑"}));
  await userEvent.click(screen.getByRole("button", {name: "归档阶段：Design"}));
  expect(screen.getByText("确认归档阶段：Design？")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name: "取消归档"}));
  expect(writes).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", {name: "归档阶段：Design"}));
  await userEvent.click(screen.getByRole("button", {name: "确认归档"}));
  await screen.findByText("阶段已归档。");
  expect(screen.queryByRole("button", {name: "恢复阶段：Design"})).not.toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("显示归档项"));
  await userEvent.click(screen.getByRole("button", {name: "恢复阶段：Design"}));
  await screen.findByText("阶段已恢复。");
  expect(writes).toEqual([{archived: true, expectedRevision: 1, expectedProjectRevision: 1}, {archived: false, expectedRevision: 2, expectedProjectRevision: 2}]);
});

test.each(["stage", "milestone"])("%s lifecycle409 retains target through failed reread then uses fresh revisions", async kind => {
  let version = 1;
  let objectRevision = 1;
  let failRead = false;
  const writes: unknown[] = [];
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (request.method === "PATCH") {
      writes.push(await request.json());
      if (writes.length === 1) {
        version = 2;
        objectRevision = 2;
        failRead = true;
        return response({code: "structure_in_use", message: "请先解除任务关联", traceId: "occupied"}, 409);
      }
      return response({...kind === "stage" ? stage : milestone, archived: true, revision: 3});
    }
    if (path.endsWith("/projects")) return response({items: [project], nextCursor: null});
    if (failRead && path.endsWith("/stages")) return response({code: "database_unavailable", message: "Offline", traceId: "read"}, 503);
    if (path.endsWith("/stages")) return response({items: [{...stage, revision: objectRevision}], nextCursor: null});
    if (path.endsWith("/milestones")) return response({items: [{...milestone, revision: objectRevision}], nextCursor: null});
    if (path.endsWith("/tasks")) return response({items: [], nextCursor: null});
    return response({...project, revision: version});
  });
  page(client);
  const label = kind === "stage" ? "阶段：Design" : "里程碑：Review";
  await userEvent.click(await screen.findByRole("button", {name: `归档${label}`}));
  await userEvent.click(screen.getByRole("button", {name: "确认归档"}));
  await screen.findByText("请先解除任务关联");
  expect(screen.getByRole("button", {name: "确认归档"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button", {name: "重新读取项目结构"}));
  await screen.findByText("重新读取失败，请重试。");
  expect(screen.getByText(`确认归档${label}？`)).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "确认归档"})).toBeDisabled();
  expect(writes).toHaveLength(1);
  failRead = false;
  await userEvent.click(screen.getByRole("button", {name: "重新读取项目结构"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "确认归档"})).toBeEnabled());
  await userEvent.click(screen.getByRole("button", {name: "确认归档"}));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1]).toEqual({archived: true, expectedRevision: 2, expectedProjectRevision: 2});
});

test("committed lifecycle with failed refresh offers reread without repeating write", async () => {
  let failRead = false;
  let writes = 0;
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (request.method === "PATCH") {writes++; failRead = true; return response({...stage, archived: true, revision: 2});}
    if (path.endsWith("/projects")) return response({items: [project], nextCursor: null});
    if (path.endsWith("/stages")) return failRead ? response({code: "database_unavailable", message: "Offline", traceId: "r"}, 503) : response({items: [{...stage, archived: writes > 0, revision: writes + 1}], nextCursor: null});
    if (path.endsWith("/milestones") || path.endsWith("/tasks")) return response({items: [], nextCursor: null});
    return response({...project, revision: writes + 1});
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {name: "归档阶段：Design"}));
  await userEvent.click(screen.getByRole("button", {name: "确认归档"}));
  await screen.findByText("阶段已归档，但刷新失败。请重新读取后再操作。");
  expect(screen.queryByRole("button", {name: "确认归档"})).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "创建阶段"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button", {name: "重新读取项目结构"}));
  await screen.findByText("重新读取失败，请重试。");
  expect(writes).toBe(1);
  failRead = false;
  await userEvent.click(screen.getByRole("button", {name: "重新读取项目结构"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "创建阶段"})).toBeEnabled());
  expect(writes).toBe(1);
});

test("archived structure remains readable to viewers and absent from assignment selectors", async () => {
  const archivedStage = {...stage, archived: true};
  const archivedMilestone = {...milestone, archived: true};
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/projects")) return response({items: [project], nextCursor: null});
    if (path.endsWith("/stages")) return response({items: [archivedStage], nextCursor: null});
    if (path.endsWith("/milestones")) return response({items: [archivedMilestone], nextCursor: null});
    if (path.endsWith("/tasks") || path.endsWith("/assignees")) return response({items: [], nextCursor: null});
    return response(project);
  });
  const view = render(<QueryClientProvider client={client}><MemoryRouter><SessionProvider restoredIdentity={{...identity, membership: {...identity.membership, role: "viewer"}}} sessionApi={{restore: async () => identity, logout: async () => undefined}}><ProjectsPage /></SessionProvider></MemoryRouter></QueryClientProvider>);
  await screen.findByLabelText("显示归档项");
  await userEvent.click(screen.getByLabelText("显示归档项"));
  await screen.findByText("Design · 顺序 0 · 已归档");
  expect(screen.queryByRole("button", {name: "恢复阶段：Design"})).not.toBeInTheDocument();
  view.unmount();
  render(<QueryClientProvider client={client}><TaskEditor organizationId={org} projectId={project.id} csrfToken="csrf" signal={new AbortController().signal} onSaved={async () => true}/></QueryClientProvider>);
  await screen.findByLabelText("所属阶段");
  expect(screen.queryByRole("option", {name: "Design"})).not.toBeInTheDocument();
  expect(screen.queryByRole("option", {name: "Review"})).not.toBeInTheDocument();
});

test.each(["occupied", "parent archived"])("lifecycle %s rejection can cancel to perform corrective actions", async problem => {
  const task = {id: "00000000-0000-4000-8000-000000005001", projectId: project.id, revision: 1, title: "Associated", description: null, assigneeUserId: null, stageId: stage.id, milestoneId: milestone.id, parentTaskId: null, status: "todo", priority: "medium", dueAt: null, acceptanceCriteria: null, createdAt: project.createdAt, updatedAt: project.updatedAt};
  const archived = problem === "parent archived";
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (request.method === "PATCH") return response({code: archived ? "structure_archived" : "structure_in_use", message: "请先调整关联", traceId: "correction"}, 409);
    if (path.endsWith("/projects")) return response({items: [project], nextCursor: null});
    if (path.endsWith("/stages")) return response({items: [{...stage, archived}], nextCursor: null});
    if (path.endsWith("/milestones")) return response({items: [{...milestone, archived}], nextCursor: null});
    if (path.endsWith("/tasks")) return response({items: archived ? [] : [task], nextCursor: null});
    if (path.endsWith("/assignees") || path.endsWith("/dependencies")) return response({items: [], nextCursor: null});
    if (path.includes("/tasks/")) return response(task);
    return response(project);
  });
  page(client);
  if (archived) {
    await userEvent.click(await screen.findByLabelText("显示归档项"));
    await userEvent.click(await screen.findByRole("button", {name: "恢复里程碑：Review"}));
  } else {
    await userEvent.click(await screen.findByRole("button", {name: "归档里程碑：Review"}));
    await userEvent.click(screen.getByRole("button", {name: "确认归档"}));
  }
  await screen.findByText("请先调整关联");
  await userEvent.click(screen.getByRole("button", {name: archived ? "取消恢复" : "取消归档"}));
  if (archived) expect(screen.getByRole("button", {name: "恢复阶段：Design"})).toBeEnabled();
  else {
    expect(screen.getByRole("button", {name: "查看任务：Associated"})).toBeEnabled();
    await userEvent.click(screen.getByRole("button", {name: "查看任务：Associated"}));
    await screen.findByLabelText("所属里程碑");
  }
});

test.each([200, 401])("project switch aborts lifecycle write and ignores late HTTP %s", async lateStatus => {
  const second = {...project, id: "00000000-0000-4000-8000-000000004002", name: "Second lifecycle scope"};
  let release!: (value: Response) => void;
  let requestSignal: AbortSignal | undefined;
  const pending = new Promise<Response>(resolve => {release = resolve;});
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (request.method === "PATCH") {requestSignal = request.signal; return pending;}
    if (path.endsWith("/projects")) return response({items: [project, second], nextCursor: null});
    if (path.endsWith("/stages")) return response({items: path.includes(second.id) ? [] : [stage], nextCursor: null});
    if (path.endsWith("/milestones") || path.endsWith("/tasks")) return response({items: [], nextCursor: null});
    return response(path.includes(second.id) ? second : project);
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {name: "归档阶段：Design"}));
  await userEvent.click(screen.getByRole("button", {name: "确认归档"}));
  await waitFor(() => expect(requestSignal).toBeDefined());
  expect(screen.getByRole("button", {name: "正在归档"})).toBeDisabled();
  await userEvent.selectOptions(screen.getByLabelText("切换项目"), second.id);
  await screen.findByRole("heading", {name: second.name});
  expect(requestSignal!.aborted).toBe(true);
  release(lateStatus === 200 ? response({...stage, archived: true, revision: 2}) : response({code: "session_invalid", message: "Expired", traceId: "late"}, 401));
  await new Promise(resolve => setTimeout(resolve, 20));
  expect(screen.getByRole("heading", {name: second.name})).toBeInTheDocument();
  expect(screen.queryByRole("group", {name: "归档确认"})).not.toBeInTheDocument();
  expect(screen.queryByText("阶段已归档。")).not.toBeInTheDocument();
});

test("a draft retains ordinary text when a selected grouping is newly archived", async () => {
  let archived = false;
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/stages")) return response({items: [{...stage, archived}], nextCursor: null});
    if (path.endsWith("/milestones")) return response({items: [{...milestone, archived}], nextCursor: null});
    if (path.endsWith("/assignees")) return response({items: [], nextCursor: null});
    return response(project);
  });
  render(<QueryClientProvider client={client}><TaskEditor organizationId={org} projectId={project.id} csrfToken="csrf" signal={new AbortController().signal} onSaved={async () => true}/></QueryClientProvider>);
  await userEvent.type(screen.getByLabelText("任务标题"), "Keep draft");
  await userEvent.selectOptions(await screen.findByLabelText("所属阶段"), stage.id);
  await userEvent.selectOptions(screen.getByLabelText("所属里程碑"), milestone.id);
  archived = true;
  await client.invalidateQueries({queryKey: ["project-structure", org, project.id]});
  expect(screen.getByLabelText("任务标题")).toHaveValue("Keep draft");
  await waitFor(() => expect(document.querySelector(`option[value="${stage.id}"]`)).toBeNull());
  expect(document.querySelector(`option[value="${milestone.id}"]`)).toBeNull();
  expect(screen.getByText("所选结构已归档，请清空归属或选择活动阶段与里程碑。")).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "保存任务"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button", {name: "清空归属"}));
  expect(screen.getByLabelText("任务标题")).toHaveValue("Keep draft");
  expect(screen.getByRole("button", {name: "保存任务"})).toBeEnabled();
});

test.each(["create", "move"])("milestone %s draft retains all fields and blocks a newly archived stage after task-save refresh", async operation => {
  const targetStage = {...stage, id: "00000000-0000-4000-8000-000000006002", name: "Draft target", position: 1};
  const activeStage = {...stage, id: "00000000-0000-4000-8000-000000006003", name: "Active recovery", position: 2};
  let archived = false;
  let version = 1;
  let task = {id: "00000000-0000-4000-8000-000000005001", projectId: project.id, revision: 1, title: "Refresh task", description: null, assigneeUserId: null, stageId: null, milestoneId: null, parentTaskId: null, status: "todo", priority: "medium", dueAt: null, acceptanceCriteria: null, createdAt: project.createdAt, updatedAt: project.updatedAt};
  let storedMilestone = milestone;
  const milestoneWrites: Record<string, unknown>[] = [];
  const client = setup(async request => {
    const path = new URL(request.url).pathname;
    if (request.method === "PATCH" && path.includes("/tasks/")) {
      task = {...task, ...await request.json(), revision: task.revision + 1};
      version++;
      return response(task);
    }
    if (request.method !== "GET" && path.includes("/milestones")) {
      const body = await request.json();
      milestoneWrites.push(body);
      version++;
      storedMilestone = {...storedMilestone, ...body, revision: operation === "move" ? 2 : 1};
      return response(storedMilestone, operation === "move" ? 200 : 201);
    }
    if (path.endsWith("/projects")) return response({items: [project], nextCursor: null});
    if (path.endsWith("/stages")) return response({items: [stage, {...targetStage, archived}, activeStage], nextCursor: null});
    if (path.endsWith("/milestones")) return response({items: operation === "move" || milestoneWrites.length ? [storedMilestone] : [], nextCursor: null});
    if (path.endsWith("/tasks")) return response({items: [task], nextCursor: null});
    if (path.endsWith("/assignees") || path.endsWith("/dependencies")) return response({items: [], nextCursor: null});
    if (path.includes("/tasks/")) return response(task);
    return response({...project, revision: version});
  });
  page(client);
  await userEvent.click(await screen.findByRole("button", {name: operation === "move" ? "编辑里程碑：Review" : "创建里程碑"}));
  await userEvent.clear(screen.getByLabelText("里程碑名称"));
  await userEvent.type(screen.getByLabelText("里程碑名称"), "Keep milestone draft");
  await userEvent.type(screen.getByLabelText("里程碑说明"), "Keep description");
  await userEvent.type(screen.getByLabelText("里程碑验收标准"), "Keep acceptance");
  fireEvent.change(screen.getByLabelText("里程碑截止时间（本地时区）"), {target: {value: "2026-10-20T12:30"}});
  await userEvent.selectOptions(screen.getByLabelText("里程碑所属阶段"), targetStage.id);
  await userEvent.click(screen.getByRole("button", {name: "查看任务：Refresh task"}));
  await userEvent.type(await screen.findByLabelText("任务标题"), " updated");
  archived = true;
  version++;
  await userEvent.click(screen.getByRole("button", {name: "保存任务"}));
  await screen.findByText("任务已保存。");
  await waitFor(() => expect(document.querySelector(`option[value="${targetStage.id}"]`)).toBeNull());
  expect(screen.getByLabelText("里程碑名称")).toHaveValue("Keep milestone draft");
  expect(screen.getByLabelText("里程碑说明")).toHaveValue("Keep description");
  expect(screen.getByLabelText("里程碑验收标准")).toHaveValue("Keep acceptance");
  expect(screen.getByLabelText("里程碑截止时间（本地时区）")).toHaveValue("2026-10-20T12:30");
  expect(screen.getByRole("button", {name: "保存里程碑"})).toBeDisabled();
  expect(screen.getByText("所选阶段已归档，请清空里程碑所属阶段或选择活动阶段。其他输入已保留。")).toBeInTheDocument();
  fireEvent.submit(screen.getByRole("form", {name: "里程碑表单"}));
  expect(milestoneWrites).toHaveLength(0);
  if (operation === "create") await userEvent.click(screen.getByRole("button", {name: "清空里程碑所属阶段"}));
  else await userEvent.selectOptions(screen.getByLabelText("里程碑所属阶段"), activeStage.id);
  await waitFor(() => expect(screen.getByRole("button", {name: "保存里程碑"})).toBeEnabled());
  await userEvent.click(screen.getByRole("button", {name: "保存里程碑"}));
  await screen.findByText("项目结构已保存。");
  expect(milestoneWrites).toHaveLength(1);
  expect(milestoneWrites[0]).toEqual({
    name: "Keep milestone draft", description: "Keep description", acceptanceCriteria: "Keep acceptance",
    stageId: operation === "move" ? activeStage.id : null,
    dueAt: new Date("2026-10-20T12:30").toISOString(), expectedProjectRevision: 3,
    ...(operation === "move" ? {expectedRevision: 1} : {})
  });
});
