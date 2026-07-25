# apps/api — FastAPI 后端

**从 Day 16 开始建。** 现在是空占位。

Day 1-15 期间前端对接的是 `mocks/docs-server.mjs`，契约由 `apps/web/src/api/` 那一层定义。

计划落地顺序：

| Day | 内容 |
|---|---|
| 16 | ASGI 骨架、配置、日志、`/health`、OpenAPI、CORS 白名单、统一异常响应 |
| 17 | PostgreSQL + SQLAlchemy 2.x + Alembic；六张表建迁移 |
| 18 | 密码哈希、Access/Refresh Token、令牌轮换、RBAC、资源归属校验 |
| 19 | 文档/对话/消息 CRUD、分页、上传校验（MIME + 大小） |
| 20 | pytest fixture、依赖覆盖、事务隔离、权限隔离测试、种子数据 |

**Day 17 建表时的硬约束**（见记忆 `tracebase-phase2-enterprise-search`）：
`documents` 直接建成通用 `resources` 表，带 `source_type` / `source_id` /
`external_id`（与 source_id 组唯一约束，保证摄取幂等）/ `source_updated_at` /
`acl_principals text[]` + GIN 索引 / `metadata JSONB`。
当时只有 `upload` 一个来源，这些列看着像废字段，但事后补要重写迁移和全部检索 SQL。
