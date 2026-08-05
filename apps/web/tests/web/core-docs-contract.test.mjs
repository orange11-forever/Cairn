import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repositoryRoot = new URL("../../../../", import.meta.url);

test("root documentation describes the real core development path", async () => {
  const readme = await readFile(new URL("README.md", repositoryRoot), "utf8");

  assert.match(readme, /pnpm infra:up/);
  assert.match(readme, /pnpm dev:core/);
  assert.match(readme, /pnpm verify:core/);
  assert.match(readme, /真实 PostgreSQL/);
  assert.doesNotMatch(readme, /真实鉴权.*仍未实现/);
});

test("API documentation records auth hardening and keeps deferred work explicit", async () => {
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assert.match(readme, /Bearer\/OIDC.*未实现/);
  assert.match(readme, /已实现.*PostgreSQL 登录限流/);
  assert.match(readme, /CAIRN_AUTH_RATE_LIMIT_SECRET/);
  assert.match(readme, /CAIRN_TRUSTED_PROXY_CIDRS/);
  assert.match(readme, /pnpm auth:cleanup/);
  assert.match(readme, /完整 RBAC\/ACL.*未实现/);
  assert.match(readme, /知识.*端点.*未实现/);
});
