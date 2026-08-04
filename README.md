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
> Cairn 当前处于阶段 1 基础建设。现阶段核心开发链路已包含真实 PostgreSQL 16、FastAPI Cookie 身份接口、React/Vite Web 和仍承载文档原型的 Node mock；知识摄取、完整权限与 AI Provider 仍在后续阶段建设。

## 阶段 1 基础进度

共享 API 契约、响应式 Web 与真实身份基础已经完成。

- `@cairn/contracts` 统一现有登录、文档、问答、上传和错误响应契约；
- Web 保留本地容错、请求取消、查询缓存和 UI 状态边界；
- 工作台支持 360、768、1280 像素布局，以及日间、夜间和跟随系统偏好；
- 导航壳可扩展到知识、项目、执行和治理模块，但当前只开放已有页面；
- 组织、用户、成员、Cookie 会话和审计写入 PostgreSQL，Web 身份请求连接 FastAPI；
- 文档、上传和问答仍连接 Node mock API，不代表知识系统已经完成。

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
| 实时与可观测 | Transactional Outbox、SSE、OpenTelemetry | 规划 |
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
│   └── worker/               # 后续异步任务 Worker 的预留边界
├── packages/
│   ├── contracts/            # 共享运行时契约（文档原型）
│   └── sdk/                  # 从 FastAPI OpenAPI 生成的身份客户端
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

生产环境必须替换 `.env.example` 中的数据库密码和 `CAIRN_CSRF_SECRET` 示例值；生产配置会拒绝示例密钥和不安全 Cookie。

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

API 现已提供 PostgreSQL readiness、登录、会话恢复、注销和当前组织接口。文档、上传和问答仍由 Node mock 提供。

当前切片不包含 Bearer/OIDC、登录限流、完整 RBAC/ACL、项目、知识摄取、知识端点或 AI Provider。AI Provider 与外部 Agent 接入必须建立在组织、权限、审计、项目和知识基础完成之后，不能绕过这些边界提前扩展。

## 质量检查

```bash
pnpm typecheck
pnpm test
pnpm build
pnpm verify:core
pnpm verify
```

`pnpm verify:core` 会创建独立 PostgreSQL project 和临时卷，执行迁移、真实身份集成测试、SDK 漂移检查、生产构建与 Chromium 登录闭环，并在成功、失败或信号中断后删除该验证 project。它不会接触开发数据库和卷。

`pnpm verify` 是完整的跨 package 门禁：它覆盖共享契约、SDK、Web、API、Ruff、Pyright、发行包构建与最后的真实核心验证。浏览器部分覆盖错误密码、登录、刷新恢复、组织显示、注销、360/768/1280 像素布局、主题、路由保护、会话隔离、并发取消、文档状态、筛选、上传、提问和自动滚动；生产构建还会检查开发凭据和 Mock 场景控件没有进入产物。

也可以使用 `pnpm test:contracts`、`pnpm typecheck:contracts`、`pnpm test:web`、`pnpm test:api`、`pnpm typecheck:web`、`pnpm typecheck:api`、`pnpm build:web` 和 `pnpm build:api` 分别检查单个 package。
