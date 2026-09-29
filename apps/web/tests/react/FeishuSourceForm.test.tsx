import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import type { KnowledgeSource } from "../../src/api/knowledgeSources.ts";
import { FeishuSourceForm } from "../../src/components/knowledge/FeishuSourceForm.tsx";

const source: KnowledgeSource = {
  id: "00000000-0000-4000-8000-000000011001",
  projectId: "00000000-0000-4000-8000-000000004001",
  provider: "feishu",
  name: "团队手册",
  documentId: "Doc123",
  credentialRef: "team_feishu",
  accessPolicy: "project_members",
  status: "configured",
  accessState: "available",
  syncIntervalSeconds: null,
  nextSyncAt: null,
  lastCheckedAt: null,
  lastSuccessAt: null,
  lastErrorCode: null,
  disabledAt: null,
  createdAt: "2026-09-29T00:00:00Z",
  updatedAt: "2026-09-29T00:00:00Z",
};

test.each([
  ["rename", { name: "新团队手册" }, { name: "新团队手册" }],
  ["period", { period: "900" }, { syncIntervalSeconds: 900 }],
  ["credential with rename and period", { name: "新团队手册", credential: "new_team", period: "900" },
    { name: "新团队手册", credentialRef: "new_team", syncIntervalSeconds: 900, accessPolicy: "project_members" }],
] as const)("edit emits a valid %s PATCH body", (_label, changes, expected) => {
  const onUpdate = vi.fn();
  render(<FeishuSourceForm source={source} pending={false} error={null}
    onCancel={vi.fn()} onCreate={vi.fn()} onUpdate={onUpdate} />);
  if ("name" in changes) fireEvent.change(screen.getByLabelText("来源名称"), { target: { value: changes.name } });
  if ("credential" in changes) {
    fireEvent.change(screen.getByLabelText("凭证别名"), { target: { value: changes.credential } });
    fireEvent.click(screen.getByRole("checkbox", { name: /我确认将此文档共享/ }));
  }
  if ("period" in changes) fireEvent.change(screen.getByLabelText("同步周期"), { target: { value: changes.period } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  expect(onUpdate).toHaveBeenCalledExactlyOnceWith(expected);
});
