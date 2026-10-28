import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectSchedule } from "../../src/components/projects/ProjectSchedule.tsx";
import { TaskEditor } from "../../src/components/projects/TaskEditor.tsx";
import { projectKeys } from "../../src/queries/projects.ts";
import { hoursToMinutes } from "../../src/lib/effort.ts";

vi.mock("../../src/session/SessionContext.tsx",()=>({useSessionErrorReporter:()=>vi.fn()}));
const pid="00000000-0000-4000-8000-000000004001",tid="00000000-0000-4000-8000-000000005001",org="00000000-0000-4000-8000-000000003001",now="2026-10-25T04:00:00Z";
const project={id:pid,revision:1,name:"交付项目",description:null,createdAt:now,updatedAt:now,dailyCapacityMinutes:480,workingWeekdays:[1,2,3,4,5]};
const task={id:tid,projectId:pid,revision:1,title:"验收任务",description:null,assigneeUserId:null,stageId:null,milestoneId:null,parentTaskId:null,status:"todo" as const,priority:"medium" as const,dueAt:null,acceptanceCriteria:null,createdAt:now,updatedAt:now,estimatedEffortMinutes:300,remainingEffortMinutes:600};
const scenario={project,readAt:now,startDate:"2026-10-26",effectiveStartDate:"2026-10-26",completionDate:"2026-10-27",tasks:[{id:tid,revision:task.revision,title:task.title,status:task.status,priority:task.priority,createdAt:now,estimatedEffortMinutes:300,remainingEffortMinutes:600}],dependencies:[],knownRemainingMinutes:600,gaps:[],warnings:[],schedule:[{taskId:tid,startOffsetMinutes:0,endOffsetMinutes:600,startDate:"2026-10-26",endDate:"2026-10-27"}],criticalChain:{taskIds:[tid],remainingMinutes:600,workdayLowerBound:1.25},canWrite:true,method:"serial_shared_capacity",assumptions:["统一共享产能，串行排程。"]};
const reply=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}});
function renderSchedule(){const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});const signal=new AbortController().signal;return {client,...render(<QueryClientProvider client={client}><ProjectSchedule organizationId={org} projectId={pid} csrfToken="csrf" signal={signal} onOpenTask={vi.fn()}/></QueryClientProvider>)};}
async function calculate(){fireEvent.change(screen.getByLabelText("情景开始日期"),{target:{value:"2026-10-26"}});fireEvent.click(screen.getByRole("button",{name:"计算工期情景"}));await screen.findByRole("heading",{name:"串行资源排程"});}
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

test("explicit calculation separates actual task input, shared-capacity dates and dependency lower bound",async()=>{
  const calls:Request[]=[];vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{calls.push(request);return reply(request.url.includes("schedule-scenario")?scenario:project);}));
  renderSchedule();await waitFor(()=>expect(calls).toHaveLength(1));expect(calls[0]!.url).not.toContain("schedule-scenario");await calculate();
  expect(screen.getByText(/情景完成/)).toHaveTextContent("2026-10-27");expect(screen.getByRole("heading",{name:"最长依赖链下界"})).toBeVisible();expect(screen.getByText(/1.25 个理论工作日/)).toBeVisible();expect(screen.getByText(/待处理 · 修订 1/)).toBeVisible();expect(screen.getByText("0 → 600 分钟")).toBeVisible();
});

test("input revision changes immediately hide prior dates until explicit recalculation",async()=>{
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>reply(request.url.includes("schedule-scenario")?scenario:project)));const {client}=renderSchedule();await calculate();
  act(()=>{client.setQueryData(projectKeys.detail(org,pid),{...project,revision:2});});
  expect(await screen.findByText(/旧情景已隐藏/)).toBeVisible();expect(screen.queryByRole("heading",{name:"串行资源排程"})).not.toBeInTheDocument();expect(screen.queryByText("2026-10-27")).not.toBeInTheDocument();
});

test("a delayed scenario never overwrites a newer project revision or restores old dates",async()=>{
  let finish!:(value:Response)=>void;vi.stubGlobal("fetch",vi.fn((request:Request)=>request.url.includes("schedule-scenario")?new Promise<Response>(resolve=>{finish=resolve;}):Promise.resolve(reply(project))));const {client}=renderSchedule();
  fireEvent.change(screen.getByLabelText("情景开始日期"),{target:{value:"2026-10-26"}});fireEvent.click(screen.getByRole("button",{name:"计算工期情景"}));await waitFor(()=>expect(finish).toBeDefined());
  act(()=>{client.setQueryData(projectKeys.detail(org,pid),{...project,revision:2});});await act(async()=>{finish(reply(scenario));});
  expect(await screen.findByText("计算期间项目已更新，请重新计算。")).toBeVisible();expect(client.getQueryData(projectKeys.detail(org,pid))).toMatchObject({revision:2});expect(screen.queryByRole("heading",{name:"串行资源排程"})).not.toBeInTheDocument();
});

test("data gaps show known work and actual status without predicted or critical dates",async()=>{
  const body={...scenario,completionDate:null,effectiveStartDate:null,schedule:[],criticalChain:null,gaps:[{code:"blocked_task",message:"任务已阻塞，尚无解除阻塞日期。",taskIds:[tid]}],tasks:[{...scenario.tasks[0],status:"blocked"}]};vi.stubGlobal("fetch",vi.fn(async(request:Request)=>reply(request.url.includes("schedule-scenario")?body:project)));renderSchedule();fireEvent.change(screen.getByLabelText("情景开始日期"),{target:{value:"2026-10-26"}});fireEvent.click(screen.getByRole("button",{name:"计算工期情景"}));
  expect(await screen.findByRole("heading",{name:"暂不能给出完成日期"})).toBeVisible();expect(screen.getByText(/已知剩余工作量/)).toHaveTextContent("600 分钟");expect(screen.getByText(/已阻塞 · 修订 1/)).toBeVisible();expect(screen.queryByRole("heading",{name:"最长依赖链下界"})).not.toBeInTheDocument();
});

test("project capacity saves total hours as integer minutes with calendar and revision",async()=>{
  let current=project;let body:unknown=null;vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{if(request.method==="PATCH"){body=await request.json();expect(request.headers.get("X-CSRF-Token")).toBe("csrf");current={...project,revision:2,dailyCapacityMinutes:90,workingWeekdays:[1,2,3,4]};return reply(current);}return reply(request.url.includes("schedule-scenario")?scenario:current);}));
  renderSchedule();await calculate();fireEvent.click(screen.getByText("设置项目每日可投入总人时"));fireEvent.change(screen.getByLabelText("每天可投入的人时（整个项目合计）"),{target:{value:"1.5"}});fireEvent.click(screen.getByLabelText("周五"));fireEvent.click(screen.getByRole("button",{name:"保存项目产能"}));
  expect(await screen.findByText("产能已保存，请重新计算工期情景。")).toBeVisible();expect(body).toEqual({expectedProjectRevision:1,dailyCapacityMinutes:90,workingWeekdays:[1,2,3,4]});expect(screen.queryByRole("heading",{name:"串行资源排程"})).not.toBeInTheDocument();
});

test("capacity conflict preserves entered hours and read-only scenarios expose no settings",async()=>{
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>request.method==="PATCH"?reply({code:"revision_conflict",message:"项目已更新",traceId:"capacity-stale"},409):reply(request.url.includes("schedule-scenario")?scenario:project)));const view=renderSchedule();await calculate();fireEvent.click(screen.getByText("设置项目每日可投入总人时"));fireEvent.change(screen.getByLabelText("每天可投入的人时（整个项目合计）"),{target:{value:"3"}});fireEvent.click(screen.getByRole("button",{name:"保存项目产能"}));expect(await screen.findByRole("alert")).toHaveTextContent("项目已更新");expect(screen.getByLabelText("每天可投入的人时（整个项目合计）")).toHaveValue(3);view.unmount();
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>reply(request.url.includes("schedule-scenario")?{...scenario,canWrite:false}:project)));renderSchedule();await calculate();expect(screen.getByText(/当前为只读访问/)).toBeVisible();expect(screen.queryByText("设置项目每日可投入总人时")).not.toBeInTheDocument();
});

test("task effort editor keeps blanks unknown and converts decimal hours without changing actual status",async()=>{
  let patch:unknown;vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{if(request.method==="PATCH"){patch=await request.json();return reply({...task,revision:2,estimatedEffortMinutes:null,remainingEffortMinutes:90});}if(new URL(request.url).pathname===`/api/v1/projects/${pid}`)return reply(project);return reply({items:[],nextCursor:null});}));const client=new QueryClient({defaultOptions:{queries:{retry:false}}});render(<QueryClientProvider client={client}><TaskEditor task={task} organizationId={org} projectId={pid} csrfToken="csrf" signal={new AbortController().signal} onSaved={async()=>true}/></QueryClientProvider>);
  await waitFor(()=>expect(screen.getByRole("button",{name:"保存任务"})).toBeEnabled());fireEvent.change(screen.getByLabelText("初始估算（人时）"),{target:{value:""}});fireEvent.change(screen.getByLabelText("剩余工作量（人时）"),{target:{value:"1.5"}});fireEvent.click(screen.getByRole("button",{name:"保存任务"}));expect(await screen.findByText("任务已保存。")).toBeVisible();expect(patch).toMatchObject({estimatedEffortMinutes:null,remainingEffortMinutes:90});expect(patch).not.toHaveProperty("status");
});

test("hours conversion distinguishes unknown, explicit zero and subminute rounding",()=>{expect(hoursToMinutes("")).toBeNull();expect(hoursToMinutes("0")).toBe(0);expect(hoursToMinutes("1.5")).toBe(90);expect(hoursToMinutes("0.01")).toBe(1);expect(()=>hoursToMinutes("-0.001")).toThrow();expect(()=>hoursToMinutes("Infinity")).toThrow();});
