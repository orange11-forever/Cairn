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
  "GET /api/v1/organizations/{organization_id}/memberships",
  "PATCH /api/v1/organizations/{organization_id}/memberships/{membership_id}",
  "GET /api/v1/projects/{project_id}/acl",
  "PUT /api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}",
  "DELETE /api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}",
];
const knowledgeEndpointContracts = [
  ["POST /api/v1/projects/{project_id}/knowledge/uploads", "`201 UploadBatchCreateResponse`"],
  [
    "POST /api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
    "`200 UploadCompleteResponse`",
  ],
  [
    "GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}",
    "`200 BatchDetailResponse`",
  ],
  [
    "GET /api/v1/projects/{project_id}/knowledge/resources",
    "`200 KnowledgeResourcePage`",
  ],
  [
    "GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
    "`200 KnowledgeResourceResponse`",
  ],
  [
    "POST /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/{version_id}/retry",
    "`200 KnowledgeResourceResponse`",
  ],
  [
    "DELETE /api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
    "`204` 无响应体",
  ],
  [
    "GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download",
    "`307` + `Location`",
  ],
  [
    "GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}",
    "`200 ChunkContextResponse`",
  ],
  [
    "POST /api/v1/projects/{project_id}/knowledge/search",
    "`200 KnowledgeSearchResponse`",
  ],
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

function assertKnowledgeEndpointContracts(readme, documentName) {
  for (const [endpoint, successContract] of knowledgeEndpointContracts) {
    const routeRow = readme
      .split("\n")
      .find((line) => line.trimStart().startsWith("|") && line.includes(`\`${endpoint}\``));
    assert.ok(routeRow, `${documentName} must document ${endpoint}`);
    const cells = routeRow.split("|").map((cell) => cell.trim());
    assert.equal(cells[1], `\`${endpoint}\``, `${endpoint} must occupy one route table cell`);
    assert.equal(
      cells[2],
      successContract,
      `${documentName} must document ${endpoint} as ${successContract}`,
    );
  }
}

function findTaskStatement(document, documentName, taskName, capabilityPattern) {
  const taskBoundary = /(?=(?:Stage 3A )?Task \d+(?:–\d+)?[A-Z]?(?:\b|[：|]))/;
  const targetTask = new RegExp(
    `^(?:Stage 3A )?${escapeRegExp(taskName)}(?:\\b|[：|])`,
  );
  const statement = document
    .split("\n")
    .flatMap((line) => line.split(taskBoundary))
    .map((segment) => segment.trim())
    .find((segment) => targetTask.test(segment) && capabilityPattern.test(segment));
  assert.ok(
    statement,
    `${documentName} must contain a ${taskName} ${capabilityPattern.source} statement`,
  );
  assert.match(
    statement,
    /(?:已交付|已完成)/,
    `${documentName} ${taskName} capability statement must carry its own delivery status`,
  );
  return statement;
}

function assertTask16PublicDelivery(document, documentName) {
  // Break caught: one public status surface regresses Task 15 search facts, weakens
  // the Task 16 reauthorization/download safety boundary, or presents deferred UI as shipped.
  const task15Statement = findTaskStatement(
    document,
    documentName,
    "Task 15",
    /真实知识搜索结果/,
  );
  assert.match(
    task15Statement,
    /(?:locator|定位信息)/,
    `${documentName} Task 15 delivery must retain locator information`,
  );
  assert.match(
    task15Statement,
    /混合检索/,
    `${documentName} Task 15 delivery must retain hybrid-search behavior`,
  );
  assert.match(
    task15Statement,
    /关键词降级/,
    `${documentName} Task 15 delivery must retain keyword-fallback behavior`,
  );

  const task16Statement = findTaskStatement(
    document,
    documentName,
    "Task 16",
    /引用上下文[^\n]*授权下载/,
  );
  assert.match(
    task16Statement,
    /纯文本/,
    `${documentName} Task 16 context must be described as plain text`,
  );
  assert.match(
    task16Statement,
    /前文[^\n]*命中(?:片段)?[^\n]*后文/,
    `${documentName} Task 16 context must preserve before, hit, after ordering`,
  );
  assert.match(
    task16Statement,
    /重新展开[^；。\n]*重新授权/,
    `${documentName} Task 16 re-expansion must reauthorize context`,
  );
  assert.match(
    task16Statement,
    /下载[^；。\n]*新标签页[^；。\n]*Identity API/,
    `${documentName} Task 16 download must open a new tab at the Identity API`,
  );
  assert.match(
    task16Statement,
    /实时授权后[^；。\n]*`307`[^；。\n]*短时效对象地址/,
    `${documentName} Task 16 download must authorize live before a 307 to a short-lived object address`,
  );
  assert.match(
    task16Statement,
    /Web 不(?:读取或缓存|缓存或读取)最终预签名 URL/,
    `${documentName} must forbid Web from reading or caching the final presigned URL`,
  );
  assert.doesNotMatch(
    document,
    /引用上下文[^；。\n]*(?:后续|尚未|延后|未交付|不交付)/,
    `${documentName} must not defer citation context`,
  );
  assert.doesNotMatch(
    document,
    /(?:授权)?下载[^；。\n]*(?:后续|尚未|延后|未交付|不交付)/,
    `${documentName} must not defer authorized download`,
  );
}

function assertTask17PublicDelivery(document, documentName) {
  assert.match(document, /Stage 3A Task 1–18/, documentName + " must publish the current Task 18 frontier");
  assert.doesNotMatch(document, /Task 1–16/, documentName + " must not retain a stale frontier");
  const statement = findTaskStatement(document, documentName, "Task 17", /真实上传批次/);
  for (const [capability, pattern] of [
    ["project and write scope", /\/projects\/:projectId\/knowledge[^。\n]*canWrite/],
    ["selection and validation", /选择[^。\n]*拖放[^。\n]*20[^。\n]*校验[^。\n]*SHA-256/],
    ["bounded direct PUT progress and completion", /2 个并发[^。\n]*PUT[^。\n]*直传[^。\n]*进度[^。\n]*complete/],
    ["bounded tracking and manual refresh", /2 秒[^。\n]*终止[^。\n]*5 分钟[^。\n]*停止自动跟踪[^。\n]*手动刷新[^。\n]*不伪造处理失败/],
    ["browser-only cancellation", /取消只停止当前浏览器操作[^。\n]*已确认的服务端任务仍会继续/],
    ["new-batch upload retry", /可重试的传输或[^。\n]*complete[^。\n]*失败[^。\n]*全新批次与预签名 URL/],
    ["non-retryable contract failures", /contract[^。\n]*不允许重试/],
  ]) {
    assert.match(statement, pattern, documentName + " must retain " + capability);
  }
  assert.match(document, /公开 `PUT` URL 必须与 Web 页面使用不同 origin/);
  assert.match(document, /拒绝同源上传 URL[^。\n]*Cookie/);
  assert.match(document, /PUT[^。\n]*不携带 Identity credentials/);
  assert.match(document, /预签名上传 URL[^。\n]*不进入 DOM、Query\/Mutation 缓存、日志或浏览器存储/);
  assert.match(document, /搜索仅标记 stale，不自动重跑/);
  assert.match(
    document,
    /全文格式化预览、生成式回答和 Mock 退场仍在后续任务/,
    documentName + " must retain deferred product work",
  );
  assert.doesNotMatch(
    document,
    /(?:Web 上传|真实上传批次)[^；。\n]*(?:后续|尚未|延后|未交付|不交付)/,
    documentName + " must not defer delivered project uploads",
  );
  assert.doesNotMatch(
    document,
    /(?:全文格式化预览|生成式回答|Mock 退场)[^；。\n]*(?:已交付|已完成)/,
    documentName + " must not present deferred Web capabilities as delivered",
  );
}

function assertTask18APublicDelivery(document, documentName) {
  assert.match(
    document,
    /Stage 3A Task 1–18/,
    documentName + " must publish the current Task 18 frontier",
  );
  const statement = findTaskStatement(document, documentName, "Task 18A", /Web 资源详情/);
  for (const [capability, pattern] of [
    ["real generated detail GET", /生成 SDK[^。\n]*Cookie credentials[^。\n]*真实 `GET [^`]+\/knowledge\/resources\/\{resource_id\}`/],
    ["collapse cancellation", /收起[^。\n]*取消[^。\n]*(?:清除|销毁)[^。\n]*局部详情/],
    ["project transition isolation", /项目切换[^。\n]*取消[^。\n]*销毁/],
    ["session generation isolation", /会话代际变化[^。\n]*取消[^。\n]*销毁/],
    ["explicit reauthorization", /重新展开[^。\n]*手动刷新[^。\n]*重新授权/],
    ["offline-safe manual refresh", /离线[^。\n]*隐藏旧详情[^。\n]*下载[^。\n]*(?:不自动重连刷新|禁用自动重连刷新)/],
    ["manual-only status", /不(?:做|进行)周期轮询/],
    ["safe detail presentation", /安全[^。\n]*(?:元数据|失败)[^。\n]*(?:中文|错误)/],
    ["ready-only download", /仅 `latestVersion\.status=ready`[^。\n]*Identity API[^。\n]*新标签页/],
    ["no final URL cache", /Web 不(?:读取或缓存|缓存或读取)最终预签名 URL/],
    ["local 404 recheck", /详情 `404`[^。\n]*资源列表[^。\n]*搜索[^。\n]*stale[^。\n]*不自动重跑搜索/],
    ["detail 404 with list 200", /资源列表仍为 `200`[^。\n]*保留工作区/],
    ["detail 404 with list 404", /列表 `404`[^。\n]*隐藏工作区/],
  ]) {
    assert.match(statement, pattern, documentName + " must retain " + capability);
  }
  assert.doesNotMatch(
    document,
    /(?:全文格式化预览|生成式回答|Mock 退场)[^；。\n]*(?:已交付|已完成)/,
  );
}

function assertTask18BPublicDelivery(document, documentName) {
  const statement = findTaskStatement(document, documentName, "Task 18B", /资源操作/);
  for (const [capability, pattern] of [
    ["writer and server retryability gate", /最新资源列表[^。\n]*`canWrite`[^。\n]*`latestVersion\.status=failed`[^。\n]*服务端返回 `latestVersion\.retryable=true`/],
    ["exact request identifiers", /请求中的精确 `resource_id`\/`version_id`/],
    ["matched response identifiers", /返回体 `id`[^。\n]*请求 `resource_id`[^。\n]*`latestVersion\.id`[^。\n]*请求 `version_id`[^。\n]*匹配/],
    ["exact retry response", /重试[^。\n]*`200`[^。\n]*(?:匹配[^。\n]*资源[／/]版本|返回体[^。\n]*`id`)/],
    ["CSRF mutation boundary", /重试[^。\n]*CSRF/],
    ["named confirmation and exact delete", /软删除[^。\n]*当前资源名[^。\n]*行内[^。\n]*确认[^。\n]*取消[^。\n]*不发送请求[^。\n]*`204` 空响应/],
    ["no automatic replay or rollback claim", /不自动重试[^。\n]*离线回放[^。\n]*不承诺回滚/],
    ["cancel before cleanup", /删除[^。\n]*先取消[^。\n]*再清理/],
    ["current-project cancellation and search scope", /当前项目[^。\n]*(?:读取|搜索)[^。\n]*搜索/],
    ["scoped cleanup and no search POST", /删除[^。\n]*(?:取消|清理)[^。\n]*(?:详情|引用|搜索)[^。\n]*不自动[^。\n]*`POST`/],
    ["preserve other projects and upload tracking", /保留其他项目[^。\n]*上传跟踪/],
    ["session cancellation isolation", /迟到 `401`[^。\n]*不会使新会话失效/],
    ["404, 409, and contract recovery", /`404`[^。\n]*列表[^。\n]*`409`[^。\n]*刷新详情[^。\n]*契约错误[^。\n]*手动/],
  ]) {
    assert.match(statement, pattern, documentName + " must retain " + capability);
  }
  assert.match(document, /全文格式化预览、生成式回答和 Mock 退场仍在后续任务/);
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

test("root README publishes a concise current delivery snapshot", async () => {
  // Break caught: the first-screen project status omits a runtime boundary, loses the
  // cross-query/mutation session-invalid contract, or presents deferred Web work as shipped.
  const readme = await readFile(new URL("README.md", repositoryRoot), "utf8");

  assert.match(readme, /## 当前交付快照/);
  for (const boundary of ["Web", "API \/ SDK", "Worker", "基础设施", "延后"]) {
    assert.match(readme, new RegExp(`\\| ${boundary} \\|`));
  }

  const webBoundary = readme.split("\n").find((line) => line.startsWith("| Web |"));
  assert.ok(webBoundary, "README must include the Web delivery boundary");
  assert.match(webBoundary, /查询和变更请求[^|]*`401 session_invalid`/);
  assert.match(webBoundary, /清理本地会话/);
  assert.match(webBoundary, /查询缓存/);
  assert.match(webBoundary, /变更缓存/);
  assert.match(webBoundary, /回到登录页/);

  const apiSdkBoundary = readme.split("\n").find((line) => line.startsWith("| API \/ SDK |"));
  assert.ok(apiSdkBoundary, "README must include the API / SDK delivery boundary");
  assert.match(apiSdkBoundary, /SDK[^|]*导出[^|]*OpenAPI schema[^|]*运行时校验器/);
  assert.match(apiSdkBoundary, /Web API 适配器[^|]*OpenAPI `date-time`[^|]*校验/);
  assert.match(
    readme,
    /全文格式化预览[^\n]*生成式回答[^\n]*Mock[^\n]*(?:后续|尚未|延后)/,
  );
  assert.doesNotMatch(readme, /搜索结果[^；。\n]*(?:后续|尚未|延后)/);
  assert.match(readme, /```text\nCairn\n├── apps\//);
  assert.doesNotMatch(readme, /```text\nCarin\n/);
});

test("API documentation records the delivered authorization boundary and deferred work", async () => {
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assert.match(readme, /Bearer\/OIDC.*未实现/);
  assert.match(readme, /已实现.*PostgreSQL 登录限流/);
  assert.match(readme, /CAIRN_AUTH_RATE_LIMIT_SECRET/);
  assert.match(readme, /CAIRN_TRUSTED_PROXY_CIDRS/);
  assert.match(readme, /pnpm auth:cleanup/);
  assert.match(readme, /阶段 2\.5A.*已交付/);
  assert.match(readme, /read\s*<\s*write\s*<\s*manage/);
  assert.match(readme, /viewer[^。\n]*上限[^。\n]*read/i);
  assert.match(readme, /last_owner_required/);
  assert.match(readme, /群组.*未实现/);
  assert.match(readme, /Task 12.*混合搜索.*已交付/);
  assert.match(readme, /Task 13.*Web 知识工作区基础.*已交付/);
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

test("root documentation publishes Stage 2.5A without expanding the UI boundary", async () => {
  const readme = await readFile(new URL("README.md", repositoryRoot), "utf8");

  assert.match(readme, /已完成阶段 2\.5A/);
  for (const role of ["owner", "admin", "member", "viewer"]) {
    assert.match(readme, new RegExp(`\\b${role}\\b`, "i"));
  }
  assert.match(readme, /ACL.*UI.*未实现/i);
  assert.match(readme, /群组.*未实现/);
  assert.match(readme, /Task 12.*混合搜索.*已交付/);
  assert.match(readme, /Task 13.*Web 知识工作区基础.*已交付/);
});

test("public documentation records Task 16 citation context and authorized download", async () => {
  const [rootReadme, apiReadme, architecture] = await Promise.all([
    readFile(new URL("README.md", repositoryRoot), "utf8"),
    readFile(new URL("apps/api/README.md", repositoryRoot), "utf8"),
    readFile(new URL("docs/architecture.md", repositoryRoot), "utf8"),
  ]);

  assertTask16PublicDelivery(rootReadme, "README.md");
  assertTask16PublicDelivery(apiReadme, "apps/api/README.md");
  assertTask16PublicDelivery(architecture, "docs/architecture.md");
});

test("public documentation preserves Task 17 upload contracts at the Task 18A frontier", async () => {
  for (const documentName of ["README.md", "apps/api/README.md", "docs/architecture.md"]) {
    const document = await readFile(new URL(documentName, repositoryRoot), "utf8");
    assertTask17PublicDelivery(document, documentName);
  }
});

test("Task 17 delivery checks reject stale upload deferrals, unsafe retries, and overclaims", async () => {
  const document = await readFile(new URL("README.md", repositoryRoot), "utf8");
  for (const [before, after] of [
    ["Task 1–18", "Task 1–16"],
    ["全新批次与预签名 URL", "旧批次与预签名 URL"],
    ["5 分钟", "无限期"],
    ["不携带 Identity credentials", "携带 Identity credentials"],
    ["必须与 Web 页面使用不同 origin", "可以与 Web 页面使用相同 origin"],
    ["不进入 DOM、Query/Mutation 缓存、日志或浏览器存储", "保存到浏览器存储"],
    ["已确认的服务端任务仍会继续", "已确认的服务端任务也会撤销"],
  ]) {
    assert.ok(document.includes(before), "mutation must change the delivery document: " + before);
    assert.throws(() => assertTask17PublicDelivery(document.replaceAll(before, after), "mutated README"));
  }
  for (const falseClaim of [
    "Web 上传仍在后续任务。",
    "全文格式化预览已交付。",
    "生成式回答已交付。",
    "Mock 退场已完成。",
  ]) {
    assert.throws(() => assertTask17PublicDelivery(document + "\n" + falseClaim, "mutated README"));
  }
});

test("public documentation records bounded Task 18A resource details", async () => {
  for (const documentName of ["README.md", "apps/api/README.md", "docs/architecture.md"]) {
    const document = await readFile(new URL(documentName, repositoryRoot), "utf8");
    assertTask18APublicDelivery(document, documentName);
  }
});

test("public documentation records Task 18B resource operations", async () => {
  for (const documentName of ["README.md", "apps/api/README.md", "docs/architecture.md"]) {
    const document = await readFile(new URL(documentName, repositoryRoot), "utf8");
    assertTask18BPublicDelivery(document, documentName);
  }
});

test("Task 18 delivery checks reject unsafe or stale lifecycle claims", async () => {
  const document = await readFile(new URL("README.md", repositoryRoot), "utf8");
  for (const [before, after] of [
    ["重新展开和手动刷新都会重新授权", "重新展开复用旧授权详情"],
    ["项目切换或", ""],
    ["或会话代际变化", ""],
    ["离线等待期间隐藏旧详情和下载", "离线等待期间保留旧详情和下载"],
    ["不进行周期轮询", "每 2 秒自动轮询"],
    ["仅 `latestVersion.status=ready`", "所有版本状态"],
    ["不自动重跑搜索", "自动重跑搜索"],
    ["资源列表仍为 `200` 时保留工作区", "资源列表仍为 `200` 时隐藏工作区"],
    ["列表 `404` 才隐藏工作区", "列表 `404` 也保留工作区"],
  ]) {
    assert.ok(document.includes(before), "mutation must change Task 18A docs: " + before);
    assert.throws(() => assertTask18APublicDelivery(
      document.replaceAll(before, after),
      "mutated README",
    ));
  }
  for (const [before, after] of [
    ["`canWrite` 且 `latestVersion.status=failed`、服务端返回 `latestVersion.retryable=true`", "`canWrite` 且 `latestVersion.status=failed`"],
    ["请求中的精确 `resource_id`/`version_id`", "请求中的精确 `resource_id`"],
    ["返回体 `id` 与请求 `resource_id`、`latestVersion.id` 与请求 `version_id` 匹配", "返回体 `id` 与请求 `resource_id` 匹配"],
    ["列出当前资源名的行内确认", "行内确认"],
    ["先取消当前项目相关的列表、详情、引用和搜索读取，再清理", "清理"],
    ["当前项目相关的列表、详情、引用和搜索读取", "相关的列表、详情、引用和搜索读取"],
    ["删除会先取消当前项目相关的列表、详情、引用和搜索读取，再清理其缓存并重置当前项目可见搜索", "删除会先取消相关的列表、详情、引用和搜索读取，再清理其缓存并重置可见搜索"],
    ["保留其他项目和上传跟踪", "保留上传跟踪"],
    ["当前 CSRF", "任意凭据"],
    ["取消不发送请求", "取消也发送请求"],
    ["不自动重试或离线回放", "自动重试或离线回放"],
    ["不承诺回滚", "承诺回滚"],
    ["不自动发起 `POST`", "自动发起 `POST`"],
    ["迟到 `401` 不会使新会话失效", "迟到 `401` 会使新会话失效"],
    ["`404` 重检列表并按列表 `200`/`404` 决定局部资源或工作区隐藏，`409` 先刷新详情，契约错误须手动详情恢复", "`404` 直接成功，`409` 直接重试，契约错误继续提供操作"],
  ]) {
    assert.ok(document.includes(before), "mutation must change the Task 18B clause: " + before);
    assert.throws(() => assertTask18BPublicDelivery(document.replaceAll(before, after), "mutated README"));
  }
});

test("API documentation binds all ten knowledge routes to their response contracts", async () => {
  // Break caught: a route is omitted, assigned another schema/status, or the special
  // no-body delete and redirect Location contracts are weakened.
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assert.match(readme, /## Stage 3A Task 1–18 知识摄取、资源操作与搜索契约/);
  assertKnowledgeEndpointContracts(readme, "apps/api/README.md");
});

test("knowledge API documentation preserves security, tracing, and cache headers", async () => {
  // Break caught: mutation CSRF, request/error correlation, no-store, concealment,
  // or the download reauthorization boundary disappears from the public contract.
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assert.match(readme, /上传批次、上传完成、手动重试和删除[^。\n]*mutation[^。\n]*Origin[^。\n]*`X-CSRF-Token`/);
  assert.match(readme, /搜索 `POST`[^。\n]*Origin[^。\n]*`X-CSRF-Token`/);
  assert.match(readme, /不存在、跨组织或权限不足[^。\n]*`404 not_found`/);
  assert.match(readme, /下载[^。\n]*重新授权[^。\n]*`307`[^。\n]*(?:对象 URL|S3\/MinIO URL)/);
  assert.match(readme, /`X-Request-ID`[^。\n]*`Cache-Control: private, no-store`/);
  assert.match(readme, /\{ message, code, traceId \}[^。\n]*`traceId`[^。\n]*`X-Request-ID`/);
  assert.match(readme, /错误响应包含机器错误码和 `traceId`/);
  assert.doesNotMatch(readme, /错误响应包含机器错误码和 `trace_id`/);
});

test("API documentation describes sanitized ingestion failures without leaking provider details", async () => {
  // Break caught: the public contract promises provider/model/profile diagnostics
  // even though persisted failures expose only stable codes and sanitized detail.
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assert.match(readme, /失败[^。\n]*稳定错误码[^。\n]*(?:清洗|`safe_detail`)/);
  assert.doesNotMatch(readme, /失败时返回可定位到 provider、model 和 profile 的错误/);
});

test("documentation distinguishes current ingestion infrastructure from planned services", async () => {
  // Break caught: pgvector, MinIO, or the Worker is demoted to roadmap status, or
  // Redis is accidentally advertised as a current dependency.
  const [rootReadme, workerReadme, architecture] = await Promise.all([
    readFile(new URL("README.md", repositoryRoot), "utf8"),
    readFile(new URL("apps/worker/README.md", repositoryRoot), "utf8"),
    readFile(new URL("docs/architecture.md", repositoryRoot), "utf8"),
  ]);

  assert.match(rootReadme, /PostgreSQL 16\/pgvector 与 S3 兼容 MinIO 当前已使用；Redis 规划/);
  assert.match(rootReadme, /独立 Worker[^\n]*知识摄取核心链路/);

  assert.match(workerReadme, /Stage 3A Task 1–11 已交付的独立 Python 进程/);
  assert.match(workerReadme, /pnpm infra:up[^\n]*PostgreSQL 16\/pgvector 和 MinIO/);
  assert.match(workerReadme, /Redis[^\n]*规划/);

  assert.match(architecture, /PostgreSQL 16\/pgvector[^\n]*当前已使用/);
  assert.match(architecture, /S3 兼容 MinIO[^\n]*当前已使用/);
  assert.match(architecture, /独立 Worker[^\n]*(?:已交付|当前已使用)/);
  assert.match(architecture, /Redis[^\n]*规划/);
});

test("Worker documentation covers current modes and explicit non-goals", async () => {
  // Break caught: an operator loses a supported execution mode, or planned search,
  // Agent, deletion propagation, or connector work is presented as Worker behavior.
  const readme = await readFile(new URL("apps/worker/README.md", repositoryRoot), "utf8");

  assert.match(readme, /`pnpm dev:worker`[^\n]*持续模式/);
  assert.match(readme, /`pnpm worker:once`[^\n]*最多处理一个/);
  assert.match(readme, /`pnpm worker:preflight`[^\n]*不租用任务/);
  assert.match(readme, /Task 12 混合搜索查询/);
  assert.match(readme, /Temporal Agent 工作流/);
  assert.match(readme, /软删除[^\n]*对象\/索引清除传播/);
  assert.match(readme, /连接器[^\n]*外部来源删除传播/);
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

test("API documentation authorizes event reads before querying the Outbox", async () => {
  // Break caught: documentation bypasses the delivered project ACL policy or omits
  // one of the three concealed inputs that short-circuit before Outbox retrieval.
  const readme = await readFile(new URL("apps/api/README.md", repositoryRoot), "utf8");

  assert.match(
    readme,
    /events[^。\n]*先[^。\n]*(?:ACL|授权)[^。\n]*`read`[^。\n]*授权通过[^。\n]*才[^。\n]*Outbox/i,
  );
  assert.match(
    readme,
    /events[^。\n]*不存在[^。\n]*跨组织[^。\n]*同组织[^。\n]*无 `read` 权限[^。\n]*`200`[^。\n]*空[^。\n]*`text\/event-stream`/i,
  );
  assert.doesNotMatch(
    readme,
    /events[^。\n]*(?:不先加载项目|不验证项目是否存在)/i,
  );
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
