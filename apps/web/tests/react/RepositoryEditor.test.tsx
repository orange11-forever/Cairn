import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { SessionProvider } from '../../src/session/SessionContext.tsx';
import { RepositoryEditorPanel } from '../../src/components/code/RepositoryEditorPanel.tsx';
vi.mock('../../src/components/code/MonacoEditor.tsx', () => ({ default: ({value,original,onChange}: {value:string;original?:string;onChange?:(v:string)=>void}) => original === undefined ? <textarea aria-label="代码编辑器" value={value} onChange={event => onChange?.(event.target.value)} /> : <div aria-label="差异"><pre>{original}</pre><pre>{value}</pre></div> }));
const identity={user:{id:'00000000-0000-4000-8000-000000001001',email:'demo@cairn.dev',displayName:'用户'},organization:{id:'00000000-0000-4000-8000-000000002001',name:'Cairn',slug:'cairn'},membership:{id:'00000000-0000-4000-8000-000000003001',role:'owner' as const},csrfToken:'csrf'};
const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});
function mount() {
 const files = new Map<string, {content:string;revision:string}>([['one',{content:'initial one',revision:'a'.repeat(64)}],['two',{content:'initial two',revision:'a'.repeat(64)}]]);
 let workspaceId='b'.repeat(64);
 let release: (()=>void) | undefined;
 let hold=false;
 const fetch=vi.fn(async(input:RequestInfo|URL)=>{
  const request=input as Request;const url=new URL(request.url);const path=url.pathname;const project=path.split('/')[5]!;const file=files.get(project)!;
  if(path.endsWith('/files'))return json({workspaceId,branch:'main',paths:['main.py']});
  if(path.endsWith('/changes'))return json({workspaceId,files:[]});
  if(path.endsWith('/diff'))return json({workspaceId,path:'main.py',original:'HEAD original',modified:file.content,revision:file.revision});
  if(path.endsWith('/file')&&request.method==='PUT') {
   const body=await request.json();
   if(hold)await new Promise<void>(resolve=>{release=resolve;});
   if(body.revision!==file.revision)return json({code:'workspace_file_conflict',message:'文件已被外部修改，草稿已保留',traceId:'test'},409);
   file.content=body.content;file.revision='c'.repeat(64);
  }
  return json({workspaceId,path:'main.py',...file});
 });
 vi.stubGlobal('fetch',fetch);
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
 function TestApp(){const [project,setProject]=useState('one');return <><button onClick={()=>setProject(project==='one'?'two':'one')}>切换项目</button><RepositoryEditorPanel key={project} projectId={project} localPath={'/repo/'+project} onConnection={()=>{}} /></>;}
 render(<MemoryRouter><QueryClientProvider client={client}><SessionProvider restoredIdentity={identity}><TestApp /></SessionProvider></QueryClientProvider></MemoryRouter>);
 return {files,fetch,client,hold:()=>{hold=true;},release:()=>release?.(),rebind:()=>{workspaceId='d'.repeat(64);}};
}
test('project switching retains dirty tabs and close requires an explicit discard',async()=>{
 const {client}=mount();await userEvent.click(await screen.findByRole('button',{name:'main.py'}));
 fireEvent.change(await screen.findByLabelText('代码编辑器'),{target:{value:'my draft'}});
 await userEvent.click(screen.getByRole('button',{name:'切换项目'}));await userEvent.click(await screen.findByRole('button',{name:'main.py'}));
 expect(await screen.findByLabelText('代码编辑器')).toHaveValue('initial two');
 await userEvent.click(screen.getByRole('button',{name:'切换项目'}));expect(await screen.findByLabelText('代码编辑器')).toHaveValue('my draft');
 await userEvent.click(screen.getByRole('button',{name:'关闭 main.py'}));expect(screen.getByRole('alert')).toHaveTextContent('未保存');
 await userEvent.click(screen.getByRole('button',{name:'继续编辑'}));expect(screen.getByLabelText('代码编辑器')).toHaveValue('my draft');
 client.clear();
});
test('conflict keeps draft and requires comparing disk before adopting the new revision',async()=>{
 const {files,client}=mount();await userEvent.click(await screen.findByRole('button',{name:'main.py'}));
 fireEvent.change(await screen.findByLabelText('代码编辑器'),{target:{value:'my draft'}});
 files.set('one',{content:'external',revision:'e'.repeat(64)});
 await userEvent.click(screen.getByRole('button',{name:'保存'}));expect(await screen.findByRole('alert')).toHaveTextContent('外部修改');
 expect(screen.getByLabelText('代码编辑器')).toHaveValue('my draft');
 await userEvent.click(screen.getByRole('button',{name:'对照磁盘版本'}));expect(await screen.findByLabelText('差异')).toHaveTextContent('external');
 await userEvent.click(screen.getByRole('button',{name:'采用磁盘基线，保留草稿'}));
 await userEvent.click(screen.getByRole('button',{name:'保存'}));
 await waitFor(()=>expect(files.get('one')!.content).toBe('my draft'));client.clear();
});
test('typing while save is pending retains the newer edits',async()=>{
 const fixture=mount();await userEvent.click(await screen.findByRole('button',{name:'main.py'}));
 fireEvent.change(await screen.findByLabelText('代码编辑器'),{target:{value:'first save'}});fixture.hold();
 await userEvent.click(screen.getByRole('button',{name:'保存'}));
 fireEvent.change(screen.getByLabelText('代码编辑器'),{target:{value:'newer draft'}});
 await act(async()=>fixture.release());
 await waitFor(()=>expect(screen.getByRole('button',{name:'保存'})).toBeEnabled());
 expect(screen.getByLabelText('代码编辑器')).toHaveValue('newer draft');expect(fixture.files.get('one')!.content).toBe('first save');fixture.client.clear();
});
test('branch or binding change disables saving an old draft without losing it',async()=>{
 const fixture=mount();await userEvent.click(await screen.findByRole('button',{name:'main.py'}));
 fireEvent.change(await screen.findByLabelText('代码编辑器'),{target:{value:'old repo draft'}});fixture.rebind();
 await userEvent.click(screen.getByRole('button',{name:'刷新文件与差异'}));
 expect(await screen.findByText(/此标签保留原草稿/)).toBeVisible();expect(screen.getByRole('button',{name:'保存'})).toBeDisabled();
 expect(screen.getByLabelText('代码编辑器')).toHaveValue('old repo draft');fixture.client.clear();
});
