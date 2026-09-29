import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AppRoutes } from "../../src/app/AppRoutes.tsx";
import type { IdentityContext } from "../../src/api/auth.ts";
import { createAppQueryClient } from "../../src/app/queryClient.ts";
import { SessionProvider } from "../../src/session/SessionContext.tsx";
import { useSession } from "../../src/session/SessionContext.tsx";
import { ThemeProvider } from "../../src/theme/ThemeContext.tsx";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const SOURCE_ID = "00000000-0000-4000-8000-000000011001";
const ORG_ID = "00000000-0000-4000-8000-000000002001";
const SOURCE_ROUTE = `/projects/${PROJECT_ID}/knowledge/sources`;
const identity: IdentityContext = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
  organization: { id: ORG_ID, slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
  csrfToken: "csrf-current",
};
const source = {
  id: SOURCE_ID, projectId: PROJECT_ID, provider: "feishu", name: "团队手册",
  documentId: "Doc123", credentialRef: "team_feishu", accessPolicy: "project_members",
  status: "configured", accessState: "available", syncIntervalSeconds: null,
  nextSyncAt: null, lastCheckedAt: null, lastSuccessAt: null, lastErrorCode: null,
  disabledAt: null, createdAt: "2026-09-29T00:00:00Z", updatedAt: "2026-09-29T00:00:00Z",
} as const;
const project = { id: PROJECT_ID, name: "测试项目", description: null,
  createdAt: "2026-09-29T00:00:00Z", updatedAt: "2026-09-29T00:00:00Z" };
const json = (body: unknown, status = 200) => Response.json(body, { status });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
};
let navigate: NavigateFunction;
let establishSession: (identity: IdentityContext) => void;
function NavigationProbe() {
  navigate = useNavigate();
  establishSession = useSession().establishSession;
  return null;
}
function renderRoute(initial = SOURCE_ROUTE, role: IdentityContext["membership"]["role"] = "owner") {
  const queryClient = createAppQueryClient();
  render(<ThemeProvider><QueryClientProvider client={queryClient}>
    <MemoryRouter initialEntries={[initial]}>
      <SessionProvider restoredIdentity={{ ...identity, membership: { ...identity.membership, role } }}>
        <NavigationProbe /><AppRoutes />
      </SessionProvider>
    </MemoryRouter>
  </QueryClientProvider></ThemeProvider>);
  return { queryClient };
}
function defaultFetch(sourcePage: unknown[] = [source]) {
  return vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === `/api/v1/projects/${PROJECT_ID}`) return json(project);
    if (path === `/api/v1/projects/${PROJECT_ID}/knowledge/sources`)
      return json({ items: sourcePage, nextCursor: null });
    if (path === `/api/v1/projects/${PROJECT_ID}/knowledge/sources/${SOURCE_ID}/syncs`)
      return json({ items: [], nextCursor: null });
    if (path === "/api/v1/projects") return json({ items: [project], nextCursor: null });
    if (path.endsWith("/knowledge/resources")) return json({ items: [], nextCursor: null,
      capabilities: { canRead: true, canWrite: true } });
    return json({ items: [], nextCursor: null });
  });
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, media: "", addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
});
afterEach(() => {
  vi.unstubAllGlobals(); vi.restoreAllMocks();
  Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
});

test("member direct route exposes no source configuration and sends no source request", async () => {
  const fetcher = defaultFetch(); vi.stubGlobal("fetch", fetcher);
  renderRoute(SOURCE_ROUTE, "member");
  expect(await screen.findByText("仅组织管理员可以管理飞书来源。")).toBeInTheDocument();
  expect(screen.queryByLabelText("凭证别名")).toBeNull();
  expect(fetcher.mock.calls.some(([request]) => new URL(request.url).pathname.includes("/knowledge/sources"))).toBe(false);
});

test("admin creates a docx source only after valid fields and explicit sharing", async () => {
  const base = defaultFetch([]);
  const requests: Request[] = [];
  let sources = [] as unknown[];
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    requests.push(request);
    const path = new URL(request.url).pathname;
    if (path === `/api/v1/projects/${PROJECT_ID}/knowledge/sources`) {
      return json({ items: sources, nextCursor: null });
    }
    if (path.endsWith("/knowledge/sources/feishu") && request.method === "POST") {
      sources = [{ ...source, accessState: "unverified" }];
      return json(sources[0], 201);
    }
    return base(request);
  }));
  renderRoute();
  await screen.findByText("还没有飞书来源");
  fireEvent.click(screen.getByRole("button", { name: "添加来源" }));
  const form = screen.getByRole("region", { name: "添加飞书来源" });
  const submit = within(form).getByRole("button", { name: "添加来源" });
  expect(submit).toBeDisabled();
  fireEvent.change(within(form).getByLabelText("来源名称"), { target: { value: "团队手册" } });
  fireEvent.change(within(form).getByLabelText("飞书文档链接或 ID"), {
    target: { value: "https://feishu.cn.evil.invalid/docx/Doc123" },
  });
  fireEvent.change(within(form).getByLabelText("凭证别名"), { target: { value: "team_feishu" } });
  fireEvent.click(within(form).getByRole("checkbox", { name: /我确认将此文档共享/ }));
  expect(submit).toBeDisabled();
  fireEvent.change(within(form).getByLabelText("飞书文档链接或 ID"), {
    target: { value: "https://team.feishu.cn/docx/Doc123?from=copy" },
  });
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  await screen.findByText("来源已登记。现在可以手动同步文档。");
  const post = requests.find((request) => request.method === "POST");
  expect(post).toBeDefined();
  expect(post?.headers.get("X-CSRF-Token")).toBe("csrf-current");
  expect(JSON.parse(await post!.text())).toEqual({
    name: "团队手册", documentId: "Doc123", credentialRef: "team_feishu",
    accessPolicy: "project_members", syncIntervalSeconds: null,
  });
});

test("a duplicate create shows a fixed conflict and keeps the form", async () => {
  const base = defaultFetch([]);
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    if (request.method === "POST" && new URL(request.url).pathname.endsWith("/knowledge/sources/feishu")) {
      return json({ code: "source_conflict", message: "private", traceId: "conflict-1" }, 409);
    }
    return base(request);
  }));
  renderRoute();
  await screen.findByText("还没有飞书来源");
  fireEvent.click(screen.getByRole("button", { name: "添加来源" }));
  const form = screen.getByRole("region", { name: "添加飞书来源" });
  fireEvent.change(within(form).getByLabelText("来源名称"), { target: { value: "团队手册" } });
  fireEvent.change(within(form).getByLabelText("飞书文档链接或 ID"), { target: { value: "Doc123" } });
  fireEvent.change(within(form).getByLabelText("凭证别名"), { target: { value: "team_feishu" } });
  fireEvent.click(within(form).getByRole("checkbox", { name: /我确认将此文档共享/ }));
  fireEvent.click(within(form).getByRole("button", { name: "添加来源" }));
  expect(await within(form).findByText("该飞书文档已登记，请在来源列表中查看")).toBeInTheDocument();
  expect(within(form).getByLabelText("来源名称")).toHaveValue("团队手册");
});

test("admin syncs, edits period, stops and explicitly restores a source", async () => {
  let current: typeof source | Record<string, unknown> = source;
  const sync = {
    id: "00000000-0000-4000-8000-000000012001", projectId: PROJECT_ID, sourceId: SOURCE_ID,
    status: "completed", resourceStatus: "ready", attempt: 1, trigger: "manual",
    createdAt: "2026-09-29T00:00:00Z", completedAt: "2026-09-29T00:01:00Z",
    errorCode: null, failureCode: null, nextAttemptAt: null,
    resourceId: "00000000-0000-4000-8000-000000013001",
    resourceVersionId: "00000000-0000-4000-8000-000000014001",
  } as const;
  let history = [] as unknown[];
  const requests: Request[] = [];
  const base = defaultFetch();
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    requests.push(request);
    const path = new URL(request.url).pathname;
    if (path === `/api/v1/projects/${PROJECT_ID}/knowledge/sources` && request.method === "GET")
      return json({ items: [current], nextCursor: null });
    if (path === `/api/v1/projects/${PROJECT_ID}/knowledge/sources/${SOURCE_ID}/syncs`) {
      if (request.method === "POST") { history = [sync]; return json(sync, 202); }
      return json({ items: history, nextCursor: null });
    }
    if (path.endsWith(`/syncs/${sync.id}`)) return json(sync);
    if (path === `/api/v1/projects/${PROJECT_ID}/knowledge/sources/${SOURCE_ID}`) {
      if (request.method === "PATCH") {
        const body = JSON.parse(await request.clone().text()) as Record<string, unknown>;
        current = { ...current, ...body,
          disabledAt: body.status === "configured" ? null : (current as typeof source).disabledAt,
          accessState: body.status === "configured" ? "unverified" : (current as typeof source).accessState,
        };
        return json(current);
      }
      if (request.method === "DELETE") {
        current = { ...current, status: "disabled", disabledAt: "2026-09-29T00:02:00Z" };
        return new Response(null, { status: 204 });
      }
    }
    return base(request);
  }));
  renderRoute();
  fireEvent.click(await screen.findByRole("button", { name: /团队手册/ }));
  fireEvent.click(screen.getByRole("button", { name: "立即同步" }));
  expect(await screen.findByText("可检索")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "编辑设置" }));
  fireEvent.change(screen.getByLabelText("同步周期"), { target: { value: "900" } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  expect(await screen.findByText("来源设置已保存。")).toBeInTheDocument();
  expect(screen.getAllByText("每 15 分钟")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "停用来源" }));
  expect(screen.getByText(/停用「团队手册」/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "确认停用 团队手册" }));
  expect(await screen.findByText(/来源已停用，项目成员无法再读取/)).toBeInTheDocument();
  const restore = screen.getByRole("button", { name: "恢复来源" });
  expect(restore).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /我确认将此文档共享/ }));
  expect(restore).toBeEnabled();
  fireEvent.click(restore);
  expect(await screen.findByText(/来源已恢复。请手动同步/)).toBeInTheDocument();
  const patches = requests.filter((request) => request.method === "PATCH");
  expect(patches).toHaveLength(2);
  expect(JSON.parse(await patches[0]!.text())).toEqual({ syncIntervalSeconds: 900 });
  expect(JSON.parse(await patches[1]!.text())).toEqual({
    status: "configured", accessPolicy: "project_members",
  });
});

test("history tracks the newest queued sync on the first page", async () => {
  const oldId = "00000000-0000-4000-8000-000000012001";
  const newId = "00000000-0000-4000-8000-000000012002";
  const old = { id: oldId, projectId: PROJECT_ID, sourceId: SOURCE_ID,
    status: "completed", resourceStatus: "ready", trigger: "manual", attempt: 1,
    createdAt: "2026-09-29T00:00:00Z", completedAt: "2026-09-29T00:01:00Z",
    errorCode: null, failureCode: null, nextAttemptAt: null,
    resourceId: "00000000-0000-4000-8000-000000013001",
    resourceVersionId: "00000000-0000-4000-8000-000000014001" };
  const newest = { ...old, id: newId, status: "queued", resourceStatus: null,
    createdAt: "2026-09-29T00:02:00Z", completedAt: null,
    resourceId: null, resourceVersionId: null };
  const detailReads: string[] = [];
  const base = defaultFetch();
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === `/api/v1/projects/${PROJECT_ID}/knowledge/sources/${SOURCE_ID}/syncs`)
      return json({ items: [newest, old], nextCursor: "older-page" });
    if (path.endsWith(`/syncs/${newId}`) || path.endsWith(`/syncs/${oldId}`)) {
      detailReads.push(path); return json(path.endsWith(newId) ? newest : old);
    }
    return base(request);
  }));
  renderRoute();
  fireEvent.click(await screen.findByRole("button", { name: /团队手册/ }));
  await waitFor(() => expect(detailReads).toContain(
    `/api/v1/projects/${PROJECT_ID}/knowledge/sources/${SOURCE_ID}/syncs/${newId}`));
  expect(detailReads.some((path) => path.endsWith(oldId))).toBe(false);
  expect(screen.getByText("等待同步")).toBeInTheDocument();
});

test("disabled detail has one edit action and a single main landmark", async () => {
  vi.stubGlobal("fetch", defaultFetch([{ ...source, status: "disabled", disabledAt: "2026-09-29T00:01:00Z" }]));
  renderRoute();
  fireEvent.click(await screen.findByRole("button", { name: /团队手册/ }));
  expect(screen.getAllByRole("button", { name: "编辑设置" })).toHaveLength(1);
  expect(document.querySelectorAll("main")).toHaveLength(1);
});

test("route reentry hides cached document and alias until fresh source authorization", async () => {
  const second = deferred<Response>();
  let sourceReads = 0;
  const base = defaultFetch();
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    if (new URL(request.url).pathname === `/api/v1/projects/${PROJECT_ID}/knowledge/sources`) {
      sourceReads += 1;
      if (sourceReads === 2) return second.promise;
    }
    return base(request);
  }));
  renderRoute();
  fireEvent.click(await screen.findByRole("button", { name: /团队手册/ }));
  expect(screen.getByText("Doc123")).toBeInTheDocument();
  act(() => navigate("/projects"));
  expect(await screen.findByRole("heading", { name: "项目任务" })).toBeInTheDocument();
  act(() => navigate(SOURCE_ROUTE));
  await waitFor(() => expect(sourceReads).toBe(2));
  const staleSelection = screen.queryByRole("button", { name: /团队手册/ });
  if (staleSelection) fireEvent.click(staleSelection);
  expect(staleSelection).toBeNull();
  expect(screen.queryByText("Doc123")).toBeNull();
  expect(screen.queryByText("team_feishu")).toBeNull();
  await act(async () => { second.resolve(json({ items: [source], nextCursor: null })); });
  fireEvent.click(await screen.findByRole("button", { name: /团队手册/ }));
  expect(screen.getByText("Doc123")).toBeInTheDocument();
});

test("source 404 removes private source and knowledge caches", async () => {
  const pending = deferred<Response>();
  const base = defaultFetch();
  vi.stubGlobal("fetch", vi.fn(async (request: Request) =>
    new URL(request.url).pathname === `/api/v1/projects/${PROJECT_ID}/knowledge/sources`
      ? pending.promise : base(request)));
  const { queryClient } = renderRoute();
  queryClient.setQueryData(["project-knowledge", ORG_ID, PROJECT_ID, "search", "old answer"], "private-answer");
  await act(async () => {
    pending.resolve(json({ code: "not_found", message: "gone", traceId: "trace-404" }, 404));
  });
  expect(await screen.findByText("项目来源不可用或你已失去管理权限。")).toBeInTheDocument();
  await waitFor(() => expect(queryClient.getQueryData([
    "project-knowledge", ORG_ID, PROJECT_ID, "search", "old answer",
  ])).toBeUndefined());
  expect(screen.queryByText("private-answer")).toBeNull();
});

test("a late old-session source response cannot repopulate the replacement session", async () => {
  const oldResponse = deferred<Response>();
  let reads = 0;
  const base = defaultFetch([]);
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    if (new URL(request.url).pathname === `/api/v1/projects/${PROJECT_ID}/knowledge/sources`) {
      reads += 1;
      return reads === 1 ? oldResponse.promise : json({ items: [], nextCursor: null });
    }
    return base(request);
  }));
  renderRoute();
  await waitFor(() => expect(reads).toBe(1));
  act(() => establishSession({ ...identity, organization: {
    ...identity.organization, id: "00000000-0000-4000-8000-000000002002",
  } }));
  await waitFor(() => expect(reads).toBe(2));
  await act(async () => oldResponse.resolve(json({ items: [source], nextCursor: null })));
  expect(screen.queryByText("团队手册")).toBeNull();
  expect(screen.queryByText("team_feishu")).toBeNull();
});

test("offline during post-mutation invalidation does not refetch private sources", async () => {
  const base = defaultFetch([]);
  const created = { ...source, accessState: "unverified" };
  let sourceReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === `/api/v1/projects/${PROJECT_ID}/knowledge/sources`) sourceReads += 1;
    if (path.endsWith("/knowledge/sources/feishu") && request.method === "POST") return json(created, 201);
    return base(request);
  }));
  const { queryClient } = renderRoute();
  await screen.findByText("还没有飞书来源");
  const gate = deferred<void>();
  const originalCancel = queryClient.cancelQueries.bind(queryClient);
  let gated = false;
  vi.spyOn(queryClient, "cancelQueries").mockImplementation(async (...args) => {
    if (!gated) { gated = true; await gate.promise; }
    return originalCancel(...args);
  });
  fireEvent.click(screen.getByRole("button", { name: "添加来源" }));
  fireEvent.change(screen.getByLabelText("来源名称"), { target: { value: "团队手册" } });
  fireEvent.change(screen.getByLabelText("飞书文档链接或 ID"), { target: { value: "Doc123" } });
  fireEvent.change(screen.getByLabelText("凭证别名"), { target: { value: "team_feishu" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /我确认将此文档共享/ }));
  fireEvent.click(within(screen.getByRole("region", { name: "添加飞书来源" })).getByRole("button", { name: "添加来源" }));
  await waitFor(() => expect(gated).toBe(true));
  const beforeOffline = sourceReads;
  act(() => { Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    window.dispatchEvent(new Event("offline")); });
  await act(async () => gate.resolve());
  expect(sourceReads).toBe(beforeOffline);
  expect(screen.queryByText("Doc123")).toBeNull();
});
