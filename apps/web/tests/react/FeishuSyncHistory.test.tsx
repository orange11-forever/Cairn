import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import type { KnowledgeSource, KnowledgeSourceSync } from "../../src/api/knowledgeSources.ts";
import { FeishuSyncHistory, syncLabel } from "../../src/components/knowledge/FeishuSyncHistory.tsx";

const source = { id: "source", status: "configured" } as KnowledgeSource;
const sync = {
  id: "sync", status: "completed", resourceStatus: "queued",
  createdAt: "2026-09-29T00:00:00Z", trigger: "manual", failureCode: null,
  nextAttemptAt: null,
} as KnowledgeSourceSync;

test("completed snapshot waits for indexing before it is labeled searchable", () => {
  expect(syncLabel(sync)).toBe("快照已保存 · 等待索引");
  expect(syncLabel({ ...sync, resourceStatus: "processing" })).toBe("快照已保存 · 正在索引");
  expect(syncLabel({ ...sync, resourceStatus: "ready" })).toBe("可检索");
  expect(syncLabel({ ...sync, resourceStatus: "failed" })).toBe("快照已保存 · 索引失败");
});

test("soft-deleted local resource has specific usable guidance", () => {
  render(<FeishuSyncHistory source={source} items={[{
    ...sync, status: "failed", resourceStatus: null, failureCode: "feishu_resource_deleted",
  }]} active pollingStopped={false} hasNextPage={false} loadingMore={false}
    onRefresh={() => undefined} onLoadMore={() => undefined} onRetry={() => undefined} />);
  expect(screen.getByText(/项目资料已被删除/)).toBeInTheDocument();
  expect(screen.getByText(/登记为新来源/)).toBeInTheDocument();
});
