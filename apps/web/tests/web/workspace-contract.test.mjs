import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const REPOSITORY_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");

test("Web tooling belongs to apps/web", async () => {
  const workspace = await readFile(join(REPOSITORY_ROOT, "pnpm-workspace.yaml"), "utf8");
  const root = JSON.parse(await readFile(join(REPOSITORY_ROOT, "package.json"), "utf8"));
  const web = JSON.parse(
    await readFile(join(REPOSITORY_ROOT, "apps/web/package.json"), "utf8"),
  );

  assert.match(workspace, /apps\/\*/);
  assert.match(workspace, /packages\/\*/);
  assert.deepEqual(root.dependencies ?? {}, {});
  assert.deepEqual(root.devDependencies ?? {}, {});
  assert.equal(web.scripts.test, "node scripts/run-tests.mjs");
  assert.equal(web.scripts.verify, "node scripts/run-verification.mjs");
  assert.match(web.dependencies["@tanstack/react-query"], /^5\./);
  assert.equal(web.dependencies["@cairn/contracts"], "workspace:*");
  assert.match(web.dependencies["react-router-dom"], /^7\./);

  for (const moved of ["apiError.ts", "conversations.ts", "primitives.ts", "users.ts"]) {
    await assert.rejects(
      readFile(join(REPOSITORY_ROOT, "apps/web/src/schemas", moved), "utf8"),
    );
  }

  const contracts = JSON.parse(
    await readFile(join(REPOSITORY_ROOT, "packages/contracts/package.json"), "utf8"),
  );
  assert.equal(contracts.name, "@cairn/contracts");
  assert.equal(contracts.exports["."].default, "./src/index.ts");
});
