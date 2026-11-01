import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { SessionProvider } from '../../src/session/SessionContext.tsx';
import { CodeWorkspacePage } from '../../src/pages/CodeWorkspacePage.tsx';
const projectId='00000000-0000-4000-8000-000000004001';
const identity={user:{id:'00000000-0000-4000-8000-000000001001',email:'demo@cairn.dev',displayName:'用户'},organization:{id:'00000000-0000-4000-8000-000000002001',name:'Cairn',slug:'cairn'},membership:{id:'00000000-0000-4000-8000-000000003001',role:'owner' as const},csrfToken:'csrf'};
const project={id:projectId,name:'mikuOJ',description:'Online judge',revision:1,createdAt:'2026-10-31T00:00:00Z',updatedAt:'2026-10-31T00:00:00Z'};
const snapshot={branch:'master',head:'a'.repeat(40),digest:'b'.repeat(64),eligibleFiles:1,excludedFiles:1,truncated:false,paths:['src/main.py'],sources:[{id:'S1',path:'src/main.py',startLine:1,endLine:1,content:'print("entry")',truncated:false,redacted:false}]};
const graph={nodes:[{id:'entry',label:'程序入口',description:'启动 Python 程序',citationIds:['S1']},{id:'console',label:'控制台',description:'输出消息',citationIds:['S1']}],edges:[{source:'entry',target:'console',label:'输出启动消息',basis:'direct',citationIds:['S1']},{source:'console',target:'entry',label:'可能返回状态',basis:'inferred',citationIds:['S1']}]};
const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});
function mount(failure=false){
 vi.stubGlobal('chrome',{webview:{postMessage:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}});
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
  const request=input as Request;const path=new URL(request.url).pathname;
  if(path.endsWith('/architecture')&&request.method==='POST')return failure?json({code:'architecture_changed',message:'代码已变化，请刷新源码',traceId:'test'},409):json({generatedAt:'2026-10-31T03:00:00Z',assistantId:null,assistantName:'岑宁',assistantRevision:0,model:{id:'default',name:'测试模型',model:'test',protocol:'openai-compatible'},status:'answered',paragraphs:[{text:'技术栈与入口：Python 程序从 main.py 启动。',citationIds:['S1']}],graph,snapshot});
  if(path.endsWith('/files'))return json({workspaceId:'a'.repeat(64),branch:'main',paths:[]});
  if(path.endsWith('/changes'))return json({workspaceId:'a'.repeat(64),files:[]});
  if(path.endsWith('/architecture'))return json(snapshot);
  if(path.endsWith('/assistant-settings'))return json({id:null,name:'岑宁',instructions:'',enabledSkillIds:[],revision:0,modelId:null,avatarDataUrl:null});
  if(path.endsWith('/answer-model'))return json({configured:true,model:'test',protocol:'openai-compatible',defaultModelId:'default',models:[{id:'default',name:'测试模型',model:'test',protocol:'openai-compatible'}]});
  if(path.endsWith('/repository'))return json({binding:{localPath:'D:\\code\\mikuOJ',branch:'master',repository:null,account:null},gitAvailable:true,repositoryStatus:'local',message:null});
  return json(project);
 }));
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
 render(<MemoryRouter initialEntries={[`/projects/${projectId}/code`]}><QueryClientProvider client={client}><SessionProvider restoredIdentity={identity}><Routes><Route path='/projects/:projectId/code' element={<CodeWorkspacePage/>}/></Routes></SessionProvider></QueryClientProvider></MemoryRouter>);
 return client;
}
test('code workspace explains analysis scope and reveals cited source lines',async()=>{
 const client=mount();
 await userEvent.click(await screen.findByRole('tab',{name:'架构解析'}));
 expect(await screen.findByRole('heading',{name:'mikuOJ'})).toBeVisible();
 await userEvent.click(await screen.findByRole('button',{name:'解析项目架构'}));
 expect(await screen.findByText(/Python 程序从 main.py 启动/)).toBeVisible();
 await userEvent.click(screen.getByRole('button',{name:'查看引用 S1：src/main.py'}));
 expect(screen.getByText('print("entry")')).toBeVisible();
 expect(screen.getAllByText(/测试模型/).length).toBeGreaterThan(0);
 client.clear();
});
test('source changes show a recoverable error without stale architecture success',async()=>{
 const client=mount(true);
 await userEvent.click(await screen.findByRole('tab',{name:'架构解析'}));
 await userEvent.click(await screen.findByRole('button',{name:'解析项目架构'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('代码已变化');
 expect(screen.queryByText(/Python 程序从 main.py 启动/)).not.toBeInTheDocument();
 client.clear();
});

test('unlinking the repository hides the old architecture report and source',async()=>{
 const client=mount();
 await userEvent.click(await screen.findByRole('tab',{name:'架构解析'}));
 await userEvent.click(await screen.findByRole('button',{name:'解析项目架构'}));
 expect(await screen.findByText(/Python 程序从 main.py 启动/)).toBeVisible();
 await userEvent.click(screen.getByRole('button',{name:'查看引用 S1：src/main.py'}));
 const {act}=await import('@testing-library/react');
 await act(async()=>{client.setQueryData(['desktop-workspace',1,projectId],{binding:null,gitAvailable:true,repositoryStatus:'local',message:null});});
 await waitFor(()=>expect(screen.queryByText(/Python 程序从 main.py 启动/)).not.toBeInTheDocument());
 expect(screen.queryByText('print("entry")')).not.toBeInTheDocument();
 client.clear();
});

test('changed source digest after editing hides the stale architecture report',async()=>{
 const client=mount();
 await userEvent.click(await screen.findByRole('tab',{name:'架构解析'}));
 await userEvent.click(await screen.findByRole('button',{name:'解析项目架构'}));
 expect(await screen.findByText(/Python 程序从 main.py 启动/)).toBeVisible();
 const {act}=await import('@testing-library/react');
 await act(async()=>{client.setQueryData(['code-sources',1,projectId,'D:\\code\\mikuOJ'],{...snapshot,digest:'c'.repeat(64)});});
 await waitFor(()=>expect(screen.queryByText(/Python 程序从 main.py 启动/)).not.toBeInTheDocument());
 expect(screen.queryByRole('region',{name:'源码架构节点图'})).not.toBeInTheDocument();
 client.clear();
});

test('architecture nodes and cyclic relationships expose cited evidence with keyboard controls',async()=>{
 const client=mount();
 await userEvent.click(await screen.findByRole('tab',{name:'架构解析'}));
 await userEvent.click(await screen.findByRole('button',{name:'解析项目架构'}));
 const diagram=await screen.findByRole('region',{name:'源码架构节点图'});
 const entry=within(diagram).getByRole('button',{name:'查看模块：程序入口'});
 entry.focus(); await userEvent.keyboard('{Enter}');
 expect(within(diagram).getByText('启动 Python 程序')).toBeVisible();
 await userEvent.click(within(diagram).getByRole('button',{name:'查看节点依据 S1：src/main.py'}));
 expect(screen.getByRole('region',{name:'源码引用'})).toHaveTextContent('print("entry")');
 const edge=within(diagram).getByRole('button',{name:'查看关系：控制台 → 程序入口，可能返回状态'});
 edge.focus(); await userEvent.keyboard(' ');
 const details=within(diagram).getByRole('region',{name:'所选架构关系'});
 expect(details).toHaveTextContent('Agent 推断');
 await userEvent.click(within(details).getByRole('button',{name:'查看关系依据 S1：src/main.py'}));
 expect(screen.getByRole('region',{name:'源码引用'})).toHaveTextContent('print("entry")');
 await userEvent.click(within(diagram).getByRole('button',{name:'放大架构图'}));
 expect(within(diagram).getByRole('button',{name:'重置架构图缩放'})).toHaveTextContent('125%');
 client.clear();
});

test('changing the selected agent invalidates its architecture graph',async()=>{
 const client=mount();
 await userEvent.click(await screen.findByRole('tab',{name:'架构解析'}));
 await userEvent.click(await screen.findByRole('button',{name:'解析项目架构'}));
 expect(await screen.findByRole('region',{name:'源码架构节点图'})).toBeVisible();
 const {act}=await import('@testing-library/react');
 await act(async()=>{client.setQueryData(['code-assistant',1,projectId],{id:null,name:'另一个配置',instructions:'',enabledSkillIds:[],revision:1,modelId:null,avatarDataUrl:null});});
 await waitFor(()=>expect(screen.queryByRole('region',{name:'源码架构节点图'})).not.toBeInTheDocument());
 expect(screen.queryByText(/Python 程序从 main.py 启动/)).not.toBeInTheDocument();
 client.clear();
});
