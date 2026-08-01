# apps/api: FastAPI 后端

当前处于阶段 0。`apps/api` 是根 uv workspace 中可安装、可独立启动的 FastAPI package，现已提供配置、请求 ID、统一错误、健康检查、版本探针和 OpenAPI 骨架，并将在阶段 1-6 逐步承载企业基础、任务图、智能搜索、Agent 执行和治理能力。

现有 Web 原型仍连接 `mocks/docs-server.mjs`。当前产品、架构和阶段路线以 [`docs/specs/2026-07-31-cairn-platform-reorientation-design.md`](../../docs/specs/2026-07-31-cairn-platform-reorientation-design.md) 为准。

Local Web、Compose 与 Helm 必须使用同一 `/api/v1` 契约、数据库迁移和权限规则。Local Web 默认绑定 `127.0.0.1:8080`；它不是当前的 Vite + mock 原型，也不使用 SQLite 分叉。

## 当前工程命令

在仓库根目录运行：

```bash
uv sync --all-packages --all-groups
pnpm dev:api
uv run --package cairn-api pytest
uv run --package cairn-api ruff check apps/api/src apps/api/tests
uv run --package cairn-api pyright
uv build --package cairn-api
```

API 默认监听 `127.0.0.1:8080`，提供 `/health`、`/api/v1`、`/docs` 和 `/openapi.json`。当前 package 只是无外部服务依赖的 FastAPI 工程基线，不能称为正式 Local Web 或业务 API。

## 实施顺序

| 阶段 | API 侧主要交付 |
|---|---|
| 0 | FastAPI 骨架、`/health`、`/api/v1`、统一错误、OpenAPI SDK、测试和 CI |
| 1 | 组织、成员、Cookie/Bearer 双鉴权、RBAC、ACL、审计和 PostgreSQL 迁移 |
| 2 | 项目与任务 DAG、状态机、Outbox 和 SSE 查询模型 |
| 3 | 通用资源、对象存储、摄取状态、权限感知搜索和引用 |
| 4 | Agent、模型策略、运行、预算、审批与 AgentRunner 契约 |
| 5-6 | 外部编程 Agent、代码智能、OIDC/SAML、配额、审计查询和部署治理 |

## 数据模型不变量

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
resources 1 --- N resource_acl_entries

resource_acl_entries:
  org_id
  resource_id
  principal_type   user | group | role | org
  principal_id
  permission       read | write | manage
  created_at
  revoked_at
```

`principal_type` 与 `principal_id` 分列保存，避免裸 id 在用户、群组和角色之间产生歧义。唯一约束至少覆盖组织、资源、principal 和 permission，普通授权查询忽略 `revoked_at` 非空的条目。

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

### 5. 通用资源与摄取幂等

上传文档、GitHub 内容、项目、任务和 Agent 产物通过通用资源模型进入知识层。资源至少记录 `source_type`、`source_id`、`external_id`、`source_updated_at`、`metadata` 和处理状态。

`source_id + external_id + source_version` 形成摄取幂等边界。外部来源删除必须传播到资源、切片和搜索索引。

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

首个 profile 可以使用 1024 维，以降低首版检索和评估复杂度。每个向量必须通过 `embedding_profile_id` 解释；不同模型、维度或距离度量不能混入同一个相似度索引。

更换模型或维度时创建新 profile，新旧向量在重建和灰度期间并存。启动与写入时校验实际向量维度符合 profile，失败时返回可定位到 provider、model 和 profile 的错误。

## 鉴权与 API 契约

### Cookie 与 Bearer 双模式

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
- 列表使用稳定游标分页，错误响应包含机器错误码和 `trace_id`。

### 跨端约束

- 业务规则和状态转换由服务端校验，客户端只做展示和即时输入校验；
- 上传协议预留分片、偏移查询、续传和内容校验；
- 普通进度和日志使用 SSE，多人实时编辑等双向场景才使用 WebSocket；
- 老版本客户端可能长期存在，破坏性契约变化必须通过新 API 版本演进。

## 模型与 Provider

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
