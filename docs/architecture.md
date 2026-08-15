# Cairn 架构

本文只描述公开、稳定的架构边界，并明确区分当前已交付能力与目标能力。路线图中的组件不代表已经实现。

## 当前已交付

- React 19、TypeScript 与 Vite 构成 Web 客户端；身份、项目和任务请求连接真实 FastAPI，文档、上传和问答仍连接 Node mock。
- FastAPI 采用模块化单体边界，提供 Cookie 会话、组织身份与 RBAC、项目 ACL、成员角色管理、项目任务、追加式审计、事务性 Outbox、有界 SSE，以及项目授权下的知识上传与资源生命周期 API。
- PostgreSQL 16/pgvector 与 S3 兼容 MinIO 当前已使用：PostgreSQL 保存业务事实、持久化摄取任务、知识资源、切片和向量，MinIO 保存原始对象与 ZIP 展开产物；生成的 TypeScript SDK 对齐 OpenAPI。Redis 仍是规划中基础设施。
- Stage 3A Task 1–11 的独立 Worker 已交付，用租约和心跳处理受限归档展开、文档解析、结构化切分、OpenAI 兼容 1024 维 Embedding 与原子索引发布。
- Task 12 项目范围混合搜索未交付；群组、邀请、成员移除、ACL/成员管理 UI、真实 Web 知识工作区、连接器、Agent 执行和完整模型 Provider 策略层也尚未实现。

## 目标架构

- API 处理同步命令、查询、租户与权限边界；已交付的独立 Worker 处理知识摄取、解析和索引，Outbox 发布与其他异步工作仍按后续需求扩展。
- PostgreSQL 是业务事实来源；S3/MinIO 保存原始对象和派生产物；Redis 只用于可丢失的缓存、协调或实时扇出，Redis 不是真实数据来源。
- 当前知识层以 Resource 和 ResourceVersion 表达逻辑资源与不可变版本，并保留来源、校验和、解析及索引状态。
- Task 12 搜索必须先执行规范化 ACL 过滤，再进行关键词或向量召回；引用必须能追溯到资源版本和片段。

## 安全与数据不变量

1. `org_id` 是所有租户数据访问的第一过滤条件，客户端不能声明可信租户、actor 或创建者。
2. 规范化 ACL 和当前成员关系是授权事实来源；权限在数据库查询中预过滤，任何搜索、问答或 Agent 工具都不能先取回跨权限内容再在应用层遮盖。
3. 审计日志追加写入，不通过普通业务路径更新或删除。
4. 业务写入、审计记录与 Outbox 事件在同一事务提交。
5. 普通删除使用可审计的软删除；物理清除是独立、显式且受权限约束的流程。
6. 外部资源同步以 `source_id`、`external_id` 和 `source_version` 保持幂等。
7. 向量与索引记录携带版本化 embedding profile；模型或分块策略变化不覆盖旧索引事实。

## 阶段路线

- 阶段 2.5.0：许可证、公开架构、跨平台仓库规则与受 CI 保护的 PR 流程。
- 阶段 2.5A：RBAC/ACL（已交付），包含组织角色、项目 ACL、成员角色 API、concealment、CSRF，以及权限变化与审计/Outbox 的事务一致性。
- Stage 3A Task 1–11：知识摄取基础（已交付），包含 Worker、S3/MinIO、Resource/ResourceVersion、解析、分块、Embedding 与原子索引发布。
- Stage 3A Task 12：项目范围混合搜索（未交付），后续实现检索前权限过滤和关键词/向量混合召回。

后续 Agent、模型 Provider 和工作流能力必须建立在租户、权限、审计和知识边界之上，不能绕过这些基础能力提前接入生产数据。
