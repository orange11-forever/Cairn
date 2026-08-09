<p align="center">
  <img src="./assets/brand/cairn-wordmark.png" width="560" alt="Cairn" />
</p>

<p align="center">
  面向软件研发团队的企业知识与研发协作平台
</p>

<p align="center">
  统一知识检索 · 项目任务图 · Agent 编排 · 多模型接入 · 企业私有部署
</p>

> [!IMPORTANT]
> Cairn 已完成阶段 2 的项目任务基础。当前核心开发链路包含真实 PostgreSQL 16、FastAPI Cookie 身份与项目任务 API、React/Vite Web 项目视图，以及仍承载文档原型的 Node mock；知识摄取、完整权限与 AI Provider 仍在后续阶段建设。

## 阶段 2 已完成边界

共享 API 契约、响应式 Web 与真实身份基础已经完成。阶段 2 在此基础上已交付项目、任务、依赖、状态机、事务性 Outbox 和有界 SSE 查询基础。

- `@cairn/contracts` 统一现有登录、文档、问答、上传和错误响应契约；
- Web 保留本地容错、请求取消、查询缓存和 UI 状态边界；
- 工作台支持 360、768、1280 像素布局，以及日间、夜间和跟随系统偏好；
- 已登录用户可在 Web 项目视图中查看游标分页的项目和任务，并通过服务端状态机更新任务状态；
- 组织、用户、成员、Cookie 会话、登录限流状态和审计写入 PostgreSQL，Web 身份请求连接 FastAPI；
- 项目、任务、依赖、审计行和 Outbox 事件写入 PostgreSQL；每次已接受的命令在同一事务中提交业务变更、审计记录和事件；
- 文档、上传和问答仍连接 Node mock API，不代表知识系统已经完成。

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

`Project` 是阶段 2 的聚合根：任务创建、状态变化和依赖边都以所属项目作为 Outbox aggregate，项目事件查询也按组织与项目共同隔离。项目与任务列表的 `limit` 为 1–100，默认 50；响应通过 `nextCursor` 续页。

显式延后：

- 完整阶段/里程碑编辑 UI、React Flow/ELK 图编辑、拖拽 Kanban 和时间线可视化延后；
- Outbox worker 发布、长连接重连 SSE、Redis fan-out、评论、通知和任务执行延后；
- Bearer/OIDC、现有成员边界以外的 RBAC/ACL、知识摄取/搜索、Agent 执行和模型 Provider 延后。

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
| 数据与文件 | PostgreSQL、pgvector、Redis、S3/MinIO | PostgreSQL 16 当前已使用；其余规划 |
| 工作流与 Agent | Temporal、LangGraph、AgentRunner | 规划 |
| 模型接入 | LiteLLM Gateway 与 Cairn 模型策略层 | 规划 |
| 实时与可观测 | Transactional Outbox、SSE、OpenTelemetry | Outbox 与有界 SSE 查询当前已使用；OpenTelemetry 规划 |
| 部署 | Local Web、Docker Compose、Kubernetes/Helm | Docker Compose 当前用于核心开发；正式部署规划 |
| 测试与工具 | pnpm、Vitest、Testing Library、Playwright；uv、pytest、Ruff、Pyright | 当前已使用 |

## 项目结构

以下目录树只列出公开维护的源码、测试与工程入口，不包含私有文档、依赖缓存和构建产物。

```text
Carin
├── apps/
│   ├── api/                  # FastAPI 工程基线
│   │   ├── src/cairn_api/    # API 应用、配置、中间件与错误契约
│   │   └── tests/            # pytest 测试
│   ├── web/                  # React/Vite Web 原型
│   │   ├── mocks/            # Node mock API
│   │   ├── scripts/          # Web 测试、构建与浏览器验收脚本
│   │   ├── src/              # 页面、组件、查询、会话与数据契约
│   │   ├── styles/           # 全局样式
│   │   └── tests/            # Node 契约测试与 React 组件测试
│   └── worker/               # 后续 Outbox/异步任务 Worker 的预留边界
├── packages/
│   ├── contracts/            # 共享运行时契约（文档原型）
│   └── sdk/                  # 从 FastAPI OpenAPI 生成的身份与项目任务客户端
├── assets/brand/             # Cairn 品牌图片
├── deploy/compose/           # PostgreSQL 核心开发基础设施
├── scripts/                  # 跨 package 的任务编排与进程工具
├── package.json              # 根命令与 Node.js 工程约束
├── pnpm-workspace.yaml       # pnpm workspace 定义
├── pyproject.toml            # Python workspace 与工具配置
└── uv.lock                   # Python 依赖锁文件
```

## 最终部署形式

正式 Local Web、单服务器私有部署和 Kubernetes 私有部署将共享同一套 API、数据库迁移和应用镜像。当前核心开发链路已有真实 API、PostgreSQL 和 Web，文档类操作暂由 Node mock 承载；正式部署能力仍在建设中。

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

- 登录：`http://localhost:5500`
- Web：`http://localhost:5500`
- Identity API：`http://127.0.0.1:8080`
- Mock API：`http://localhost:8787`

`pnpm dev:core` 会先执行迁移和幂等演示种子，再托管 API、Mock 与 Web 三个进程。演示身份只允许在开发或测试环境写入；生产环境会拒绝演示种子、示例 CSRF 密钥和不安全 Cookie。按 `Ctrl+C` 停止该命令只终止 API、Mock 与 Web，不删除 PostgreSQL 开发卷；再次启动会复用已有数据。`pnpm dev:web` 与 `pnpm mock:web` 仍可用于底层调试，但原来的双终端 mock-only 流程不再是核心开发路径。

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

API 现已提供 PostgreSQL readiness、登录、会话恢复、注销、当前组织以及项目任务接口。登录失败限制由 PostgreSQL 持久化：同一规范化邮箱在 15 分钟窗口内最多失败 5 次，同一来源 IP 最多失败 30 次，达到阈值后阻止 15 分钟；表中仅保存使用 `CAIRN_AUTH_RATE_LIMIT_SECRET` 生成的 HMAC 摘要，不保存明文邮箱或 IP。文档、上传和问答仍由 Node mock 提供。

当前切片不包含 Bearer/OIDC、完整 RBAC/ACL、知识摄取、知识端点、任务执行或 AI Provider。AI Provider 与外部 Agent 接入必须建立在组织、权限、审计、项目和知识基础完成之后，不能绕过这些边界提前扩展。

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
pnpm verify:core
pnpm verify
```

`pnpm verify:core` 会创建独立 PostgreSQL project 和临时卷，执行迁移、真实身份集成测试、SDK 漂移检查、生产构建与 Chromium 登录闭环。最后一段验收会用 OpenSSL 生成仅供本次运行使用的 localhost 证书，在 HTTPS 反向代理后启动生产配置 API，并验证 CORS、Secure/HttpOnly/SameSite Cookie、会话恢复、CSRF 注销和可信来源 IP。临时证书、进程及 Compose project 会在成功、失败或信号中断后清理；该命令不会接触开发数据库和卷。

`pnpm verify` 是完整的跨 package 门禁：它覆盖共享契约、SDK、Web、API、Ruff、Pyright、发行包构建与最后的真实核心验证。浏览器部分覆盖错误密码、登录、刷新恢复、组织显示、注销、360/768/1280 像素布局、主题、路由保护、会话隔离、并发取消、文档状态、筛选、上传、提问和自动滚动；生产构建还会检查开发凭据和 Mock 场景控件没有进入产物。

也可以使用 `pnpm test:contracts`、`pnpm typecheck:contracts`、`pnpm test:web`、`pnpm test:api`、`pnpm typecheck:web`、`pnpm typecheck:api`、`pnpm build:web` 和 `pnpm build:api` 分别检查单个 package。
