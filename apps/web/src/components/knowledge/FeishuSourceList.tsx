import type { KnowledgeSource } from "../../api/knowledgeSources.ts";
import { intervalLabel } from "../../lib/feishuDocument.ts";

const ACCESS: Record<KnowledgeSource["accessState"], string> = {
  unverified: "待验证", available: "可访问", access_denied: "无权限", not_found: "文档不存在",
};

export function FeishuSourceList({ items, selectedId, hasNextPage, loadingMore, onSelect, onLoadMore, onAdd }: {
  items: KnowledgeSource[];
  selectedId: string | null;
  hasNextPage: boolean;
  loadingMore: boolean;
  onSelect(sourceId: string): void;
  onLoadMore(): void;
  onAdd(): void;
}) {
  return <aside aria-label="飞书来源列表" className="feishu-source-list">
    <div className="feishu-section-heading"><h2>来源列表</h2><span>已加载 {items.length} 项</span></div>
    {items.length === 0 ? <div className="feishu-empty">
      <h3>还没有飞书来源</h3>
      <p>请先让部署管理员配置飞书凭证别名，并授予应用文档读取权限。</p>
      <button type="button" onClick={onAdd}>添加飞书文档</button>
    </div> : <ul>{items.map((source) => <li key={source.id}>
      <button type="button" aria-current={selectedId === source.id ? "true" : undefined}
        onClick={() => onSelect(source.id)}>
        <strong>{source.name}</strong>
        <span>{source.status === "disabled" ? "已停用" : "已启用"} · {ACCESS[source.accessState]}</span>
        <small>{intervalLabel(source.syncIntervalSeconds)}</small>
      </button>
    </li>)}</ul>}
    {hasNextPage ? <button type="button" className="feishu-load-more" disabled={loadingMore}
      onClick={onLoadMore}>{loadingMore ? "正在加载…" : "加载更多来源"}</button> : null}
  </aside>;
}
