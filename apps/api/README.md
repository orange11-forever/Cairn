# apps/api: FastAPI 后端

`apps/api` 是根 uv workspace 中可安装、可独立启动的 FastAPI package，现已提供 PostgreSQL 组织身份、Cookie 会话、组织 RBAC、项目 ACL、项目任务、审计、事务性 Outbox、有界 SSE、Stage 3A Task 1–11 知识上传与资源生命周期、Task 12 项目范围混合搜索、配置、请求 ID、统一错误、健康检查和 OpenAPI。Agent 执行和完整 Provider 治理能力仍在后续阶段。

Web 的身份、项目任务与 `/projects/:projectId/knowledge` 资源/搜索连接本 API；现有通用文档、上传和问答原型仍连接 `mocks/docs-server.mjs`。Task 14 真实知识资源列表已交付；Task 15 真实知识搜索结果已交付，显示服务端排序摘录、文件类型、类型化 locator 定位信息、混合检索标签与关键词降级结果，并覆盖取消、错误、会话失效和访问权撤销状态。Task 16 搜索卡片内按需引用上下文与授权下载已交付：引用上下文以“前文 → 命中片段 → 后文”展示纯文本，重新展开会重新授权；下载只把新标签页导航到 Identity API，实时授权后由 `307` 重定向到短时效对象地址，Web 不缓存或读取最终预签名 URL。Web 上传、资源详情与重试/删除、全文格式化预览、生成式回答和 Mock 退场仍在后续任务。当前产品、架构和阶段路线以 [公开架构说明](../../docs/architecture.md) 为准。

Web 壳与项目工作台的响应式/可访问性抛光，以及知识向导“岑宁”的 Q 版紧凑头像，均为客户端展示与验收更新，不新增 API 端点，也不扩展 Stage 3A API 交付边界。

当前核心开发由 FastAPI、PostgreSQL 16/pgvector、S3 兼容 MinIO、独立知识 Worker、React/Vite Web 与文档 Node mock 共同组成；Redis 仍是规划中基础设施。API 默认绑定 `127.0.0.1:8080`，身份与知识数据不使用 SQLite 或内存仓储分叉。未来 Local Web、Compose 与 Helm 必须继续使用同一 `/api/v1` 契约、数据库迁移和权限规则。

## 当前工程命令

在仓库根目录运行：

```bash
uv sync --all-packages --all-groups
pnpm infra:up
pnpm db:migrate
pnpm db:seed
pnpm dev:api
pnpm auth:cleanup
uv run --package cairn-api cairn-api upload-cleanup
pnpm dev:worker
pnpm worker:once
pnpm worker:preflight
pnpm test:worker
pnpm lint:worker
pnpm typecheck:worker
pnpm check:sdk
uv run --package cairn-api pytest
uv run --package cairn-api ruff check apps/api/src apps/api/tests
uv run --package cairn-api pyright
uv build --package cairn-api
```

API 默认监听 `127.0.0.1:8080`，提供 `/health`、`/ready`、身份与知识接口、`/docs` 和 `/openapi.json`。日常完整开发流程应从仓库根目录运行 `pnpm infra:up` 和 `pnpm dev:core`；`infra:up` 会启动 pgvector PostgreSQL 与 MinIO，并初始化 bucket/CORS。Worker 用 `pnpm dev:worker` 作为独立进程运行；停止 `dev:core` 不会停止 Worker，也不会删除 PostgreSQL 或 MinIO 开发卷。

Docker Desktop 必须保持运行。生产环境必须使用 HTTPS `APP_URL`/`CORS_ORIGINS`、启用安全 Cookie，并分别提供至少 32 字节且不能复用的 `CAIRN_CSRF_SECRET` 与 `CAIRN_AUTH_RATE_LIMIT_SECRET`。将直接连接的可信反向代理网段以逗号分隔配置到 `CAIRN_TRUSTED_PROXY_CIDRS`；代理必须覆盖外部请求携带的 `Forwarded`/`X-Forwarded-*`，Uvicorn 不代替应用解析这些请求头。

## 当前能力边界

- 已实现：组织、用户、成员关系、Argon2id 密码、Cookie 会话、CSRF、PostgreSQL 登录限流、当前组织查询、项目、任务、任务依赖、状态机、追加式审计、事务性 Outbox 和有界 SSE 查询。
- 阶段 2.5A 已交付项目范围的组织 RBAC、规范化 ACL、成员角色列表与更新 API。
- Stage 3A Task 1–11 已交付：1–20 文件上传批次、校验和绑定的 MinIO/S3 预签名直传、批次状态、知识资源生命周期、切片上下文和独立 Worker 摄取链路。
- Stage 3A Task 12 混合搜索 API 已交付：项目权限过滤优先的关键词/向量召回、确定性融合、关键词降级、限流、审计与可追溯引用。
- Stage 3A Task 13 Web 知识工作区基础已交付：受保护路由、真实资源分页、`canWrite` 权限状态展示与搜索请求/query 状态边界；完整 UI 闭环仍在后续任务中。
- Stage 3A Task 14 真实知识资源列表已交付：显示标题、文件类型、大小、更新时间和处理状态，支持保留既有项目的游标续页、分页错误恢复与只读能力提示。
- Stage 3A Task 15 真实知识搜索结果已交付：按服务端顺序显示摘录、文件类型、类型化 locator 定位信息和混合检索/关键词降级标签，并保留取消、错误、`401 session_invalid` 会话失效与访问权撤销状态。
- Stage 3A Task 16 搜索卡片内按需引用上下文与授权下载已交付：按“前文 → 命中片段 → 后文”展示纯文本，重新展开会重新授权；下载在新标签页中只导航到 Identity API，经实时授权与 `307` 重定向进入短时效对象地址，Web 不缓存或读取最终预签名 URL。Web 上传、资源详情与重试/删除、全文格式化预览、生成式回答和 Mock 退场仍在后续任务。
- `Bearer/OIDC`：未实现。
- 群组、邀请、成员移除、ACL 管理 UI 与成员管理 UI：未实现。
- 连接器、AI Provider 完整策略层与外部 Agent：未实现。

登录限流使用固定的 15 分钟窗口：规范化邮箱最多失败 5 次，来源 IP 最多失败 30 次，达到阈值后阻止 15 分钟。`auth_rate_limits` 只保存以 `CAIRN_AUTH_RATE_LIMIT_SECRET` 生成的 HMAC-SHA-256 摘要，不保存明文邮箱或 IP；限流数据库操作失败时登录会关闭并返回 `503 database_unavailable`。

`pnpm auth:cleanup` 分批、幂等删除过期/已撤销会话和失效限流桶，保留有效会话、活动窗口和全部审计记录。演示种子只允许在开发和测试环境运行；生产配置拒绝演示种子、示例密钥、HTTP Origin 和不安全 Cookie。停止 `pnpm dev:core` 只停止 API、Mock 与 Web 进程，不删除 PostgreSQL 开发卷。

`uv run --package cairn-api cairn-api upload-cleanup` 分批租用过期上传会话，删除孤立上传对象并持久化可审计的终态；数据库或对象存储失败会以非零退出码暴露，便于定时任务重试。

根命令 `pnpm verify:core` 除迁移、PostgreSQL 集成测试、SDK 和 Web 验收外，还会用临时 localhost 证书启动 HTTPS 反向代理与生产配置 API，通过 Chromium 检查 CORS、Cookie、会话、CSRF 和审计来源 IP，并在所有退出路径清理证书、进程与隔离数据库资源。该阶段要求本机可用 OpenSSL 和 Playwright Chromium。

## 阶段 2 项目任务契约

项目与任务端点只信任认证依赖提供的 `CurrentIdentity`，以其中的组织作为租户权威。创建请求明确禁止客户端提交可信 `org_id`、创建者或 actor 字段。项目详情与任务读写对缺失或跨租户资源返回 `404 not_found`；events 查询则先按当前组织、成员角色与项目 ACL 校验 `read`，授权通过才按组织与 `Project` aggregate 查询 Outbox，所以使用下述非泄露空流语义：

- `events` 查询不存在、跨组织（跨租户）或同组织但无 `read` 权限的项目 ID：均返回 `200` 空 `text/event-stream`，不查询 Outbox，也不泄露项目是否存在或调用者缺少权限。

### 端点

| 方法与路径 | 语义 |
|---|---|
| `POST /api/v1/projects` | 创建项目 |
| `GET /api/v1/projects` | 分页列出当前组织的项目 |
| `GET /api/v1/projects/{project_id}` | 读取当前组织中的项目 |
| `POST /api/v1/projects/{project_id}/tasks` | 在项目中创建任务 |
| `GET /api/v1/projects/{project_id}/tasks` | 分页列出项目任务 |
| `PATCH /api/v1/tasks/{task_id}/status` | 通过服务端状态机转换任务状态 |
| `POST /api/v1/tasks/{task_id}/dependencies` | 添加指向路由任务的前置依赖 |
| `GET /api/v1/projects/{project_id}/events` | 先执行项目 `read` 授权；通过后读取有界 Outbox SSE 批次，否则返回空 `200` stream |
| `GET /api/v1/organizations/{organization_id}/memberships` | 分页列出当前组织成员；仅 `owner`、`admin` |
| `PATCH /api/v1/organizations/{organization_id}/memberships/{membership_id}` | 按角色矩阵更新成员角色 |
| `GET /api/v1/projects/{project_id}/acl` | 分页列出项目当前有效 ACL；需要 `manage` |
| `PUT /api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}` | 幂等设置项目 ACL |
| `DELETE /api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}` | 幂等撤销项目 ACL 并保留历史行 |

Cookie 会话下的 `POST`/`PATCH`/`PUT`/`DELETE` 命令要求合法 Origin 和会话绑定的 `X-CSRF-Token`。已接受的项目、任务、成员角色或 ACL 变化会把业务变化、追加式审计行与 Outbox 事件放在同一数据库事务中提交。

### 阶段 2.5A 授权与成员管理

项目权限的顺序严格为 `read < write < manage`，更高权限包含更低权限。授权查询以当前组织为第一过滤条件，再组合组织角色和当前有效的规范化 ACL：

| 组织角色 | 项目权限 | 项目创建 | 成员管理 |
|---|---|---|---|
| `owner` | 所有当前组织项目隐式 `manage` | 允许 | 可列出成员并把任意成员切换为任意角色 |
| `admin` | 所有当前组织项目隐式 `manage` | 允许 | 可列出成员；只能在 `member` 与 `viewer` 之间切换 |
| `member` | 匹配 `org`、`role`、`user` ACL 的最高权限 | 允许 | 不允许 |
| `viewer` | 匹配 ACL 后的有效权限上限为 `read` | 禁止，返回 `403 forbidden` | 不允许 |

创建项目在同一事务中写入组织 `read` 和创建者用户 `manage` 两条 ACL。ACL 当前支持 `org`、`role` 与当前组织内的 `user` principal；群组 principal 未实现，非法类型、外部组织、组织外用户或非法角色返回 `422 invalid_principal`。ACL 没有 deny 条目；多个匹配 grant 取最高权限。

项目详情、任务读写和 ACL 读写要求相应的 `read`、`write` 或 `manage`。不存在、跨组织和权限不足的项目统一返回 `404 not_found`，因此调用者不能借错误差异探测项目。`events` 继续使用前述空 `200 text/event-stream` 语义。成员列表对当前组织内权限不足的 `member`/`viewer` 返回 `403 forbidden`；组织 ID 不匹配、成员不存在或成员来自其他组织返回 `404 not_found`。

`owner` 可管理所有角色；`admin` 不能管理 `owner`/`admin`，也不能把成员提升到这两个角色。组织的最后一名 `owner` 不能被降级，返回 `409 last_owner_required`。设置已有的相同角色或相同 ACL、以及撤销不存在的 ACL 都是幂等成功，不写新的审计或 Outbox；实际变化会锁定授权边界，并在业务写入、审计记录与 Outbox 事件全部成功后一起提交，失败则整体回滚。

### 任务状态机

任务状态的完整集合为 `backlog`、`todo`、`in_progress`、`blocked`、`done` 和 `cancelled`。新任务从 `backlog` 开始；服务端只接受以下有向转换：

- `backlog → todo`
- `todo → in_progress`
- `in_progress → blocked`
- `in_progress → done`
- `in_progress → cancelled`
- `blocked → in_progress`

`done` 与 `cancelled` 是终态，没有出边。重复提交当前状态、跳级或任何未列出的边都返回 `409 invalid_state_transition`；状态规则只由服务端执行，客户端展示不能扩展它。

### 任务依赖

`POST /api/v1/tasks/{task_id}/dependencies` 把 JSON 中的 `predecessorTaskId` 作为前置任务，把路径中的 `task_id` 作为后继任务，边方向严格为 predecessor → successor。

服务层逐项拒绝以下依赖输入：

- predecessor 或 successor 任务缺失：`404 not_found`；
- predecessor 或 successor 跨租户：`404 not_found`，不暴露其他租户的任务；
- predecessor 与 successor 跨项目：`422 invalid_dependency`；
- predecessor 与 successor 自依赖：`422 invalid_dependency`；
- predecessor → successor 重复边：`409 dependency_exists`；
- 新边会闭合反向可达路径形成环：`409 dependency_cycle`。

依赖创建锁定所属项目；Outbox 中的 `Project` 是聚合根，任务创建、任务状态变化和依赖添加事件都使用项目 ID 作为 `aggregate_id`。

### 游标分页与 SSE

项目列表和项目任务列表采用稳定、不透明的 `(created_at, id)` 游标分页。查询参数 `limit` 范围为 1–100、默认 50；有下一页时响应提供 `nextCursor`，客户端应原样作为下一次请求的 `cursor`，不能解析或构造它。无效游标返回 `422 invalid_cursor`。

`GET /api/v1/projects/{project_id}/events?after=...` 先在当前组织中结合成员角色与项目 ACL 校验 `read`。不存在、跨组织或同组织但无读取权限的项目都会在查询 Outbox 前得到相同的空 `200 text/event-stream`，而不是 `404`；只有授权通过后，服务端才按 `(occurred_at, id)` 升序读取当前组织、当前 `Project` 聚合的 Outbox 事件。响应为 `text/event-stream`；SSE 批次一次最多 100 个 frame，发送完即结束。`id` 是不透明续读游标，可在下一次请求的 `after` 中使用。这不是长连接订阅，数据库错误会在开始响应前返回 `503 database_unavailable`，其他租户的事件不会进入结果。

### 显式延后

- 完整阶段/里程碑编辑 UI、React Flow/ELK 图编辑、拖拽 Kanban 和时间线可视化延后。
- Outbox worker 发布、长连接重连 SSE、Redis fan-out、评论、通知和任务执行延后。
- 群组、邀请、成员移除、ACL/成员管理 UI、Bearer/OIDC、连接器、Agent 执行和完整模型 Provider 策略层延后。Web 上传、资源详情与重试/删除、全文格式化预览、生成式回答和 Mock 退场仍在后续任务。

## Stage 3A Task 1–12 知识摄取与搜索契约

这些端点继承 Cookie 会话和项目授权。上传批次、上传完成、手动重试和删除是 mutation，都要求合法 Cookie Origin 和会话绑定的 `X-CSRF-Token`。项目或知识资源不存在、跨组织或权限不足时使用统一的不泄露 `404 not_found`，不通过错误差异暴露资源存在性。

`POST .../knowledge/uploads` 严格接受 1–20 个文件意图，为每个文件返回绑定媒体类型与 SHA-256 校验和的 S3/MinIO 预签名 `PUT`。完成确认会检查对象存在性、大小、校验和与媒体类型，再以同一数据库事务创建资源/版本、摄取任务、追加式审计和 Outbox 事件。

| 方法与路径 | 成功契约 | 语义 |
|---|---|---|
| `POST /api/v1/projects/{project_id}/knowledge/uploads` | `201 UploadBatchCreateResponse` | 创建批次并返回每个对象的预签名上传指令 |
| `POST /api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete` | `200 UploadCompleteResponse` | 验证直传对象并推进批次/资源状态 |
| `GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}` | `200 BatchDetailResponse` | 返回批次汇总和每个摄取 item 状态 |
| `GET /api/v1/projects/{project_id}/knowledge/resources` | `200 KnowledgeResourcePage` | 用不透明游标分页返回资源与 `canWrite` 能力 |
| `GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}` | `200 KnowledgeResourceResponse` | 返回资源和最新版本的处理/失败事实 |
| `POST /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/{version_id}/retry` | `200 KnowledgeResourceResponse` | 将可重试的失败版本重新排队 |
| `DELETE /api/v1/projects/{project_id}/knowledge/resources/{resource_id}` | `204` 无响应体 | 软删除资源并默认从后续读取中排除 |
| `GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download` | `307` + `Location` | 重新检查项目 `read` 权限后重定向到短时效对象 URL |
| `GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}` | `200 ChunkContextResponse` | 返回命中切片、结构化 locator 和同版本前后文 |
| `POST /api/v1/projects/{project_id}/knowledge/search` | `200 KnowledgeSearchResponse` | 在项目授权边界内返回混合检索结果、模式与可追溯引用 |

资源列表 `limit` 范围为 1–100、默认 50，客户端只能将 `nextCursor` 原样作为下次 `cursor`。下载端点不代理对象内容：它会在每次请求中重新授权和写入读取审计，然后返回 `307` 短时效 S3/MinIO URL。

搜索 `POST` 与上传批次、上传完成、手动重试和删除 mutation 一样，要求合法 Cookie Origin 和会话绑定的 `X-CSRF-Token`。搜索先在数据库中固定组织、项目、当前版本、资源状态与 ACL，再召回关键词和向量候选并确定性融合；Embedding 暂时不可用时明确返回 `keyword_fallback`，数据库或权限事实不可用时返回 `503 database_unavailable`。用户或组织超限返回 `429 search_rate_limited` 与有效 `Retry-After`，审计不记录原始查询文本。

所有知识响应都带 `X-Request-ID` 和 `Cache-Control: private, no-store`。标准错误体为 `{ message, code, traceId }`，其 `traceId` 与 `X-Request-ID` 对应；请求验证、会话/CSRF、资源隐藏、状态冲突、数据库/对象存储和未预期异常都通过现有统一错误边界暴露。FastAPI OpenAPI 是契约来源，`pnpm generate:sdk` 生成客户端，`pnpm check:sdk` 在门禁中防止 OpenAPI/SDK 漂移。

## 实施顺序

| 阶段 | API 侧主要交付 |
|---|---|
| 0 | FastAPI 骨架、`/health`、`/api/v1`、统一错误、OpenAPI SDK、测试和 CI |
| 1 | 已完成组织、成员、Cookie 身份、审计和 PostgreSQL 迁移；Bearer 延后 |
| 2 | 已完成项目与任务 DAG、状态机、Outbox 和有界 SSE 查询模型 |
| 2.5A | 已完成组织 RBAC、项目 ACL 与成员角色管理 API；群组、邀请、成员移除和管理 UI 延后 |
| 3A Task 1–11 | 已完成通用知识资源、MinIO/S3 上传、摄取状态、Worker 解析/切分/Embedding/索引和切片引用上下文 |
| 3A Task 12 | 已完成项目范围混合搜索 API、权限预过滤、确定性融合、关键词降级、限流与审计 |
| 3A Task 13 | 已完成真实 Web 知识工作区基础与查询边界 |
| 3A Task 14 | 已完成真实知识资源列表、处理状态、只读提示和游标续页 |
| 3A Task 15 | 已完成真实知识搜索结果、类型化 locator、混合检索/关键词降级标签与取消/错误/会话/访问权状态 |
| 3A Task 16 | 已完成搜索卡片内按需引用上下文与授权下载；前文、命中片段和后文以纯文本展示，重新展开会重新授权，下载只导航到 Identity API 并经实时授权后 `307` 到短时效对象地址且在新标签页打开，Web 不缓存或读取最终预签名 URL；Web 上传、资源详情与重试/删除、全文格式化预览、生成式回答和 Mock 退场仍在后续任务 |
| 4 | Agent、模型策略、运行、预算、审批与 AgentRunner 契约 |
| 5-6 | 外部编程 Agent、代码智能、OIDC/SAML、配额、审计查询和部署治理 |

## 后续数据模型不变量

以下内容同时记录已交付的授权和 Stage 3A Task 1–16 知识边界，以及后续阶段必须遵守的设计约束；Web 上传、资源详情与重试/删除、全文格式化预览、生成式回答和 Mock 退场仍在后续任务，连接器、Agent 或 Provider 能力尚未实现。

### 1. 组织是租户边界

每张租户业务表带 `org_id`。所有高频查询、唯一约束和索引都必须从组织边界开始设计，任何资源读取同时校验组织和资源权限。

最低要求：

- `organizations`、`users`、`memberships` 分表；
- 项目、任务、资源、对话、运行、审计和摄取记录均带 `org_id`；
- 跨组织访问测试覆盖列表、详情、搜索、下载和 Agent 工具调用；
- 服务层从受保护上下文取得 `current_org` 与 `current_user`，不接受客户端自行指定可信组织。

### 2. ACL 使用规范化条目

授权事实来源是规范化 ACL 表，不是资源行上的字符串数组：

```text
projects 1 --- N resource_acl_entries

resource_acl_entries:
  org_id
  resource_type
  resource_id
  principal_type   user | group | role | org
  principal_id
  permission       read | write | manage
  granted_by_type / granted_by_id / granted_at
  revoked_by_type / revoked_by_id / revoked_at
```

`principal_type` 与 `principal_id` 分列保存，避免裸 id 在用户、群组和角色之间产生歧义。当前只实现 `project` 资源以及 `org`、`role`、`user` principal；群组未实现。每个组织、资源和 principal 同时最多一条当前有效授权，普通授权查询忽略 `revoked_at` 非空的历史条目。

搜索索引可以保存版本化 principal token 快照并建立 GIN 索引，但快照只用于查询加速：

- 成员、角色或 ACL 变化时必须失效或重建快照；
- 最终授权仍由规范化 ACL 和当前成员关系决定；
- 快照过期只能导致暂时拒绝或重建，不能独立授予访问；
- 权限过滤在检索前完成，禁止先取 Top-k 再在应用层过滤。

### 3. 审计日志只追加

`audit_logs` 至少包含：

```text
org_id, actor_type, actor_id, on_behalf_of,
action, resource_type, resource_id,
ip, user_agent, trace_id, metadata, created_at
```

审计记录只插入，不更新、不删除。Agent 必须以 `on_behalf_of` 用户身份行动并继承其权限。登录、资源读写、权限变化、搜索、Agent 工具调用、审批和费用均写审计。

### 4. 软删除与合规清除分开

- `deleted_at` 表示可恢复的普通删除；
- `purged_at` 和清除证据表示内容已按合规要求不可恢复地清除；
- 普通业务查询默认排除 `deleted_at` 非空记录；
- 清除流程必须覆盖数据库内容、对象存储、搜索索引和缓存，并保留不可反推原文的审计证据。

### 5. 知识资源与摄取幂等

当前已实现文件上传生成的项目知识资源、不可变版本、批次/item 状态和持久化摄取任务。上传会话 ID 是完成确认的幂等边界，SHA-256 绑定本次预签名传输；软删除只改变可见性，不冒充合规清除。

连接器后续仍必须以 `source_id + external_id + source_version` 形成摄取幂等边界，其外部来源删除传播尚未实现。

### 6. Embedding Profile 版本化

向量维度属于 Embedding Profile，不是全产品永久固定的全局配置：

```text
embedding_profiles:
  id, org_id/null, provider, model, dimensions,
  distance_metric, chunking_config, index_config,
  version, status

chunk_embeddings:
  chunk_id, embedding_profile_id, embedding
```

当前 Stage 3A 活动 profile 使用 OpenAI 兼容 Embedding 和严格的 1024 维向量。每个向量通过 `embedding_profile_id` 解释；不同模型、维度或距离度量不能混入同一个相似度索引。Worker preflight 与写入路径都会校验活动 profile、Provider、模型和维度。

更换模型或维度时创建新 profile，新旧向量在重建和灰度期间并存。启动与写入时校验实际向量维度符合 profile；失败的 attempt、job、批次 item 和资源版本只暴露稳定错误码与经过清洗的 `safe_detail`，不承诺返回 provider、model 或 profile 配置细节。

## 鉴权与 API 契约

### 目标：Cookie 与 Bearer 双模式

当前只实现 Web 的 Cookie 路径。Bearer、Refresh token 轮换、设备会话和凭据冲突策略均未实现。

| 客户端 | 凭据 | 存储 |
|---|---|---|
| Web/PWA | HttpOnly Cookie | 浏览器 Cookie 存储 |
| iOS/Android | `Authorization: Bearer` | Keychain/Keystore |
| Tauri/CLI/VS Code | Bearer 或受控 Cookie 会话 | 系统凭据存储 |

Cookie 路径启用 CSRF 防护；Bearer 路径不依赖浏览器自动携带凭据。Refresh token 轮换、撤销和设备会话管理对两种模式使用同一服务端策略。测试必须覆盖两条路径和凭据冲突时的确定优先级。

### 版本化契约

- 所有业务端点使用 `/api/v1` 前缀；
- FastAPI OpenAPI 是跨客户端网络契约的来源；
- TypeScript SDK 从 OpenAPI 生成，不手工维护第二套网络 DTO；
- Web、Tauri、Expo、VS Code 和 CLI 共享 SDK、事件契约与权限语义，不共享服务端业务实现；
- 创建运行、触发任务和外部副作用的命令支持幂等键；
- 列表使用稳定游标分页，错误响应包含机器错误码和 `traceId`。

### 跨端约束

- 业务规则和状态转换由服务端校验，客户端只做展示和即时输入校验；
- 当前上传协议使用单对象预签名 `PUT` 和 SHA-256 内容校验；分片、偏移查询和续传尚未实现；
- 普通进度和日志使用 SSE，多人实时编辑等双向场景才使用 WebSocket；
- 老版本客户端可能长期存在，破坏性契约变化必须通过新 API 版本演进。

## 后续模型与 Provider 设计

本节是下游设计约束；当前 API 不读取 Provider 配置，也不发起模型调用。

模型访问统一经过 LiteLLM Gateway 和 Cairn 策略层。Provider、模型、能力、上下文窗口、成本、数据边界和风险策略分开配置。

适配层必须统一：

1. 流式事件格式；
2. 错误分类与可重试性；
3. 上下文窗口和 token 用量；
4. 工具调用格式；
5. Embedding Profile 与向量维度；
6. 超时、取消、预算和审计字段。

企业生产部署必须明确区分官方 API、第三方中转和客户内网模型。Secret 不进入仓库、镜像或普通日志；模型调用记录 provider、model、版本、token、费用、trace 和数据策略结果。

## 暂不提前实现

当前只固定会造成数据迁移、权限漏洞或跨客户端返工的不变量。计费、多可用区、SCIM、按租户密钥和数据驻留策略在对应阶段实现，但接口和表结构不得阻塞后续加入这些能力。
