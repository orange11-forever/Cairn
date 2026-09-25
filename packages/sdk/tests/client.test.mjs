import assert from "node:assert/strict";
import test from "node:test";

import { createCairnClient, matchesComponentSchema } from "../src/index.ts";

test("SDK uses credentialed fetch and the configured base URL", async () => {
  const calls = [];
  const identityFixture = {
    user: {
      id: "00000000-0000-4000-8000-000000001001",
      email: "demo@cairn.dev",
      displayName: "演示用户",
    },
    organization: {
      id: "00000000-0000-4000-8000-000000002001",
      slug: "cairn-demo",
      name: "Cairn Demo",
    },
    membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
    csrfToken: "csrf-test-token",
  };
  const client = createCairnClient({
    baseUrl: "http://identity.test",
    fetch: async (request) => {
      calls.push(request);
      return Response.json(identityFixture);
    },
  });

  await client.GET("/api/v1/session");

  assert.equal(calls[0].credentials, "include");
  assert.equal(new URL(calls[0].url).origin, "http://identity.test");
});

test("SDK validates identity responses from generated OpenAPI component schemas", () => {
  const valid = {
    user: {
      id: "00000000-0000-4000-8000-000000001001",
      email: "demo@cairn.dev",
      displayName: "演示用户",
    },
    organization: {
      id: "00000000-0000-4000-8000-000000002001",
      slug: "cairn-demo",
      name: "Cairn Demo",
    },
    membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
    csrfToken: "csrf-test-token",
  };

  assert.equal(matchesComponentSchema("IdentityContextResponse", valid), true);
  assert.equal(matchesComponentSchema("IdentityContextResponse", { ...valid, user: null }), false);
  assert.equal(
    matchesComponentSchema("IdentityContextResponse", {
      ...valid,
      organization: { ...valid.organization, id: "not-a-uuid" },
    }),
    false,
  );
});

test("SDK validates OpenAPI date-time formats before consumers parse them", () => {
  const membership = {
    id: "00000000-0000-4000-8000-000000003001",
    userId: "00000000-0000-4000-8000-000000001001",
    email: "member@example.com",
    displayName: "Member",
    role: "member",
    createdAt: "2026-08-10T09:30:00Z",
  };

  assert.equal(matchesComponentSchema("MembershipDetailResponse", membership), true);
  assert.equal(
    matchesComponentSchema("MembershipDetailResponse", {
      ...membership,
      createdAt: "2024-02-29T23:59:59.123456+08:00",
    }),
    true,
  );
  assert.equal(
    matchesComponentSchema("MembershipDetailResponse", {
      ...membership,
      createdAt: "1990-12-31T23:59:60Z",
    }),
    true,
  );
  assert.equal(
    matchesComponentSchema("MembershipDetailResponse", {
      ...membership,
      createdAt: "1991-01-01T00:59:60+01:00",
    }),
    true,
  );
  for (const createdAt of [
    "not-a-date",
    "2026-02-30T09:30:00Z",
    "2026-08-10",
    "2026-08-10T09:30:00",
    "2026-08-10T09:30:60Z",
    "2026-08-31T23:58:60Z",
    "1990-12-31T23:59:60+01:00",
  ]) {
    assert.equal(
      matchesComponentSchema("MembershipDetailResponse", { ...membership, createdAt }),
      false,
      createdAt,
    );
  }
});

test("SDK validates generated membership and ACL response schemas", () => {
  const membershipFixture = {
    id: "00000000-0000-4000-8000-000000003001",
    userId: "00000000-0000-4000-8000-000000001001",
    email: "member@example.com",
    displayName: "Member",
    role: "member",
    createdAt: "2026-08-10T09:30:00Z",
  };
  assert.equal(matchesComponentSchema("MembershipDetailResponse", membershipFixture), true);
  assert.equal(
    matchesComponentSchema("MembershipDetailResponse", {
      ...membershipFixture,
      id: "not-a-uuid",
    }),
    false,
  );
  assert.equal(
    matchesComponentSchema("MembershipDetailResponse", {
      ...membershipFixture,
      role: "operator",
    }),
    false,
  );

  const aclFixture = {
    id: "00000000-0000-4000-8000-000000006001",
    resourceType: "project",
    resourceId: "00000000-0000-4000-8000-000000004001",
    principalType: "user",
    principalId: "00000000-0000-4000-8000-000000001001",
    permission: "manage",
    grantedByType: "user",
    grantedById: "00000000-0000-4000-8000-000000001001",
    grantedAt: "2026-08-10T09:30:00Z",
  };
  assert.equal(matchesComponentSchema("AclEntryResponse", aclFixture), true);
  assert.equal(
    matchesComponentSchema("AclEntryResponse", { ...aclFixture, permission: "deny" }),
    false,
  );
  assert.equal(
    matchesComponentSchema("AclEntryResponse", { ...aclFixture, resourceId: "not-a-uuid" }),
    false,
  );
});

test("SDK validates generated knowledge source responses", () => {
  const source = {
    id: "00000000-0000-4000-8000-000000007001",
    projectId: "00000000-0000-4000-8000-000000004001",
    provider: "feishu",
    name: "Engineering handbook",
    documentId: "Doc123",
    credentialRef: "engineering_feishu",
    accessPolicy: "project_members",
    status: "configured",
    createdAt: "2026-09-19T07:30:00Z",
    updatedAt: "2026-09-19T07:30:00Z",
    disabledAt: null,
  };

  assert.equal(matchesComponentSchema("KnowledgeSourceResponse", source), true);
  assert.equal(
    matchesComponentSchema("KnowledgeSourceResponse", { ...source, accessPolicy: "private" }),
    false,
  );
  const { credentialRef: _missingCredentialRef, ...missingCredentialRef } = source;
  assert.equal(matchesComponentSchema("KnowledgeSourceResponse", missingCredentialRef), false);

  const page = { items: [source], nextCursor: null };
  assert.equal(matchesComponentSchema("KnowledgeSourcePage", page), true);
  assert.equal(matchesComponentSchema("KnowledgeSourcePage", { items: [source] }), false);
  assert.equal(
    matchesComponentSchema("KnowledgeSourcePage", {
      ...page,
      items: [{ ...source, status: "syncing" }],
    }),
    false,
  );
});

test("SDK validates strict Feishu source registration requests", () => {
  const request = {
    name: "Engineering handbook",
    documentId: "Doc123",
    credentialRef: "engineering_feishu",
    accessPolicy: "project_members",
  };

  assert.equal(matchesComponentSchema("FeishuSourceCreateRequest", request), true);
  const { accessPolicy: _missingPolicy, ...missingPolicy } = request;
  assert.equal(matchesComponentSchema("FeishuSourceCreateRequest", missingPolicy), false);
  assert.equal(
    matchesComponentSchema("FeishuSourceCreateRequest", { ...request, orgId: "forged" }),
    false,
  );
});

test("SDK sends credentialed Feishu source registration with CSRF and JSON body", async () => {
  const calls = [];
  const client = createCairnClient({
    baseUrl: "https://api.cairn.test",
    fetch: async (request) => {
      calls.push(request);
      return Response.json({}, { status: 201 });
    },
  });
  const projectId = "00000000-0000-4000-8000-000000004001";
  const body = {
    name: "Engineering handbook",
    documentId: "Doc123",
    credentialRef: "engineering_feishu",
    accessPolicy: "project_members",
  };

  await client.POST("/api/v1/projects/{project_id}/knowledge/sources/feishu", {
    params: { path: { project_id: projectId } },
    headers: { "X-CSRF-Token": "csrf-source-token" },
    body,
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].credentials, "include");
  assert.equal(
    calls[0].url,
    `https://api.cairn.test/api/v1/projects/${projectId}/knowledge/sources/feishu`,
  );
  assert.equal(calls[0].headers.get("X-CSRF-Token"), "csrf-source-token");
  assert.deepEqual(await calls[0].json(), body);
});

test("SDK validates sync lifecycle payloads and strict empty queue requests", () => {
  const queued = {
    id: "00000000-0000-4000-8000-000000008001",
    projectId: "00000000-0000-4000-8000-000000004001",
    sourceId: "00000000-0000-4000-8000-000000007001",
    status: "queued", attempt: 0, createdAt: "2026-09-25T08:00:00Z",
    completedAt: null, errorCode: null, resourceId: null, resourceVersionId: null,
  };
  assert.equal(matchesComponentSchema("KnowledgeSourceSyncCreateRequest", {}), true);
  for (const value of [null, [], { documentId: "forged" }, { credentialRef: "forged" }]) {
    assert.equal(matchesComponentSchema("KnowledgeSourceSyncCreateRequest", value), false);
  }
  for (const status of ["queued", "running", "completed", "failed"]) {
    assert.equal(matchesComponentSchema("KnowledgeSourceSyncResponse", { ...queued, status }), true);
  }
  assert.equal(matchesComponentSchema("KnowledgeSourceSyncResponse", {
    ...queued, status: "completed", attempt: 2, completedAt: "2026-09-25T08:01:00Z",
    resourceId: "00000000-0000-4000-8000-000000009001",
    resourceVersionId: "00000000-0000-4000-8000-000000009002",
  }), true);
  for (const [key, value] of [["status", "ready"], ["attempt", "1"], ["sourceId", "invalid"],
    ["resourceVersionId", "invalid"], ["createdAt", "invalid"], ["completedAt", "invalid"]]) {
    assert.equal(matchesComponentSchema("KnowledgeSourceSyncResponse", { ...queued, [key]: value }), false);
  }
  for (const key of Object.keys(queued)) {
    const partial = { ...queued };
    delete partial[key];
    assert.equal(matchesComponentSchema("KnowledgeSourceSyncResponse", partial), false, key);
  }
});

test("SDK queues and polls sync with exact routes, credentials, CSRF and empty JSON", async () => {
  const calls = [];
  const client = createCairnClient({
    baseUrl: "https://api.cairn.test",
    fetch: async (request) => {
      calls.push(request);
      return Response.json({}, { status: request.method === "POST" ? 202 : 200 });
    },
  });
  const path = { project_id: "00000000-0000-4000-8000-000000004001",
    source_id: "00000000-0000-4000-8000-000000007001" };
  const sync_id = "00000000-0000-4000-8000-000000008001";
  await client.POST("/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs", {
    params: { path }, headers: { "X-CSRF-Token": "csrf-sync-token" }, body: {},
  });
  await client.GET("/api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs/{sync_id}", {
    params: { path: { ...path, sync_id } },
  });
  assert.equal(calls.length, 2);
  const base = `https://api.cairn.test/api/v1/projects/${path.project_id}/knowledge/sources/${path.source_id}/syncs`;
  assert.equal(calls[0].url, base);
  assert.equal(calls[1].url, `${base}/${sync_id}`);
  assert.deepEqual(calls.map((request) => request.method), ["POST", "GET"]);
  assert.equal(calls[0].headers.get("X-CSRF-Token"), "csrf-sync-token");
  assert.equal(calls[0].headers.get("Content-Type"), "application/json");
  assert.deepEqual(await calls[0].json(), {});
  assert.equal(calls[1].body, null);
  assert.ok(calls.every((request) => request.credentials === "include"));
});
