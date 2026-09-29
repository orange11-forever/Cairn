import type { components } from "../src/generated/schema.d.ts";

type Patch = components["schemas"]["FeishuSourcePatchRequest"];

const rename: Patch = { name: "Renamed" };
const disable: Patch = { status: "disabled" };
const pause: Patch = { syncIntervalSeconds: null };
const credential: Patch = { credentialRef: "team", accessPolicy: "project_members" };
const restore: Patch = { status: "configured", accessPolicy: "project_members" };
void [rename, disable, pause, credential, restore];

// @ts-expect-error At least one update field is required.
const empty: Patch = {};
// @ts-expect-error Sharing confirmation alone does not update a source.
const sharingOnly: Patch = { accessPolicy: "project_members" };
// @ts-expect-error Only syncIntervalSeconds accepts explicit null.
const nullName: Patch = { name: null };
// @ts-expect-error Credential replacement requires sharing confirmation.
const unconfirmedCredential: Patch = { credentialRef: "team" };
// @ts-expect-error Source restore requires sharing confirmation.
const unconfirmedRestore: Patch = { status: "configured" };
// @ts-expect-error A rename does not waive confirmation for a credential change.
const renamedUnconfirmedCredential: Patch = { name: "Renamed", credentialRef: "team" };
// @ts-expect-error A period edit does not waive confirmation for restore.
const periodUnconfirmedRestore: Patch = { syncIntervalSeconds: 300, status: "configured" };
void [empty, sharingOnly, nullName, unconfirmedCredential, unconfirmedRestore,
  renamedUnconfirmedCredential, periodUnconfirmedRestore];
