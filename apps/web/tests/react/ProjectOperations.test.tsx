import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProjectOperations } from "../../src/components/projects/ProjectOperations.tsx";

vi.mock("../../src/session/SessionContext.tsx",()=>({useSessionErrorReporter:()=>vi.fn()}));
const pid="00000000-0000-4000-8000-000000004001",tid="00000000-0000-4000-8000-000000005001",oid="00000000-0000-4000-8000-000000006001";
const now="2026-10-25T04:00:00Z";
const intent="创建一个名为确认发布窗口的高优先级任务";
const preview={projectId:pid,intent,generatedAt:now,assistantName:"项目顾问",model:{id:"default",name:"测试模型",model:"synthetic",protocol:"openai-compatible"},canExecute:true,
  snapshot:{project:{id:pid,revision:1,name:"交付项目",description:null,createdAt:now,updatedAt:now},stages:[],milestones:[],tasks:[{id:tid,projectId:pid,revision:1,title:"已有任务",description:null,assigneeUserId:null,stageId:null,milestoneId:null,parentTaskId:null,status:"todo",priority:"medium",dueAt:null,acceptanceCriteria:null,createdAt:now,updatedAt:now}],dependencies:[]},
  suggestion:{status:"proposed",explanation:"创建确认发布窗口任务",action:{type:"create_task",title:"确认发布窗口",description:null,priority:"high",acceptanceCriteria:null,stageId:null,milestoneId:null}},
};
const saved={operationId:oid,projectId:pid,intent,action:preview.suggestion.action,explanation:preview.suggestion.explanation,generatedAt:now,appliedAt:now,result:{id:tid,title:"确认发布窗口"}};
const reply=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}});
const props=()=>({projectId:pid,ownerId:"owner",csrfToken:"csrf",signal:new AbortController().signal,onApplied:vi.fn(async()=>{}),onOpenTask:vi.fn()});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();sessionStorage.clear();});
async function generate(){fireEvent.change(screen.getByLabelText("你要执行的操作"),{target:{value:intent}});fireEvent.click(screen.getByRole("button",{name:"生成待确认操作"}));await screen.findByRole("group",{name:"确认助手操作"});}

test("shows concrete proposed changes and executes only after explicit confirmation",async()=>{
  const writes:unknown[]=[],requests:Request[]=[];
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{requests.push(request);if(request.url.endsWith("operation-preview"))return reply(preview);const body=await request.json();writes.push(body);return reply({...saved,operationId:body.operationId},201);}));
  const input=props(),open=vi.fn();render(<ProjectOperations {...input} onOpenTask={open}/>);
  expect(requests).toHaveLength(0);await generate();
  expect(screen.getByText("确认发布窗口")).toBeVisible();expect(screen.getByText("高")).toBeVisible();expect(writes).toHaveLength(0);
  expect(await requests[0]!.clone().json()).toEqual({intent});
  fireEvent.click(screen.getByRole("button",{name:"确认执行此操作"}));
  expect(await screen.findByText("操作已执行，真实项目内容已更新。")).toBeVisible();
  expect(writes).toHaveLength(1);expect(writes[0]).toMatchObject({confirmed:true,preview});expect(input.onApplied).toHaveBeenCalledOnce();
  expect(requests[1]!.headers.get("X-CSRF-Token")).toBe("csrf");
  fireEvent.click(screen.getByRole("button",{name:"打开真实任务"}));expect(open).toHaveBeenCalledWith(tid);
  expect(screen.queryByRole("button",{name:"确认执行此操作"})).not.toBeInTheDocument();
});

test("field update shows original and proposed values before confirmation",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>reply({...preview,suggestion:{status:"proposed",explanation:"调整已有任务标题",action:{type:"update_task",taskId:tid,field:"title",value:"确认生产窗口"}}})));
  render(<ProjectOperations {...props()}/>);await generate();
  expect(screen.getByText("原值：已有任务")).toBeVisible();expect(screen.getByText("新值：确认生产窗口")).toBeVisible();
});

test("unknown response locks new writes and recovers the committed operation by ID",async()=>{
  let operationId="",writes=0;
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{if(request.url.endsWith("operation-preview"))return reply(preview);if(request.method==="POST"){writes++;operationId=(await request.json()).operationId;throw new TypeError("connection lost");}expect(request.url).toContain(operationId);return reply({...saved,operationId});}));
  render(<ProjectOperations {...props()}/>);await generate();fireEvent.click(screen.getByRole("button",{name:"确认执行此操作"}));
  expect(await screen.findByText(/提交结果尚未确认/)).toBeVisible();expect(screen.getByRole("button",{name:"生成待确认操作"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"查询操作结果"}));expect(await screen.findByText("操作已执行，真实项目内容已更新。")).toBeVisible();expect(writes).toBe(1);
});

test("a missing result retries the exact same payload and identifier",async()=>{
  const writes:unknown[]=[];
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{if(request.url.endsWith("operation-preview"))return reply(preview);if(request.method==="GET")return reply({code:"not_found",message:"资源不存在",traceId:"missing"},404);const body=await request.json();writes.push(body);if(writes.length===1)throw new TypeError("lost");return reply({...saved,operationId:body.operationId},201);}));
  render(<ProjectOperations {...props()}/>);await generate();fireEvent.click(screen.getByRole("button",{name:"确认执行此操作"}));await screen.findByText(/提交结果尚未确认/);
  fireEvent.click(screen.getByRole("button",{name:"查询操作结果"}));await screen.findByText(/尚未找到已执行记录/);fireEvent.click(screen.getByRole("button",{name:"重新提交同一操作"}));
  await screen.findByText("操作已执行，真实项目内容已更新。");expect(writes).toHaveLength(2);expect(writes[1]).toEqual(writes[0]);
});

test("reload restores pending ID and queries before allowing another operation",async()=>{
  sessionStorage.setItem(`cairn.pending-operation:owner:${pid}`,oid);vi.stubGlobal("fetch",vi.fn(async()=>reply(saved)));
  render(<ProjectOperations {...props()}/>);expect(screen.getByRole("button",{name:"生成待确认操作"})).toBeDisabled();fireEvent.click(screen.getByRole("button",{name:"查询操作结果"}));
  await screen.findByText("操作已执行，真实项目内容已更新。");expect(sessionStorage.getItem(`cairn.pending-operation:owner:${pid}`)).toBeNull();
});

test("successful execution with failed refresh stays saved and cannot execute twice",async()=>{
  let writes=0;vi.stubGlobal("fetch",vi.fn(async(request:Request)=>{if(request.url.endsWith("operation-preview"))return reply(preview);writes++;return reply({...saved,operationId:(await request.json()).operationId},201);}));
  render(<ProjectOperations {...props()} onApplied={async()=>{throw new Error("refresh failed");}}/>);await generate();fireEvent.click(screen.getByRole("button",{name:"确认执行此操作"}));
  expect(await screen.findByText(/操作已执行，但项目刷新失败/)).toBeVisible();expect(screen.getByRole("button",{name:"打开真实任务"})).toBeVisible();fireEvent.click(screen.getByRole("button",{name:"重新读取项目"}));expect(writes).toBe(1);
});

test("read-only access and clarification suggestions do not offer an execution button",async()=>{
  let body:unknown={...preview,canExecute:false};vi.stubGlobal("fetch",vi.fn(async()=>reply(body)));render(<ProjectOperations {...props()}/>);await generate();
  expect(screen.getByText(/当前为只读访问/)).toBeVisible();expect(screen.queryByRole("button",{name:"确认执行此操作"})).not.toBeInTheDocument();
  body={...preview,suggestion:{status:"needs_clarification",explanation:"请明确目标任务",action:null}};fireEvent.click(screen.getByRole("button",{name:"生成待确认操作"}));expect(await screen.findByText("请明确目标任务")).toBeVisible();expect(screen.queryByRole("button",{name:"确认执行此操作"})).not.toBeInTheDocument();
});

test("storage refusal prevents submission and preserves preview",async()=>{
  vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw new DOMException("blocked","SecurityError");});const fetch=vi.fn(async()=>reply(preview));vi.stubGlobal("fetch",fetch);
  render(<ProjectOperations {...props()}/>);await generate();fireEvent.click(screen.getByRole("button",{name:"确认执行此操作"}));expect(await screen.findByRole("alert")).toHaveTextContent("无法保存操作编号");expect(fetch).toHaveBeenCalledOnce();
});

test("stale snapshot rejection shows the action and trace and allows regeneration",async()=>{
  vi.stubGlobal("fetch",vi.fn(async(request:Request)=>request.url.endsWith("operation-preview")?reply(preview):reply({code:"project_analysis_changed",message:"项目已变化",traceId:"operation-stale"},409)));
  render(<ProjectOperations {...props()}/>);await generate();fireEvent.click(screen.getByRole("button",{name:"确认执行此操作"}));expect(await screen.findByRole("alert")).toHaveTextContent("创建任务：项目已变化");expect(screen.getByText("请求编号：operation-stale")).toBeVisible();expect(screen.getByRole("button",{name:"生成待确认操作"})).toBeEnabled();
});

test("late suggestions are discarded when switching projects",async()=>{
  let finish!:(value:Response)=>void;let requestSignal:AbortSignal|undefined;vi.stubGlobal("fetch",vi.fn((request:Request)=>{requestSignal=request.signal;return new Promise<Response>(resolve=>{finish=resolve;});}));
  const input=props(),view=render(<ProjectOperations {...input}/>);fireEvent.change(screen.getByLabelText("你要执行的操作"),{target:{value:intent}});fireEvent.click(screen.getByRole("button",{name:"生成待确认操作"}));await waitFor(()=>expect(requestSignal).toBeDefined());view.rerender(<ProjectOperations {...input} projectId="00000000-0000-4000-8000-000000004002"/>);expect(requestSignal?.aborted).toBe(true);await act(async()=>{finish(reply(preview));});expect(screen.queryByText(preview.suggestion.explanation)).not.toBeInTheDocument();
});

test("removed dependency history identifies both task endpoints after the edge is gone",async()=>{
  const predecessor="00000000-0000-4000-8000-000000005002",dependency="00000000-0000-4000-8000-000000007001";
  vi.stubGlobal("fetch",vi.fn(async()=>reply({items:[{...saved,action:{type:"remove_dependency",taskId:tid,dependencyId:dependency},result:{taskId:tid,dependencyId:dependency,predecessorTaskId:predecessor,successorTaskId:tid,removed:true}}],nextCursor:null})));
  render(<ProjectOperations {...props()}/>);fireEvent.click(screen.getByRole("button",{name:"查看我的操作记录"}));
  expect(await screen.findByText(predecessor)).toBeVisible();expect(screen.getByText(tid)).toBeVisible();expect(screen.queryByText(dependency)).not.toBeInTheDocument();
});
