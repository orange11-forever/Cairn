import { MessageSquare, Plus } from "lucide-react";
import { useProjectConversations } from "./ProjectConversationsContext.tsx";

export function ConversationHistory() {
  const state = useProjectConversations();
  if (state === null) return null;
  return <section className="workbench-conversations" aria-label="项目对话历史">
    <h2>{state.showAllHistory ? "全部历史对话" : `${state.assistant.data?.name ?? "当前助手"}的对话`}</h2>
    <label className="conversation-history-scope"><input type="checkbox" checked={state.showAllHistory} onChange={event => state.setShowAllHistory(event.target.checked)} /><span>全部历史（含旧版）</span></label>
    {state.projectError !== null ? <p role="alert">项目暂不可访问，历史对话已隐藏。</p> : <>
    <button type="button" className="conversation-new" onClick={() => state.selectConversation(null)}><Plus size={17} aria-hidden="true" />新建对话</button>
    {state.list.isPending ? <p role="status">正在读取对话…</p> : null}
    {state.list.isError ? <><p role="alert">对话列表暂时无法读取。</p><button type="button" onClick={() => void state.list.refetch()}>重新读取对话列表</button></> : null}
    <ul className="conversation-history-list">
      {state.entries.map(item => <li key={item.id}><button type="button" className="workbench-conversation" aria-current={item.id === state.selectedId ? "true" : undefined} onClick={() => state.selectConversation(item.id)}><MessageSquare size={17} aria-hidden="true" /><span>{item.title}<small>{item.revision - 1} 轮问答</small></span></button></li>)}
    </ul>
    {!state.list.isPending && state.entries.length === 0 ? <p className="conversation-empty">发送第一个问题后，对话会保存在这里。</p> : null}
    {state.list.hasNextPage ? <button type="button" disabled={state.list.isFetchingNextPage} onClick={() => void state.list.fetchNextPage()}>加载更多对话</button> : null}
    </>}
  </section>;
}
