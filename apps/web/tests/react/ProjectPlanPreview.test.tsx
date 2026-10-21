import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectPlanPreview } from "../../src/components/projects/ProjectPlanPreview.tsx";

vi.mock("../../src/session/SessionContext.tsx", () => ({ useSessionErrorReporter: () => vi.fn() }));
const pid = "00000000-0000-4000-8000-000000004001";
const now = "2026-10-19T08:20:00Z";
const result = {
  projectId: pid, generatedAt: now, assistantName: "项目顾问",
  model: { id: "default", name: "规划模型", model: "synthetic", protocol: "openai-compatible" },
  snapshot: { project: { id: pid, revision: 1, name: "交付项目", description: "发布可用版本", createdAt: now, updatedAt: now }, stages: [], milestones: [], tasks: [], dependencies: [] },
  retrievalMode: "keyword_fallback", citations: [],
  plan: {
    status: "planned", summary: "先确认发布条件，再执行验收。", assumptions: ["部署窗口待确认"], citationIds: ["S1"],
    stages: [{id:"P1",name:"发布准备",goal:"满足发布条件",citationIds:["S1"]}],
    milestones: [{id:"M1",stageId:"P1",name:"发布就绪",acceptanceCriteria:"关键检查通过",citationIds:["S1"]}],
    tasks: [
      {id:"T1",stageId:"P1",milestoneId:"M1",title:"确认窗口",description:"与成员确认部署时间",acceptanceCriteria:"窗口已记录",priority:"high",dependsOn:[],citationIds:["S1"]},
      {id:"T2",stageId:"P1",milestoneId:"M1",title:"执行验收",description:"检查生产访问",acceptanceCriteria:"验收已记录",priority:"high",dependsOn:["T1"],citationIds:["S1"]},
    ],
  },
};
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status,headers:{"Content-Type":"application/json"}});
afterEach(() => vi.unstubAllGlobals());

test("generates a read-only plan with stages, milestones and a navigable dependency graph", async () => {
  const requests: Request[] = [];
  vi.stubGlobal("fetch",vi.fn(async(request: Request) => {requests.push(request); return reply(result);}));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  expect(requests).toHaveLength(0);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  expect(await screen.findByText(result.plan.summary)).toBeVisible();
  expect(screen.getByRole("heading",{name:"P1 · 发布准备"})).toBeVisible();
  expect(screen.getByText(/发布就绪/)).toBeVisible();
  expect(screen.getByRole("group",{name:"规划任务依赖图"})).toBeVisible();
  const node=screen.getByRole("button",{name:"查看建议任务：执行验收"});
  fireEvent.keyDown(node,{key:"Enter"});
  expect(screen.getByRole("article",{name:"T2 · 执行验收"})).toHaveAttribute("data-selected","true");
  expect(screen.getByText("部署窗口待确认")).toBeVisible();
  expect(screen.getByText(/尚未创建或修改项目任务/)).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0]!.url).toContain(`/projects/${pid}/plan-preview`);
  expect(requests[0]!.headers.get("X-CSRF-Token")).toBe("csrf");
});

test.each(["cycle","reference","stage","citation"])("rejects invalid %s before drawing a plan",async invalid => {
  const body=structuredClone(result);
  if(invalid==="cycle") body.plan.tasks[0]!.dependsOn=["T2"];
  else if(invalid==="reference") body.plan.tasks[1]!.dependsOn=["T9"];
  else if(invalid==="stage") body.plan.tasks[0]!.stageId="P5";
  else body.plan.tasks[0]!.citationIds=["S6"];
  vi.stubGlobal("fetch",vi.fn(async()=>reply(body)));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("数据格式不正确");
  expect(screen.queryByRole("group",{name:"规划任务依赖图"})).not.toBeInTheDocument();
});

test("late plans cannot appear in another project",async()=>{
  let finish!:(response:Response)=>void;
  let requestSignal:AbortSignal|undefined;
  vi.stubGlobal("fetch",vi.fn((request:Request)=>{requestSignal=request.signal;return new Promise<Response>(resolve=>{finish=resolve;});}));
  const scope=new AbortController();
  const view=render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={scope.signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  await waitFor(()=>expect(requestSignal).toBeDefined());
  view.rerender(<ProjectPlanPreview projectId="00000000-0000-4000-8000-000000004002" csrfToken="csrf" signal={scope.signal}/>);
  expect(requestSignal?.aborted).toBe(true);
  await act(async()=>{finish(reply(result));});
  expect(screen.queryByText(result.plan.summary)).not.toBeInTheDocument();
});

test("insufficient evidence explains the gap without showing an invented graph",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>reply({...result,plan:{...result.plan,status:"insufficient_evidence",summary:"请先明确项目目标",stages:[],milestones:[],tasks:[],citationIds:[]}})));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  expect(await screen.findByText("请先明确项目目标")).toBeVisible();
  expect(screen.queryByRole("group",{name:"规划任务依赖图"})).not.toBeInTheDocument();
});
