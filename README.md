<h1 align="center">Cairn</h1>

<p align="center">
  面向软件研发团队的企业知识、项目任务与 Agent 协作平台
</p>

<p align="center">
  权限感知搜索 · 项目任务图 · Agent 编排 · 多模型接入 · 企业私有部署
</p>

> [!IMPORTANT]
> Cairn 当前处于阶段 0：仓库与工程基线重建。现阶段可运行内容是 React/Vite 前端原型与 Node mock API，用于保留交互和测试基线；FastAPI、真实数据层和正式 Local Web 仍在后续阶段建设。

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
| Web 数据与图形 | React Router、TanStack Query、React Flow、ELK.js、Mermaid | 规划 |
| 桌面与移动 | Tauri、React Native、Expo | 规划 |
| API | Python、FastAPI、Pydantic、SQLAlchemy 2、Alembic | 规划 |
| 数据与文件 | PostgreSQL、pgvector、Redis、S3/MinIO | 规划 |
| 工作流与 Agent | Temporal、LangGraph、AgentRunner | 规划 |
| 模型接入 | LiteLLM Gateway 与 Cairn 模型策略层 | 规划 |
| 实时与可观测 | Transactional Outbox、SSE、OpenTelemetry | 规划 |
| 部署 | Local Web、Docker Compose、Kubernetes/Helm | 规划 |
| 测试与工具 | pnpm、Vitest、Testing Library、Playwright；uv、pytest、Ruff、Pyright | 前端已使用，Python 侧规划 |

## 最终部署形式

正式 Local Web、单服务器私有部署和 Kubernetes 私有部署将共享同一套 API、数据库迁移和应用镜像。当前阶段只有下方的 Vite + mock 原型，正式交付能力仍在建设中。

| 形式 | 默认入口 | 定位 |
|---|---|---|
| Local Web | `http://127.0.0.1:8080` | 本机一条命令启动真实 Web、API 和持久化依赖 |
| Docker Compose | 企业域名或内网地址 | 中小企业单服务器私有部署 |
| Kubernetes/Helm | 企业 Ingress 或网关 | 集群、高可用和外部基础设施接入 |
| 隔离网络 | 内网地址 | Compose/Helm 配合私有镜像仓库、内网模型和离线安装包 |

## 当前原型开发

环境要求：Node.js 22+、pnpm 10+。

安装依赖：

```bash
pnpm install
```

分别在两个终端启动 mock API 与 Web：

```bash
pnpm mock
```

```bash
pnpm dev
```

- Web：`http://localhost:5500`
- Mock API：`http://localhost:8787`

## 质量检查

```bash
pnpm typecheck
pnpm test
pnpm build
pnpm verify
```

`pnpm verify` 会启动真实浏览器，验证登录、文档状态、筛选、上传、提问、取消和自动滚动等关键流程。

## 设计文档

- [Cairn 平台重构设计](docs/specs/2026-07-31-cairn-platform-reorientation-design.md)：产品边界、系统架构、数据不变量、技术栈、部署模型与阶段路线。
