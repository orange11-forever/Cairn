<p align="center">
  <img src="./assets/brand/cairn-wordmark-v3.svg" width="340" alt="Cairn" />
</p>

<p align="center">
  面向软件研发团队的企业知识与研发协作平台
</p>

<p align="center">
  统一知识检索 · 项目任务图 · Agent 编排 · 多模型接入 · 企业私有部署
</p>

> [!IMPORTANT]
> Cairn 已在真实 PostgreSQL/pgvector 知识链路上交付项目范围单轮生成式知识问答。`verify:core` 使用确定性本地回答 Provider；`dev:core` 的问答需显式配置 `ANSWER_BASE_URL`、`ANSWER_API_KEY`、`ANSWER_MODEL`，并通过 `ANSWER_PROTOCOL` 选择协议，未配置时其他知识功能仍可用。浏览器验收覆盖上传、索引、混合搜索、生成回答、全文与引用定位及授权下载；默认验证不访问外网或真实 Provider。飞书单文档管理、手动与周期同步已通过本地模拟飞书验收，指定测试文档的真实同步、索引与项目读权限已通过隔离副本验收；实际上游撤权/删除仍待验收。流式/多轮问答和其他连接器仍在后续任务。
>
> 当前 Web 项目知识页采用 IDE 式工作台：左侧是资料与上传状态，中间是搜索、全文阅读和引用定位，右侧是岑宁单轮项目问答。“来源与同步”独立管理飞书接入。桌面、平板与手机均支持亮暗主题；切换区域保留草稿，切换项目或会话清理私有状态。使用与边界见 [工作台说明](docs/workbench.md)。

## 当前交付快照

更新日期：2026-10-04。身份、项目、任务、知识摄取、搜索及正文读取已连接真实 FastAPI、PostgreSQL/pgvector 和 MinIO；开发与默认验收使用本地确定性模型服务，外部模型需单独配置。

| 边界 | 当前状态 |
|---|---|
| Web | 三栏资料、内容与问答布局，实际项目切换、上传批次进度、资源状态、混合检索/关键词降级模式、资料详情、重试、删除和授权下载。验收覆盖 360、768、1280 像素及亮暗主题。查询和变更请求返回规范化 `401 session_invalid` 时，统一清理本地会话与查询缓存、重置变更缓存并回到登录页。 |
| 全文与引用 | Markdown、TXT、飞书文本快照阅读全文；支持标题、列表、代码复制、表格和文末状态。引用绑定版本与片段，定位并高亮对应段落、列表项或表格行，可回到引用；不支持格式保留纯文本引用上下文及授权下载。正文最多原始 1 MiB / 20,000 行，超限不截断；离线隐藏，恢复后手动重新读取。 |
| 账号 | 原生邮箱密码注册要求邮件验证与原密码确认，验证成功后显式登录。GitHub/飞书首次注册、身份绑定和再次登录已完成真实授权验收；原生注册已通过本机 SMTP 捕获验收，真实外部邮件投递仍待配置验收。 |
| API / SDK | FastAPI 已提供会话、注册、项目/任务、RBAC/ACL、知识摄取、资源、全文读取、混合搜索、带引用的单轮回答以及飞书来源登记/手动同步契约；生成 SDK 导出 OpenAPI schema 与运行时校验器，Web API 适配器检查身份、项目/任务和知识响应，并对 OpenAPI `date-time` 字段执行运行时校验。 |
| 项目知识问答 | 基于当前项目授权资料生成单轮回答；模型调用前后重新核验权限与证据，引用可展开上下文并授权下载。支持 Chat Completions、Responses、Claude Messages 和 Gemini GenerateContent 协议，真实厂商密钥联调仍需部署者完成。 |
| Worker | 独立 Worker 已进入知识摄取核心链路；Python Worker 通过 PostgreSQL 持久化任务完成受限归档、解析、切分、Embedding 与原子索引发布。 |
| 飞书单文档连接 | 管理员在 Web 登记来源并显式确认项目共享，可手动或每 5 分钟至一周同步、查看记录、停用和恢复。快照保存后仍需等待索引 ready；明确的上游撤权/删除在下次检查后隐藏旧内容。完整门禁和响应式浏览器验收已通过；指定测试文档的真实读取、同步、新版索引及项目只读权限已通过隔离副本验收。实际上游撤权/删除仍待验收。 |
| 基础设施 | 核心开发链路使用 PostgreSQL 16/pgvector 与 S3 兼容 MinIO；Redis、正式 Compose/Helm 部署和 OpenTelemetry 仍在规划。 |
| 延后 | 自定义助手、skills、助手/项目模型配置、项目分析、可执行规划、路线节点图与项目操作 Agent；流式/多轮问答、长期记忆、周期性资源详情轮询及其他连接器仍在后续任务。 |

## 下一阶段：可操作的项目助手

以下是后续开发方向：

- 自定义多个 AI 助手，配置名称、头像、行为说明和模型；岑宁作为默认可选助手。
- 助手可启用可复用的 skills，明确输入、输出、工具和权限；实际项目权限仍由服务端校验。
- 分析项目目标、资料、阶段、任务和依赖，生成有依据的风险判断、路线图及后续开发计划。
- 将规划落成真实阶段、里程碑、任务和依赖节点，并通过项目 API 执行用户指令，保留操作记录。

完整方向见 [项目助手、项目分析与路线节点图](docs/assistant-project-analysis-direction.md)。

## 账号登录方式

原生邮箱密码注册默认关闭，部署者启用注册并配置 SMTP 后可从登录页创建账号。提交申请后须打开邮件链接、输入原密码并明确确认，验证成功后再正常登录；完整步骤见 [原生邮箱注册](docs/native-registration.md)。本机捕获已验证注册和组织隔离流程，真实外部 SMTP 投递仍需单独验收。

GitHub 和飞书首次授权可在最终确认时注册独立个人账号及个人组织，邮箱可为空；已有 Cairn 账号也可显式绑定两种登录方式。账号归属使用已验证的提供方稳定身份，不按相同邮箱或名称合并，也不自动加入已有组织。
两家首次注册、绑定和再次登录已完成真实授权验收。部署者仍需配置自己的应用凭证和固定回调地址；功能默认关闭，配置步骤见 [OAuth 登录说明](docs/oauth-login.md)。飞书身份登录与资料来源接入分别配置，登录授权不自动授予文档读取权限。

## 多模型问答与飞书接入

项目知识页已提供单轮问答。模型协议由 `ANSWER_PROTOCOL` 配置，模型 ID、端点和密钥分别由 `ANSWER_MODEL`、`ANSWER_BASE_URL` 和 `ANSWER_API_KEY` 配置：

| 协议 | 接入目标 |
|---|---|
| `openai-compatible`（默认） | DeepSeek、Qwen、Kimi、GLM，以及支持 Chat Completions 的 GPT 模型或兼容服务 |
| `openai-responses` | GPT Responses |
| `anthropic` | Claude Messages |
| `gemini` | Gemini GenerateContent |

具体模型必须支持相应的结构化 JSON 输出。当前验收使用确定性本地 Provider 和协议测试，未使用各厂商真实密钥联网测试；更换模型时需验证目标模型的实际能力。配置与 API 边界见 [API 说明](apps/api/README.md)。

Stage 3B 首个切片为 Worker 包中的飞书新版文档读取客户端：自建应用凭证获取与缓存、指定文档的标题/版本/纯文本读取、有界响应、版本变化检测和安全失败分类。它是内部接入基础；项目知识页的管理员入口可登记并同步单个文档。前后版本检查不能保证飞书服务端原子快照。

Stage 3B 来源登记 API 接续读取基础：组织 owner/admin 可以登记飞书文档来源、绑定项目、分页查看并幂等停用。登记必须显式声明 `accessPolicy=project_members`，确认允许向有项目读取权限的成员共享；仅保存部署凭证引用，API 不接收密钥。`configured` 表示登记成功，不表示凭证已经验证或文档已经同步。来源变更、审计和项目 Outbox 在同一事务提交。

Worker 现可从唯一可选部署变量 `CAIRN_FEISHU_CREDENTIALS_JSON` 按组织 UUID 与不透明 `credentialRef` 精确解析凭证，并按次创建隔离的读取客户端；缺失配置不影响现有上传 Worker。已有知识内容读取、搜索、问答、重试、删除和索引发布会按当前 `project_members` 来源状态重新授权：停用后新请求立即不可见，索引发布与停用通过来源行锁串行化。解析器本身不授予权限；手动和周期同步、管理界面及明确的上游拒绝传播已通过本地模拟飞书验收，指定测试文档已通过隔离副本真实验收；实际上游撤权/删除仍待验收。使用方式见 [API 来源管理说明](apps/api/README.md#stage-3b-飞书项目来源登记)与 [Worker 说明](apps/worker/README.md)，范围与验收要求见[来源登记设计](docs/stage-3b-feishu-sources-design.md)、[凭证解析设计](docs/stage-3b-feishu-credentials-design.md)和[飞书读取基础设计](docs/stage-3b-feishu-reader-design.md)。

管理员还可通过来源同步端点手动排队单文档快照；`completed` 表示快照和资源版本已持久化且索引任务已排队，内容须待既有索引任务发布后可检索。同步按 revision/hash 幂等，拒绝复活软删除资源和发布较旧飞书 revision。管理界面与周期同步已通过本地模拟验收；不提供 webhook，因此上游变化只能在下次检查时被发现。

飞书接入配置与历史验收范围见[来源管理与周期同步验收](docs/stage-3b-feishu-completion-acceptance.md)。

## 项目与任务 API

所有端点都从受保护会话解析 `CurrentIdentity`。其中的组织是租户权威；客户端请求体不接受可信 `org_id`、创建者或 actor 字段。项目详情与任务读写对缺失或跨租户资源返回 `404 not_found`，隐藏普通资源的存在性。事件查询采用单独的非泄露语义：

- `events` 查询不存在的项目 ID：返回 `200` 空 `text/event-stream`，不泄露项目是否存在；
- `events` 查询跨租户项目 ID：返回 `200` 空 `text/event-stream`，同样不泄露项目是否存在。

| 操作 | 端点 | 已交付语义 |
|---|---|---|
| 创建、分页列出项目 | `POST /api/v1/projects`、`GET /api/v1/projects` | 创建项目；使用稳定不透明游标读取当前组织项目 |
| 读取项目 | `GET /api/v1/projects/{project_id}` | 仅返回当前组织中的项目 |
| 创建、分页列出任务 | `POST /api/v1/projects/{project_id}/tasks`、`GET /api/v1/projects/{project_id}/tasks` | 创建任务；在项目内使用稳定不透明游标分页 |
| 转换任务状态 | `PATCH /api/v1/tasks/{task_id}/status` | 由服务端状态机校验转换，不接受任意状态跳转 |
| 添加任务依赖 | `POST /api/v1/tasks/{task_id}/dependencies` | 请求体中的前置任务指向路由中的后继任务，形成 predecessor → successor |
| 查询项目事件 | `GET /api/v1/projects/{project_id}/events` | 按当前组织和项目 aggregate 过滤，返回一次最多 100 条、随后结束的 SSE 批次；不存在或跨租户 ID 均为空 `200` |
| 列出组织成员 | `GET /api/v1/organizations/{organization_id}/memberships` | `owner` 与 `admin` 可使用稳定游标分页读取当前组织成员 |
| 更新成员角色 | `PATCH /api/v1/organizations/{organization_id}/memberships/{membership_id}` | 按角色矩阵更新成员；最后一名 `owner` 不能被降级 |
| 列出项目 ACL | `GET /api/v1/projects/{project_id}/acl` | 需要项目 `manage` 权限；只列出当前有效条目 |
| 设置项目 ACL | `PUT /api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}` | 幂等设置 `read`、`write` 或 `manage` |
| 撤销项目 ACL | `DELETE /api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}` | 幂等撤销当前有效条目并保留历史行 |

`Project` 是阶段 2 的聚合根：任务创建、状态变化和依赖边都以所属项目作为 Outbox aggregate，项目事件查询也按组织与项目共同隔离。项目与任务列表的 `limit` 为 1–100，默认 50；响应通过 `nextCursor` 续页。

## 组织 RBAC 与项目 ACL

项目权限按 `read < write < manage` 递增：`write` 包含 `read`，`manage` 包含两者。创建项目时会授予当前组织 `read` 和创建者用户 `manage`；其他有效的 `org`、`role`、`user` ACL 取最高权限。角色矩阵如下：

| 组织角色 | 项目与成员能力 |
|---|---|
| `owner` | 对当前组织所有项目隐式拥有 `manage`；可创建项目、列出成员并更新任意成员角色 |
| `admin` | 对当前组织所有项目隐式拥有 `manage`；可创建项目、列出成员，只能在 `member` 与 `viewer` 之间切换角色 |
| `member` | 可创建项目；对其他项目仅拥有匹配 ACL 授予的权限，不能管理成员角色 |
| `viewer` | 不能创建项目；ACL 即使授予 `write` 或 `manage`，有效权限上限仍为 `read`，不能管理成员角色 |

项目详情、任务读写和 ACL 操作对不存在、跨组织或权限不足的项目统一返回 `404 not_found`，避免暴露项目存在性。成员列表对当前组织中无管理权的 `member`/`viewer` 返回 `403 forbidden`；跨组织或不可见的成员目标返回 `404 not_found`。降级最后一名所有者返回 `409 last_owner_required`。

Cookie 会话下的成员 `PATCH` 与 ACL `PUT`/`DELETE` 都要求合法 Origin 和会话绑定的 `X-CSRF-Token`。实际角色或 ACL 变化会把业务变更、追加式审计记录和 Outbox 事件放在同一事务提交；重复设置相同值和撤销不存在的 ACL 是无副作用的幂等成功，不新增审计或 Outbox 事件。

## 知识摄取、资源与搜索 API

项目授权边界内提供上传批次状态、资源列表/详情、全文读取、失败版本重试、软删除、下载重定向、切片引用上下文和项目范围混合搜索。知识资源的不存在、跨组织和权限不足统一使用不泄露的 `404 not_found`；所有变更端点和搜索 `POST` 在 Cookie 会话下都要求合法 Origin 和 `X-CSRF-Token`。下载会重新授权，然后返回指向短时效对象 URL 的 `307`。全文读取在存储 I/O 前后复核活跃用户、成员权限、来源与版本；引用通过 `version_id` 和 `chunk_id` 固定位置。

| 操作 | 端点 |
|---|---|
| 创建上传批次 | `POST /api/v1/projects/{project_id}/knowledge/uploads` |
| 确认单个直传对象 | `POST /api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete` |
| 查询批次处理状态 | `GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}` |
| 分页列出知识资源 | `GET /api/v1/projects/{project_id}/knowledge/resources` |
| 读取资源与最新版本 | `GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}` |
| 读取授权全文与引用定位 | `GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content` |
| 重试可重试的失败版本 | `POST /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/{version_id}/retry` |
| 软删除资源 | `DELETE /api/v1/projects/{project_id}/knowledge/resources/{resource_id}` |
| 重新授权并下载 | `GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download` |
| 读取命中切片及前后文 | `GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}` |
| 权限过滤的关键词/向量混合搜索 | `POST /api/v1/projects/{project_id}/knowledge/search` |
| 生成带核验引用的单轮回答 | `POST /api/v1/projects/{project_id}/knowledge/answers` |

## 显式延后

- 完整阶段/里程碑编辑 UI、React Flow/ELK 图编辑、拖拽 Kanban 和时间线可视化延后；
- Outbox worker 发布、长连接重连 SSE、Redis fan-out、评论、通知和任务执行延后；
- 群组、邀请和成员移除未实现；ACL 管理 UI 与成员管理 UI 未实现；
- Bearer/OIDC 延后；知识摄取、项目搜索和单轮生成式回答已交付。Markdown/TXT/飞书快照全文引用定位已交付。流式/多轮问答和周期性详情轮询仍在后续任务；飞书单文档周期同步和连接管理界面已通过本地模拟验收，指定测试文档的真实同步、索引与项目读权限已通过隔离副本验收；实际上游撤权/删除仍待验收。其他连接器、Agent 执行和完整模型 Provider 策略层尚未交付。

## 核心能力

| 能力 | 目标 |
|---|---|
| 企业智能搜索 | 从文档、代码、项目、任务、Agent 运行与产物中统一检索，并提供权限过滤和可追溯引用 |
| 项目与任务管理 | 使用阶段、里程碑、任务 DAG、依赖和验收标准规划并跟踪研发项目 |
| Agent 协作 | 将任务分配给人员、内置 Agent 或外部 Agent，统一管理运行、审批、预算与产物 |
| 实时进度 | 查看节点状态、日志、成本、阻塞关系和执行历史，并支持取消、恢复与重试 |
| 可视化产出 | 从结构化任务、依赖、代码和事件数据生成流程图、路线图与项目报告 |
| 多模型与跨平台 | 统一接入多种云端或内网模型，并覆盖 Web、桌面、移动端、VS Code 与 CLI |

## 技术栈

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/react/react-original.svg" width="42" height="42" alt="React" title="React" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/typescript/typescript-original.svg" width="42" height="42" alt="TypeScript" title="TypeScript" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/vitejs/vitejs-original.svg" width="42" height="42" alt="Vite" title="Vite" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/tauri/tauri-original.svg" width="42" height="42" alt="Tauri" title="Tauri" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/python/python-original.svg" width="42" height="42" alt="Python" title="Python" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/fastapi/fastapi-original.svg" width="42" height="42" alt="FastAPI" title="FastAPI" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/postgresql/postgresql-original.svg" width="42" height="42" alt="PostgreSQL" title="PostgreSQL" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/redis/redis-original.svg" width="42" height="42" alt="Redis" title="Redis" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/docker/docker-original.svg" width="42" height="42" alt="Docker" title="Docker" />
  &nbsp;
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.17.0/icons/kubernetes/kubernetes-original.svg" width="42" height="42" alt="Kubernetes" title="Kubernetes" />
</p>

为避免把路线图写成已完成功能，下表区分当前原型已经使用的技术与目标架构中的规划技术。

| 领域 | 技术选择 | 状态 |
|---|---|---|
| Web | React 19、TypeScript 5、Vite 7、Zod | 当前已使用 |
| Web 数据与图形 | React Router、TanStack Query、React Flow、ELK.js、Mermaid | Router/Query 当前已使用；其余规划 |
| 桌面与移动 | Tauri、React Native、Expo | 规划 |
| API | Python 3.12、FastAPI、Pydantic Settings、Uvicorn | 当前已使用 |
| API 数据访问 | SQLAlchemy 2、Alembic | 当前已使用 |
| 数据与文件 | PostgreSQL、pgvector、Redis、S3/MinIO | PostgreSQL 16/pgvector 与 S3 兼容 MinIO 当前已使用；Redis 规划 |
| 后台摄取 | Python Worker、PostgreSQL 持久化任务、结构化解析与切分 | 当前已使用 |
| 工作流与 Agent | Temporal、LangGraph、AgentRunner | 规划 |
| 模型接入 | OpenAI 兼容 Embedding；LiteLLM Gateway 与 Cairn 模型策略层 | 1024 维 Embedding 当前已使用；完整策略层规划 |
| 实时与可观测 | Transactional Outbox、SSE、OpenTelemetry | Outbox 与有界 SSE 查询当前已使用；OpenTelemetry 规划 |
| 部署 | Local Web、Docker Compose、Kubernetes/Helm | Docker Compose 当前用于核心开发；正式部署规划 |
| 测试与工具 | pnpm、Vitest、Testing Library、Playwright；uv、pytest、Ruff、Pyright | 当前已使用 |

## 架构

当前实现、目标组件、安全不变量与阶段路线见 [公开架构说明](docs/architecture.md)。文档中的“当前已交付”和“规划”状态是功能边界，不应互相替代。

## 项目结构

以下目录树只列出公开维护的源码、测试与工程入口，不包含私有文档、依赖缓存和构建产物。

```text
Cairn
├── apps/
│   ├── api/                  # FastAPI 工程基线
│   │   ├── src/cairn_api/    # API 应用、配置、中间件与错误契约
│   │   └── tests/            # pytest 测试
│   ├── web/                  # React/Vite Web 原型
│   │   ├── scripts/          # Web 测试、构建与浏览器验收脚本
│   │   ├── src/              # 页面、组件、查询、会话与数据契约
│   │   ├── styles/           # 全局样式
│   │   └── tests/            # Node 契约测试与 React 组件测试
│   └── worker/               # 知识摄取 Worker、解析器、切分、Embedding 与索引
├── packages/
│   └── sdk/                  # 从 FastAPI OpenAPI 生成的身份、项目任务与知识客户端
├── assets/brand/             # Cairn 品牌图片
├── deploy/compose/           # PostgreSQL/pgvector 与 MinIO 核心开发基础设施
├── scripts/                  # 跨 package 的任务编排与进程工具
├── package.json              # 根命令与 Node.js 工程约束
├── pnpm-workspace.yaml       # pnpm workspace 定义
├── pyproject.toml            # Python workspace 与工具配置
└── uv.lock                   # Python 依赖锁文件
```

## 最终部署形式

正式 Local Web、单服务器私有部署和 Kubernetes 私有部署将共享同一套 API、数据库迁移和应用镜像。当前核心开发链路已有真实 API、PostgreSQL/pgvector、MinIO、独立 Worker 和 Web；项目与项目知识操作连接真实 API，正式部署能力仍在建设中。

| 形式 | 默认入口 | 定位 |
|---|---|---|
| Local Web | `http://127.0.0.1:8080` | 本机一条命令启动真实 Web、API 和持久化依赖 |
| Docker Compose | 企业域名或内网地址 | 中小企业单服务器私有部署 |
| Kubernetes/Helm | 企业 Ingress 或网关 | 集群、高可用和外部基础设施接入 |
| 隔离网络 | 内网地址 | Compose/Helm 配合私有镜像仓库、内网模型和离线安装包 |

## 当前核心开发

环境要求：Node.js 22+、pnpm 10+、Python 3.12+、uv 和已启动的 Docker Desktop。

首次安装并启动：

```bash
pnpm install
uv sync --all-packages --all-groups
pnpm infra:up
pnpm dev:core
```

`pnpm infra:up` 启动 PostgreSQL 16/pgvector 和 MinIO，并幂等初始化对象存储 bucket 与 CORS。`pnpm dev:core` 随后执行迁移、对象存储与活动 Embedding Profile 幂等初始化和演示种子，并托管本地假 Embedding、API、Worker 与 Web。Worker 也可独立调试：

```bash
pnpm worker:preflight
pnpm dev:worker
```

`pnpm worker:preflight` 只校验数据库、对象存储和当前 Embedding Profile/Provider 依赖；`pnpm dev:worker` 持续处理任务。调试一个当前可租用任务时使用 `pnpm worker:once`。

项目问答需配置前述 `ANSWER_*` 服务端变量；原生注册和第三方登录分别按对应文档配置。仅运行 `pnpm dev:web` 会启动 Web，完整上传、索引和资料读取请使用 `pnpm dev:core`。

- 登录：`http://localhost:5500`
- 登录后进入 `/projects`；旧 `/documents` 和 `/ask` 书签重定向到项目工作台。
- Web：`http://localhost:5500`
- Identity API：`http://127.0.0.1:8080`

`pnpm dev:core` 会等待假 Embedding、API 和 Web 就绪，并把 Worker 或其他子进程的提前退出视为失败。演示身份只允许在开发或测试环境写入；生产环境会拒绝演示种子、示例 CSRF 密钥和不安全 Cookie。按 `Ctrl+C` 停止该命令会终止其托管的全部子进程，不删除 PostgreSQL 或 MinIO 开发卷；再次启动会复用已有数据。

若本机 5432 已被其他 PostgreSQL 占用，可让 `CAIRN_POSTGRES_PORT` 与 `DATABASE_URL` 同时改用同一个空闲端口；不要只改其中一项。

生产环境必须使用 HTTPS `APP_URL`/`CORS_ORIGINS`、安全 Cookie，并分别配置至少 32 字节且不能复用的 `CAIRN_CSRF_SECRET` 与 `CAIRN_AUTH_RATE_LIMIT_SECRET`。生产配置会拒绝示例密钥、HTTP Origin 和不安全 Cookie。只有直接连接且受信任的反向代理才能写入转发链；将其网段以逗号分隔配置到 `CAIRN_TRUSTED_PROXY_CIDRS`，并确保代理覆盖客户端提交的 `Forwarded`/`X-Forwarded-*` 请求头。

## 当前 API 基线

环境要求：Python 3.12+、uv。

独立调试 API 时可运行：

```bash
uv sync --all-packages --all-groups
pnpm dev:api
```

- API：`http://127.0.0.1:8080`
- 存活探针：`http://127.0.0.1:8080/health`
- 版本探针：`http://127.0.0.1:8080/api/v1`
- OpenAPI：`http://127.0.0.1:8080/docs`

API 现已提供 PostgreSQL 与对象存储 readiness、登录、会话恢复、注销、当前组织、项目任务、成员角色、项目 ACL 与上述知识资源和混合搜索接口。登录失败限制由 PostgreSQL 持久化：同一规范化邮箱在 15 分钟窗口内最多失败 5 次，同一来源 IP 最多失败 30 次，达到阈值后阻止 15 分钟；表中仅保存使用 `CAIRN_AUTH_RATE_LIMIT_SECRET` 生成的 HMAC 摘要，不保存明文邮箱或 IP。项目知识页真实上传使用 Identity API 与对象存储。

当前切片不包含 Bearer/OIDC、群组、邀请、成员移除、ACL/成员管理 UI、流式/多轮问答、周期性资源详情轮询、其他连接器、Agent 任务执行或完整 AI Provider 策略层。

可按需清理过期或已撤销的认证状态：

```bash
pnpm auth:cleanup
```

该命令分批、幂等删除过期/已撤销会话与失效限流桶，保留有效会话、活动限流窗口和全部审计记录；数据库错误会返回非零退出码。

## 质量检查

```bash
pnpm typecheck
pnpm test
pnpm build
pnpm test:worker
pnpm lint:worker
pnpm typecheck:worker
pnpm verify:core
pnpm verify
```

`pnpm verify:core` 会创建独立 Compose project 和临时 PostgreSQL/MinIO 卷，执行迁移、对象存储与活动 Embedding Profile 初始化、API/Worker 集成测试和 SDK 漂移检查，然后启动本地假 Embedding、API 与 Worker。Chromium 通过真实签名 PUT 上传中英文文本，等待 Worker 发布索引，再验证混合搜索、行号引用上下文和授权下载。最后一段验收继续验证生产构建和 HTTPS 反向代理后的 CORS、Cookie、CSRF 与可信来源 IP。临时证书、进程及 Compose project 会在成功、失败或信号中断后清理；该命令不会接触开发数据库和卷，也不使用外部 Provider 或真实密钥。

`pnpm verify` 是完整的跨 package 门禁：它覆盖 OpenAPI 生成 SDK 测试与漂移检查、Web、API、Worker、Ruff、Pyright、发行包构建与最后的真实核心验证。浏览器部分使用生产构建，覆盖登录、刷新恢复、组织显示、注销、兼容路由、360/768/1280 像素布局、亮暗主题、真实项目与项目知识导航、上传、搜索、全文与引用定位、长列表/表格引用、引用上下文、资源重试/删除、长内容换行、触摸目标、无横向溢出和品牌像素契约。Worker package 测试覆盖租约、归档、解析、切分、Embedding 与原子索引语义；真实核心验证覆盖 pgvector、MinIO 签名对象往返、Worker 摄取、项目范围混合搜索和知识 API/SDK 一致性。

也可以使用 `pnpm test:sdk`、`pnpm typecheck:sdk`、`pnpm check:sdk`、`pnpm test:web`、`pnpm test:api`、`pnpm typecheck:web`、`pnpm typecheck:api`、`pnpm test:worker`、`pnpm lint:worker`、`pnpm typecheck:worker`、`pnpm build:web` 和 `pnpm build:api` 分别检查单个 package 或生成契约。

## 开源许可证

Cairn 采用 [ISC License](LICENSE) 开源。
