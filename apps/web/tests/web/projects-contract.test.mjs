import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const REPOSITORY_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");

test("the authenticated project route is registered inside the session boundary", async () => {
  const routes = await readFile(
    join(REPOSITORY_ROOT, "apps/web/src/app/AppRoutes.tsx"),
    "utf8",
  );

  assert.match(routes, /<Route path="\/projects" element={<ProjectsPage \/>} \/>/);
  assert.match(routes, /<Route element={<RequireSession \/>}>[\s\S]*path="\/projects"/);
});

test("the project data boundary uses the generated SDK against the identity API", async () => {
  const api = await readFile(
    join(REPOSITORY_ROOT, "apps/web/src/api/projects.ts"),
    "utf8",
  );

  assert.match(api, /createCairnClient/);
  assert.match(api, /matchesComponentSchema/);
  assert.match(api, /apiOrigins\.identity/);
  assert.doesNotMatch(api, /apiOrigins\.mock|\/api\/v1\/documents|VITE_MOCK_API_URL/);
});
