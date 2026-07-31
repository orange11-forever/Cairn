# Cairn

Cairn 是面向软件研发团队的企业知识、项目任务与 Agent 协作平台，支持企业私有部署。

## 当前状态

仓库正处于阶段 0：仓库与工程基线重建。当前可运行内容仍是 React/Vite 前端原型和 Node mock API；它们作为后续迁移的行为基线保留，不代表最终架构已经完成。

## 本地运行

需要 Node.js 22+、pnpm 10+。

```bash
pnpm install
pnpm mock
pnpm dev
```

Web 默认地址为 `http://localhost:5500`，mock API 默认端口为 `8787`。

## 验证

```bash
pnpm typecheck
pnpm test:unit
pnpm test:react
pnpm build
pnpm verify
```

## 当前架构方向

- React + Vite Web/PWA，Tauri 桌面端，Expo 移动端；
- FastAPI、PostgreSQL、pgvector、Redis、S3/MinIO；
- Temporal 负责长期业务编排，LangGraph 负责内置 Agent 运行时；
- LiteLLM Gateway 统一多模型接入，AgentRunner 接入外部 Agent；
- Docker Compose 与 Kubernetes/Helm 使用同一组服务镜像；
- 企业智能搜索是横向核心能力，并与项目、任务、代码和 Agent 上下文打通。

## 文档

- 当前产品、架构与阶段路线：[Cairn 平台重构设计](docs/specs/2026-07-31-cairn-platform-reorientation-design.md)
- 本次仓库清理边界：[仓库清理设计](docs/specs/2026-07-31-repository-cleanup-design.md)
- 历史原型与旧路线：[`docs/archive/`](docs/archive/)
