import type { components } from "../src/generated/schema.d.ts";
type StageCreate = components["schemas"]["StageCreateRequest"];
type StagePatch = components["schemas"]["StageUpdateRequest"];
type MilestonePatch = components["schemas"]["MilestoneUpdateRequest"];
type TaskPatch = components["schemas"]["TaskUpdateRequest"];
const create: StageCreate = {
  name: "Design",
  position: 0,
  expectedProjectRevision: 1
};
const edit: StagePatch = {
  name: "Review",
  expectedRevision: 1,
  expectedProjectRevision: 2
};
const clear: MilestonePatch = {
  stageId: null,
  dueAt: null,
  description: null,
  acceptanceCriteria: null,
  expectedRevision: 1,
  expectedProjectRevision: 2
};
const group: TaskPatch = {
  stageId: null,
  milestoneId: null,
  expectedRevision: 1,
  expectedProjectRevision: 2
};
// @ts-expect-error Structure creation must protect the project revision.
const unsafeCreate: StageCreate = {
  name: "X",
  position: 0
};
// @ts-expect-error Structure PATCH needs an editable field.
const empty: StagePatch = {
  expectedRevision: 1,
  expectedProjectRevision: 2
};
// @ts-expect-error Grouping requires the project revision even beside ordinary edits.
const unsafeGrouping: TaskPatch = {
  expectedRevision: 1,
  title: "X",
  milestoneId: null
};
void [create, edit, clear, group, unsafeCreate, empty, unsafeGrouping];
// @ts-expect-error Clearing a milestone still requires a non-null project revision.
const nullMilestoneRevision: TaskPatch = {expectedRevision: 1, expectedProjectRevision: null, milestoneId: null};
// @ts-expect-error Clearing a stage still requires a non-null project revision.
const nullStageRevision: TaskPatch = {expectedRevision: 1, expectedProjectRevision: null, stageId: null};
// @ts-expect-error Ordinary fields cannot make a null grouping revision valid.
const nullMixedRevision: TaskPatch = {expectedRevision: 1, expectedProjectRevision: null, title: "Keep", milestoneId: null};
const ordinaryLegacyNull: TaskPatch = {expectedRevision: 1, expectedProjectRevision: null, title: "Keep"};
void [nullMilestoneRevision, nullStageRevision, nullMixedRevision, ordinaryLegacyNull];
const archiveStage: StagePatch = {archived: true, expectedRevision: 1, expectedProjectRevision: 2};
const restoreMilestone: MilestonePatch = {archived: false, expectedRevision: 1, expectedProjectRevision: 2};
// @ts-expect-error Lifecycle cannot mix ordinary fields.
const mixedLifecycle: StagePatch = {archived: true, name: "X", expectedRevision: 1, expectedProjectRevision: 2};
// @ts-expect-error archived must be a non-null strict boolean.
const nullLifecycle: MilestonePatch = {archived: null, expectedRevision: 1, expectedProjectRevision: 2};
// @ts-expect-error Creation cannot archive an object.
const archivedCreate: StageCreate = {archived: true, name: "X", position: 0, expectedProjectRevision: 1};
void [archiveStage, restoreMilestone, mixedLifecycle, nullLifecycle, archivedCreate];
