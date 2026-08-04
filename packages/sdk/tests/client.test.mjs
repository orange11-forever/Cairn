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
