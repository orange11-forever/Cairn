import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ApiError } from "../../api/errors.ts";
import { createProject, type Project } from "../../api/projects.ts";
import { useSession } from "../../session/SessionContext.tsx";

export function ProjectCreator({csrfToken, signal, onCreated, onInspect, onCancel}: {
  csrfToken:string; signal:AbortSignal; onCreated(project:Project):Promise<void>;
  onInspect():Promise<Project[]>; onCancel():void;
}) {
  const id=useId();
  const nameInput=useRef<HTMLInputElement>(null);
  const mounted=useRef(true);
  const active=useRef<AbortController|null>(null);
  const {reportSessionError}=useSession();
  const [name,setName]=useState("");
  const [description,setDescription]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [created,setCreated]=useState<Project|null>(null);
  const [uncertain,setUncertain]=useState(false);
  const [inspected,setInspected]=useState<Project[]|null>(null);
  useEffect(()=>{mounted.current=true;nameInput.current?.focus();return()=>{mounted.current=false;active.current?.abort();};},[]);
  const current=()=>mounted.current&&!signal.aborted;

  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(active.current||created||uncertain||!name.trim())return;
    const controller=new AbortController();active.current=controller;
    setBusy(true);setError("");
    let saved:Project|null=null;
    try {
      saved=await createProject({body:{name:name.trim(),description:description.trim()||null},csrfToken,signal:AbortSignal.any([signal,controller.signal])});
      if(!current())return;
      setCreated(saved);
      await onCreated(saved);
    } catch(cause) {
      if(!current())return;
      reportSessionError(cause,signal);
      const message=cause instanceof Error?cause.message:"请求失败";
      if(saved) setError(`项目已创建，但列表刷新失败：${message}`);
      else {
        const unknown=cause instanceof ApiError&&(cause.kind==="network"||cause.kind==="timeout"||cause.kind==="contract"||(cause.status??0)>=500);
        setUncertain(unknown);
        setError(unknown?`未收到创建确认，请先核对项目列表，避免重复创建。${message}`:message);
      }
    } finally {
      active.current=null;
      if(current())setBusy(false);
    }
  }

  async function reread() {
    if(busy)return;
    setBusy(true);setError("");
    try {
      if(created) await onCreated(created);
      else {const items=await onInspect();if(current())setInspected(items);}
    } catch(cause) {
      if(current())setError(`${created?"项目已创建，但列表刷新失败：":"列表读取失败："}${cause instanceof Error?cause.message:"请重试"}`);
    } finally {if(current())setBusy(false);}
  }

  return <form className="project-creator" onSubmit={event=>void submit(event)} aria-busy={busy} aria-label="创建项目">
    <h2>创建项目</h2>
    <p>先为工作建立一个项目，再添加任务、阶段和知识资料。</p>
    <fieldset disabled={busy||created!==null||uncertain}>
      <label htmlFor={`${id}-name`}>项目名称</label>
      <input ref={nameInput} id={`${id}-name`} value={name} onChange={event=>setName(event.target.value)} required maxLength={160}/>
      <label htmlFor={`${id}-description`}>项目说明（选填）</label>
      <textarea id={`${id}-description`} value={description} onChange={event=>setDescription(event.target.value)} maxLength={4000} rows={3}/>
    </fieldset>
    {error&&<p role="alert">{error}</p>}
    {created?<p role="status">项目“{created.name}”已保存，重新读取列表即可进入。</p>:null}
    {uncertain && <p role="status">{inspected?"已读取全部可访问项目，请核对下方列表。创建结果仍未确认；不会仅凭同名项目判断创建成功，也不会再次发送此请求。":"创建结果尚未确认。核对列表后可明确关闭此表单查看项目；不会自动重发。"}</p>}
    {inspected && <ul className="project-inspected-list" aria-label="已读取的完整项目列表">{inspected.length===0?<li>当前没有可访问项目，创建结果仍未确认。</li>:inspected.map(project=><li key={project.id}><strong>{project.name}</strong><p>{project.description??"暂无项目说明"}</p><small>项目编号：{project.id}</small></li>)}</ul>}
    <div className="project-creator-actions">
      {created||uncertain?<button type="button" disabled={busy} onClick={()=>void reread()}>{busy?"正在读取":created?"重新读取项目":"核对项目列表"}</button>
        :<button type="submit" disabled={busy||!name.trim()}>{busy?"正在创建":"创建项目"}</button>}
      <button type="button" disabled={busy||created!==null} onClick={onCancel}>{uncertain?"关闭并查看项目列表":"取消"}</button>
    </div>
  </form>;
}
