import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectTaskGraph } from "../../src/components/projects/ProjectTaskGraph.tsx";
import { structureKeys } from "../../src/queries/projects.ts";

const pid = "00000000-0000-4000-8000-000000004001";
const sid = "00000000-0000-4000-8000-000000006001";
const first = "00000000-0000-4000-8000-000000005001";
const second = "00000000-0000-4000-8000-000000005002";
const snapshot = {
  project: { id: pid, revision: 4, name: "真实项目", description: null, createdAt: "2026-10-23T00:00:00Z", updatedAt: "2026-10-23T00:00:00Z" },
  readAt: "2026-10-23T13:00:00Z",
  tasks: [
    { id: first, projectId: pid, revision: 1, title: "确认输入", status: "in_progress", stageId: sid, milestoneId: null },
    { id: second, projectId: pid, revision: 2, title: "交付结果", status: "todo", stageId: null, milestoneId: null },
  ],
  stages: [{ id: sid, name: "准备", position: 0, archived: false }], milestones: [],
  dependencies: [{ id: "00000000-0000-4000-8000-000000007001", predecessorTaskId: first, successorTaskId: second, createdAt: "2026-10-23T00:00:00Z" }],
};
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
function mount(onOpen = vi.fn()) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<QueryClientProvider client={client}><ProjectTaskGraph organizationId="org" projectId={pid} signal={new AbortController().signal} selectedTaskId={null} disabled={false} onOpenTask={onOpen}/></QueryClientProvider>);
  return {client, onOpen};
}
afterEach(() => vi.unstubAllGlobals());

test("real nodes expose status, stage and waiting predecessors, and open the actual task", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => reply(snapshot)));
  const {onOpen} = mount();
  const target = await screen.findByRole("button", {name: /查看任务：交付结果/});
  expect(screen.getByText("前置未完成 1")).toBeInTheDocument();
  expect(screen.getByText("准备")).toBeInTheDocument();
  fireEvent.click(target);
  expect(onOpen).toHaveBeenCalledWith(second);
  expect(document.querySelectorAll(".task-graph-edge")).toHaveLength(1);
});

test("existing project invalidation refreshes the graph after a task change", async () => {
  let body = snapshot;
  vi.stubGlobal("fetch", vi.fn(async () => reply(body)));
  const {client} = mount();
  await screen.findByText("前置未完成 1");
  body = {...snapshot, tasks: snapshot.tasks.map(node => node.id === first ? {...node, status:"done", revision:2} : node)};
  await client.invalidateQueries({queryKey: structureKeys.scope("org", pid)});
  await waitFor(() => expect(screen.queryByText("前置未完成 1")).not.toBeInTheDocument());
  expect(screen.getByText("已完成 1 / 2")).toBeInTheDocument();
});

test("a refresh denial removes cached nodes and offers an explicit reread", async () => {
  let denied = false;
  vi.stubGlobal("fetch", vi.fn(async () => denied ? reply({code:"not_found",message:"资源不存在",traceId:"graph-denied"},404) : reply(snapshot)));
  const {client} = mount();
  await screen.findByRole("button", {name:/查看任务：确认输入/});
  denied = true;
  await client.invalidateQueries({queryKey: structureKeys.scope("org", pid)});
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", {name:/查看任务：确认输入/})).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name:"重新读取节点图"})).toBeInTheDocument();
});

test("invalid edge references are rejected instead of drawing a partial graph", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => reply({...snapshot, tasks:[snapshot.tasks[0]]})));
  mount();
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", {name:/查看任务：确认输入/})).not.toBeInTheDocument();
});

test("all snapshot nodes render without inheriting the task list page size", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => reply({...snapshot, dependencies: [], tasks: Array.from({length:65},(_,index)=>({...snapshot.tasks[0], id:`00000000-0000-4000-8000-${String(index+5000).padStart(12,"0")}`,title:`真实任务 ${index}`}))})));
  mount();
  await screen.findByRole("button",{name:/查看任务：真实任务 64/});
  expect(screen.getAllByRole("button",{name:/查看任务：真实任务 /})).toHaveLength(65);
});
