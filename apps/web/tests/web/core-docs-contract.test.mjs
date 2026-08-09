import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repositoryRoot = new URL("../../../../", import.meta.url);
const projectTaskEndpoints = [
  "POST /api/v1/projects",
  "GET /api/v1/projects",
  "GET /api/v1/projects/{project_id}",
  "POST /api/v1/projects/{project_id}/tasks",
  "GET /api/v1/projects/{project_id}/tasks",
  "PATCH /api/v1/tasks/{task_id}/status",
  "POST /api/v1/tasks/{task_id}/dependencies",
  "GET /api/v1/projects/{project_id}/events",
];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function assertEndpointInventory(readme, documentName) {
  for (const endpoint of projectTaskEndpoints) {
    assert.ok(
      new RegExp(`\`${escapeRegExp(endpoint)}\``).test(readme),
      `${documentName} must document ${endpoint}`,
    );
  }
}

test("endpoint inventory does not infer parent routes from child route text", () => {
  // Break caught: substring matching lets child routes masquerade as the missing
  // POST/GET project collection and GET project detail inventory entries.
  const childRoutesOnly = [
    "- `POST /api/v1/projects/{project_id}/tasks`",
    "- `GET /api/v1/projects/{project_id}/tasks`",
    "- `PATCH /api/v1/tasks/{task_id}/status`",
    "- `POST /api/v1/tasks/{task_id}/dependencies`",
    "- `GET /api/v1/projects/{project_id}/events`",
  ].join("\n");

  assert.throws(
    () => assertEndpointInventory(childRoutesOnly, "synthetic README"),
    /synthetic README must document POST \/api\/v1\/projects/,
  );
});

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

test("root documentation records the delivered Stage 2 project and task boundary", async () => {
  // Break caught: the public overview still presents projects as unimplemented or
  // silently expands Stage 2 into the deferred graph-editing and Agent scope.
  const readme = await readFile(new URL("README.md", repositoryRoot), "utf8");

  assert.match(readme, /阶段 2.*已完成/);
  assertEndpointInventory(readme, "README.md");
  assert.match(readme, /Project.*聚合根/);
  assert.match(readme, /CurrentIdentity.*组织.*权威/);
  assert.match(readme, /不接受.*org_id/);
  assert.match(readme, /阶段.*里程碑.*编辑.*延后/);
  assert.match(readme, /Outbox worker.*延后/i);
  assert.match(readme, /Bearer\/OIDC.*延后/);
  assert.doesNotMatch(readme, /项目与任务端点：未实现/);
});

test("API documentation inventories every delivered project and task endpoint", async () => {
  // Break caught: an endpoint ships but is absent from the public API inventory.
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assertEndpointInventory(readme, "apps/api/README.md");
});

test("API documentation specifies the exact task transition graph and terminal states", async () => {
  // Break caught: documentation permits an extra state edge or omits one enforced by
  // ALLOWED_TASK_TRANSITIONS, causing clients to offer transitions the server rejects.
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  for (const status of [
    "backlog",
    "todo",
    "in_progress",
    "blocked",
    "done",
    "cancelled",
  ]) {
    assert.match(readme, new RegExp(`\\b${status}\\b`));
  }
  const documentedTransitions = new Set(
    [...readme.matchAll(/^- `([^`]+ → [^`]+)`$/gm)].map((match) => match[1]),
  );
  assert.deepEqual(documentedTransitions, new Set([
    "backlog → todo",
    "todo → in_progress",
    "in_progress → blocked",
    "in_progress → done",
    "in_progress → cancelled",
    "blocked → in_progress",
  ]));
  assert.match(readme, /`done`[^。\n]*终态[^。\n]*(?:无|没有)[^。\n]*出边/);
  assert.match(readme, /`cancelled`[^。\n]*终态[^。\n]*(?:无|没有)[^。\n]*出边/);
  assert.match(readme, /`409 invalid_state_transition`/);
});

test("API documentation maps each dependency rejection to the implemented error", async () => {
  // Break caught: consumers cannot distinguish hidden/missing tasks from invalid,
  // duplicate, and cyclic dependency edges.
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assert.match(readme, /predecessor.*→.*successor/i);
  assert.match(readme, /任务缺失[^。\n]*`404 not_found`/);
  assert.match(readme, /跨租户[^。\n]*`404 not_found`/);
  assert.match(readme, /跨项目[^。\n]*`422 invalid_dependency`/);
  assert.match(readme, /自依赖[^。\n]*`422 invalid_dependency`/);
  assert.match(readme, /重复[^。\n]*`409 dependency_exists`/);
  assert.match(readme, /环[^。\n]*`409 dependency_cycle`/);
});

test("documentation distinguishes resource hiding from non-disclosing event reads", async () => {
  // Break caught: the docs promise a 404 for the event query even though its tenant
  // filter deliberately returns an indistinguishable empty 200 stream.
  const rootReadme = await readFile(new URL("README.md", repositoryRoot), "utf8");
  const apiReadme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  for (const readme of [rootReadme, apiReadme]) {
    assert.match(readme, /项目详情[^。\n]*任务读写[^。\n]*`404 not_found`/);
    assert.match(readme, /events[^。\n]*不存在[^。\n]*`200`[^。\n]*空[^。\n]*`text\/event-stream`/i);
    assert.match(readme, /events[^。\n]*跨租户[^。\n]*`200`[^。\n]*空[^。\n]*`text\/event-stream`/i);
    assert.match(readme, /events[^。\n]*不泄露[^。\n]*项目[^。\n]*存在/);
  }
  assert.doesNotMatch(apiReadme, /跨租户读取或写入返回统一的 `404 not_found`/);
});

test("API documentation specifies cursor pagination and bounded tenant-filtered SSE", async () => {
  // Break caught: clients parse opaque cursors, exceed bounds, or treat a finite event
  // query as a reconnecting subscription.
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assert.match(readme, /\(created_at, id\)/);
  assert.match(readme, /不透明/);
  assert.match(readme, /(?:cursor.*nextCursor|nextCursor.*cursor)/i);
  assert.match(readme, /limit.*1.*100.*默认 50/i);
  assert.match(readme, /`422 invalid_cursor`/);
  assert.match(readme, /\?after=/);
  assert.match(readme, /`id`[^。\n]*不透明[^。\n]*`after`/);
  assert.match(readme, /SSE.*最多 100.*结束/);
  assert.match(readme, /当前组织[^。\n]*Project.*聚合/);
  assert.match(readme, /`503 database_unavailable`/);
  assert.match(readme, /Project.*聚合根/);
  assert.match(readme, /CurrentIdentity.*org_id/);
  assert.match(readme, /React Flow.*延后/);
  assert.match(readme, /长连接.*SSE.*延后/);
});
