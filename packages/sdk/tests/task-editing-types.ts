import type { components } from "../src/generated/schema.d.ts";
type Patch = components["schemas"]["TaskUpdateRequest"];
const accepted: Patch[] = [
  { expectedRevision: 1, title: "Updated" },
  { expectedRevision: 1, description: null },
  { expectedRevision: 1, assigneeUserId: null },
  { expectedRevision: 1, priority: "high" },
  { expectedRevision: 1, dueAt: null },
  { expectedRevision: 1, acceptanceCriteria: null },
];
// @ts-expect-error Revision alone is not an editable patch.
const revisionOnly: Patch = { expectedRevision: 1 };
// @ts-expect-error Expected revision is mandatory.
const noRevision: Patch = { title: "Updated" };
// @ts-expect-error Title cannot be cleared.
const nullTitle: Patch = { expectedRevision: 1, title: null };
// @ts-expect-error Priority cannot be cleared.
const nullPriority: Patch = { expectedRevision: 1, priority: null };
// @ts-expect-error Status is outside task details editing.
const status: Patch = { expectedRevision: 1, status: "done" };
void [accepted, revisionOnly, noRevision, nullTitle, nullPriority, status];
