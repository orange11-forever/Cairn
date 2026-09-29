import type { KnowledgeSource, KnowledgeSourceSync } from "../../api/knowledgeSources.ts";

const FAILURE: Record<string, string> = {
  feishu_access_denied: "飞书拒绝访问。请确认应用已获文档读取权限，并重新共享文档。",
  feishu_not_found: "飞书文档不存在。请核对文档 ID，或联系文档所有者。",
  feishu_auth_failed: "飞书凭证未通过验证。请联系部署管理员检查连接配置。",
  feishu_credentials_not_found: "找不到该凭证别名。请联系部署管理员检查连接配置。",
  feishu_credentials_invalid: "飞书凭证配置无效。请联系部署管理员检查连接配置。",
  feishu_credentials_unexpected: "飞书凭证暂时无法读取。请联系部署管理员检查连接配置。",
  feishu_resource_deleted: "该项目资料已被删除，同步不能恢复。若仍需内容，请在飞书复制文档，再把新文档登记为新来源。",
  feishu_document_changed: "读取时文档发生变化。请稍后重新同步。",
  feishu_rate_limited: "飞书请求过于频繁。请等待后重新同步。",
  feishu_unavailable: "飞书暂时不可用。请稍后重新同步。",
  feishu_response_too_large: "文档超过读取大小限制。请缩小文档后重新同步。",
  feishu_invalid_response: "飞书返回的数据无法读取。请稍后重试或联系管理员。",
  feishu_redirect_rejected: "飞书请求发生跳转，读取已停止。请联系管理员。",
  feishu_request_rejected: "飞书拒绝请求。请检查文档权限，或联系管理员。",
  feishu_unexpected: "同步暂时失败。请稍后重试或联系管理员。",
};

function displayTime(value: string | null): string {
  return value === null ? "尚无" : new Date(value).toLocaleString("zh-CN");
}

export function syncLabel(sync: KnowledgeSourceSync): string {
  if (sync.status === "queued") return "等待同步";
  if (sync.status === "running") return "正在同步";
  if (sync.status === "failed") return "同步失败";
  if (sync.resourceStatus === "queued") return "快照已保存 · 等待索引";
  if (sync.resourceStatus === "processing") return "快照已保存 · 正在索引";
  if (sync.resourceStatus === "ready") return "可检索";
  if (sync.resourceStatus === "failed") return "快照已保存 · 索引失败";
  return "快照已保存";
}

export function FeishuSyncHistory({ source, items, active, pollingStopped, hasNextPage, loadingMore,
  onRefresh, onLoadMore, onRetry }: {
  source: KnowledgeSource;
  items: KnowledgeSourceSync[];
  active: boolean;
  pollingStopped: boolean;
  hasNextPage: boolean;
  loadingMore: boolean;
  onRefresh(): void;
  onLoadMore(): void;
  onRetry(): void;
}) {
  return <section className="feishu-sync-history" aria-labelledby="feishu-sync-title">
    <div className="feishu-section-heading">
      <h2 id="feishu-sync-title">同步记录</h2>
      <button type="button" onClick={onRefresh}>刷新记录</button>
    </div>
    {pollingStopped ? <p role="status">自动检查已暂停。可手动刷新查看最新状态。</p> : null}
    {items.length === 0 ? <p className="feishu-muted">尚无同步记录。登记后可手动同步。</p> : <ol>
      {items.map((sync) => <li key={sync.id}>
        <div><strong>{syncLabel(sync)}</strong><span>{sync.trigger === "manual" ? "手动" : "定时"}</span></div>
        <time dateTime={sync.createdAt}>{displayTime(sync.createdAt)}</time>
        {sync.status === "failed" ? <p>{FAILURE[sync.failureCode ?? ""] ??
          "同步未完成。若对应项目资料已被删除，同步不会自动恢复，请联系项目管理员处理。"}</p> : null}
        {sync.resourceStatus === "failed" ? <p>索引失败。请联系项目管理员检查资料处理状态。</p> : null}
        {sync.nextAttemptAt ? <p>系统预计重试：{displayTime(sync.nextAttemptAt)}</p> : null}
      </li>)}
    </ol>}
    {hasNextPage ? <button type="button" disabled={loadingMore} onClick={onLoadMore}>
      {loadingMore ? "正在加载…" : "加载更多记录"}</button> : null}
    {source.status === "configured" && items[0]?.status === "failed" ?
      <button type="button" disabled={!active} onClick={onRetry}>手动重试同步</button> : null}
  </section>;
}
