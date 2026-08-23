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
  for (const createdAt of [
    "not-a-date",
    "2026-02-30T09:30:00Z",
    "2026-08-10",
    "2026-08-10T09:30:00",
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
