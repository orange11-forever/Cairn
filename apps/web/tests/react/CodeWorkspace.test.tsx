import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { SessionProvider } from '../../src/session/SessionContext.tsx';
import { CodeWorkspacePage } from '../../src/pages/CodeWorkspacePage.tsx';
const projectId='00000000-0000-4000-8000-000000004001';
const identity={user:{id:'00000000-0000-4000-8000-000000001001',email:'demo@cairn.dev',displayName:'用户'},organization:{id:'00000000-0000-4000-8000-000000002001',name:'Cairn',slug:'cairn'},membership:{id:'00000000-0000-4000-8000-000000003001',role:'owner' as const},csrfToken:'csrf'};
const project={id:projectId,name:'mikuOJ',description:'Online judge',revision:1,createdAt:'2026-10-31T00:00:00Z',updatedAt:'2026-10-31T00:00:00Z'};
const snapshot={branch:'master',head:'a'.repeat(40),digest:'b'.repeat(64),eligibleFiles:1,excludedFiles:1,truncated:false,paths:['src/main.py'],sources:[{id:'S1',path:'src/main.py',startLine:1,endLine:1,content:'print("entry")',truncated:false,redacted:false}]};
const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});
function mount(failure=false){
 vi.stubGlobal('chrome',{webview:{postMessage:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}});
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
  const request=input as Request;const path=new URL(request.url).pathname;
  if(path.endsWith('/architecture')&&request.method==='POST')return failure?json({code:'architecture_changed',message:'代码已变化，请刷新源码',traceId:'test'},409):json({generatedAt:'2026-10-31T03:00:00Z',assistantId:null,assistantName:'岑宁',assistantRevision:0,model:{id:'default',name:'测试模型',model:'test',protocol:'openai-compatible'},status:'answered',paragraphs:[{text:'技术栈与入口：Python 程序从 main.py 启动。',citationIds:['S1']}],snapshot});
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
 client.clear();
});
