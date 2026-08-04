import assert from "node:assert/strict";
import test from "node:test";

import { createCairnClient } from "../src/index.ts";

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
