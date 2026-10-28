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
  retrievalMode: "keyword_fallback", citations: [], canApply: true,
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
afterEach(() => {vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear();});

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

const saved = {
  operationId: "00000000-0000-4000-8000-000000004010", projectId: pid,
  generatedAt: now, appliedAt: now, plan: result.plan, sources: [],
  stageIds: {P1:"00000000-0000-4000-8000-000000004011"},
  milestoneIds: {M1:"00000000-0000-4000-8000-000000004012"},
  taskIds: {T1:"00000000-0000-4000-8000-000000004013",T2:"00000000-0000-4000-8000-000000004014"},
};

test("edits a draft and creates only after explicit confirmation, then opens the real task",async()=>{
  const writes: unknown[]=[];
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{
    if(request.url.endsWith("plan-preview")) return reply(result);
    const body=await request.json(); writes.push(body);
    return reply({...saved, operationId:body.operationId, plan:body.preview.plan},201);
  }));
  const open=vi.fn();
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal} onOpenTask={open}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  await screen.findByText(result.plan.summary);
  fireEvent.click(screen.getByRole("button",{name:"调整规划"}));
  fireEvent.change(screen.getByLabelText("T1 任务名称"),{target:{value:"确认生产窗口"}});
  fireEvent.click(screen.getByRole("button",{name:"检查并应用规划"}));
  expect(screen.getByText(/新增 1 个阶段、1 个里程碑、2 个任务、1 条依赖/)).toBeVisible();
  expect(writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("button",{name:"确认创建"}));
  expect(await screen.findByText(/规划已应用/)).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({preview:{plan:{tasks:[{title:"确认生产窗口"},{title:"执行验收"}]}}});
  fireEvent.click(screen.getByRole("button",{name:"打开任务：确认生产窗口"}));
  expect(open).toHaveBeenCalledWith(saved.taskIds.T1);
  expect(screen.queryByRole("button",{name:"确认创建"})).not.toBeInTheDocument();
});

test("unknown response freezes the submitted draft and recovers by querying its operation",async()=>{
  let operationId="";
  let writes=0;
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{
    if(request.url.endsWith("plan-preview")) return reply(result);
    if(request.method==="POST") {writes++; operationId=(await request.json()).operationId; throw new TypeError("connection lost");}
    expect(request.url).toContain(operationId);
    return reply({...saved,operationId});
  }));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  await screen.findByText(result.plan.summary);
  fireEvent.click(screen.getByRole("button",{name:"检查并应用规划"}));
  fireEvent.click(screen.getByRole("button",{name:"确认创建"}));
  expect(await screen.findByText(/提交结果尚未确认/)).toBeVisible();
  expect(screen.getByRole("button",{name:"重新生成规划"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"查询提交结果"}));
  expect(await screen.findByText(/规划已应用/)).toBeVisible();
  expect(writes).toBe(1);
});

test("a refresh failure after creation keeps the saved result and cannot create again",async()=>{
  let writes=0;
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{
    if(request.url.endsWith("plan-preview")) return reply(result);
    writes++; return reply({...saved,operationId:(await request.json()).operationId},201);
  }));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal} onApplied={async()=>{throw new Error("refresh failed");}}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  await screen.findByText(result.plan.summary);
  fireEvent.click(screen.getByRole("button",{name:"检查并应用规划"}));
  fireEvent.click(screen.getByRole("button",{name:"确认创建"}));
  expect(await screen.findByText(/规划已应用，但项目刷新失败/)).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"重新读取项目"}));
  expect(writes).toBe(1);
});

test("read-only preview cannot offer application and saved plans can be retrieved after reload",async()=>{
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>request.url.endsWith("plan-preview") ? reply({...result,canApply:false}) : reply({items:[saved],nextCursor:null})));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  await screen.findByText(result.plan.summary);
  expect(screen.queryByRole("button",{name:"检查并应用规划"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"查看已确认规划"}));
  expect(await screen.findByRole("button",{name:"打开任务：确认窗口"})).toBeVisible();
});

test("blocked session storage keeps preview available and explains why confirmation is disabled",async()=>{
  vi.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw new DOMException("blocked","SecurityError");});
  vi.stubGlobal("fetch",vi.fn(async()=>reply(result)));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  expect(await screen.findByText(result.plan.summary)).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("会话存储不可用");
  expect(screen.getByRole("button",{name:"检查并应用规划"})).toBeDisabled();
});

test("storage cleanup failure after commit still displays the saved plan",async()=>{
  vi.spyOn(Storage.prototype,"removeItem").mockImplementation(()=>{throw new DOMException("blocked","SecurityError");});
  let writes=0;
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{
    if(request.url.endsWith("plan-preview")) return reply(result);
    writes++;return reply({...saved,operationId:(await request.json()).operationId},201);
  }));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  await screen.findByText(result.plan.summary);
  fireEvent.click(screen.getByRole("button",{name:"检查并应用规划"}));
  fireEvent.click(screen.getByRole("button",{name:"确认创建"}));
  expect(await screen.findByText(/规划已应用/)).toBeVisible();
  expect(screen.getByRole("button",{name:"打开任务：确认窗口"})).toBeVisible();
  expect(writes).toBe(1);
});

test("stale project rejection preserves the user's editable draft",async()=>{
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>request.url.endsWith("plan-preview") ? reply(result) : reply({code:"project_analysis_changed",message:"项目已变化，请重新生成",traceId:"plan-stale"},409)));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  await screen.findByText(result.plan.summary);
  fireEvent.click(screen.getByRole("button",{name:"调整规划"}));
  fireEvent.change(screen.getByLabelText("T1 任务名称"),{target:{value:"尚未保存的修改"}});
  fireEvent.click(screen.getByRole("button",{name:"检查并应用规划"}));
  fireEvent.click(screen.getByRole("button",{name:"确认创建"}));
  expect(await screen.findByText(/规划未应用，草稿已保留/)).toBeVisible();
  expect(screen.getByLabelText("T1 任务名称")).toHaveValue("尚未保存的修改");
  expect(screen.getByLabelText("T1 任务名称")).toBeEnabled();
  expect(screen.queryByRole("article",{name:"已确认规划"})).not.toBeInTheDocument();
});

test("reload restores only the operation identifier and queries the saved result",async()=>{
  sessionStorage.setItem(`cairn.pending-plan:owner:${pid}`,saved.operationId);
  vi.stubGlobal("fetch",vi.fn(async()=>reply(saved)));
  render(<ProjectPlanPreview projectId={pid} ownerId="owner" csrfToken="csrf" signal={new AbortController().signal}/>);
  expect(screen.getByText(/上次提交结果尚未确认/)).toBeVisible();
  expect(screen.getByRole("button",{name:"生成规划预览"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"查询提交结果"}));
  expect(await screen.findByRole("article",{name:"已确认规划"})).toBeVisible();
  expect(sessionStorage.getItem(`cairn.pending-plan:owner:${pid}`)).toBeNull();
});

test("an absent result can resend the exact submission without choosing a new operation",async()=>{
  const writes: unknown[]=[];
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{
    if(request.url.endsWith("plan-preview"))return reply(result);
    if(request.method==="GET")return reply({code:"not_found",message:"资源不存在",traceId:"missing"},404);
    const body=await request.json();writes.push(body);
    if(writes.length===1)throw new TypeError("lost request");
    return reply({...saved,operationId:body.operationId},201);
  }));
  render(<ProjectPlanPreview projectId={pid} csrfToken="csrf" signal={new AbortController().signal}/>);
  fireEvent.click(screen.getByRole("button",{name:"生成规划预览"}));
  await screen.findByText(result.plan.summary);
  fireEvent.click(screen.getByRole("button",{name:"检查并应用规划"}));
  fireEvent.click(screen.getByRole("button",{name:"确认创建"}));
  await screen.findByText(/提交结果尚未确认/);
  fireEvent.click(screen.getByRole("button",{name:"查询提交结果"}));
  fireEvent.click(await screen.findByRole("button",{name:"重新提交同一规划"}));
  expect(await screen.findByRole("article",{name:"已确认规划"})).toBeVisible();
  expect(writes).toHaveLength(2);
  expect(writes[0]).toEqual(writes[1]);
});
