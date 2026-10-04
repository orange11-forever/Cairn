import { useQuery } from '@tanstack/react-query';
import { Check, ChevronDown, FolderOpen } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchProject, type Project } from '../api/projects.ts';
import { projectKeys, useProjectsQuery } from '../queries/projects.ts';

export function ProjectSwitcher({ organizationId, projectId, sessionSignal }: {
  organizationId: string; projectId: string | null; sessionSignal: AbortSignal;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const navigate = useNavigate();
  const projects = useProjectsQuery(organizationId, sessionSignal, open);
  // Observe the already-authorized page title without starting another detail request.
  const current = useQuery<Project>({ queryKey: projectKeys.detail(organizationId, projectId ?? ''), queryFn: ({ signal }) => fetchProject({ projectId: projectId ?? '', signal: AbortSignal.any([signal, sessionSignal]) }), enabled: false });
  const items = projects.data?.pages.flatMap(page => page.items) ?? [];
  const currentName = current.data?.name ?? items.find(project => project.id === projectId)?.name ?? '选择项目';
  useEffect(() => {
    setOpen(false);
  }, [projectId]);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!container.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', escape); };
  }, [open]);
  return <div className='project-switcher' ref={container}>
    <button className='project-switcher-trigger' type='button' ref={trigger} aria-label={`切换项目：${currentName}`}
      aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(value => !value)}>
      <FolderOpen size={16} aria-hidden='true' /><span title={currentName}>{currentName}</span><ChevronDown size={16} aria-hidden='true' />
    </button>
    {open ? <section className='project-switcher-panel' id={panelId} aria-label='选择项目'>
      <div className='project-switcher-heading'><strong>切换项目</strong><span>你有权访问的项目</span></div>
      {projects.isPending || (projects.isFetching && !projects.isFetchingNextPage) ? <p role='status'>正在读取项目…</p> : <>
        {projects.isError ? <div><p role='alert'>{projects.error instanceof Error ? projects.error.message : '项目暂时无法加载'}</p>
          <button type='button' onClick={() => void projects.refetch()}>重新加载项目列表</button></div> : null}
        {!projects.isError && items.length === 0 ? <p>暂无可访问的项目。</p> : null}
        {!projects.isError ? <ul>{items.map(project => <li key={project.id}><button type='button' aria-current={project.id === projectId ? 'true' : undefined}
          onClick={() => { setOpen(false); navigate(`/projects/${encodeURIComponent(project.id)}/knowledge`); }}>
          <FolderOpen size={17} aria-hidden='true' /><span>{project.name}</span>{project.id === projectId ? <Check size={16} aria-hidden='true' /> : null}
        </button></li>)}</ul> : null}
        {projects.hasNextPage ? <button type='button' disabled={projects.isFetchingNextPage} onClick={() => void projects.fetchNextPage()}>
          {projects.isFetchingNextPage ? '正在加载更多项目' : '加载更多项目'}</button> : null}
      </>}
      <button type='button' className='project-switcher-all' onClick={() => { setOpen(false); navigate('/projects'); }}>查看项目与任务</button>
    </section> : null}
  </div>;
}
