# Stage 3B：飞书项目来源登记

日期：2026-09-19。接续飞书读取适配器，交付管理员来源登记与项目绑定基础。

## 范围与选择

在现有项目知识 API 中增加来源登记、分页查询、详情和停用。每个来源绑定一个项目、一组部署凭证引用以及一个明确的飞书新版文档 ID。此切片不联网、不读取密钥、不创建摄取任务，也不宣称已经同步文档。

相比直接上线全量目录同步，本方案先确立来源身份和共享授权；相比把凭证直接写入数据库，使用不透明的部署引用可避免新增密钥保管边界。凭证引用只登记，不在此切片解析或验证是否已部署。后续 Worker 必须按组织作用域解析引用，不能将任意引用解释为全局环境变量或文件路径。

## API 与授权

- `POST /api/v1/projects/{project_id}/knowledge/sources/feishu`：创建，返回 `201`。
- `GET /api/v1/projects/{project_id}/knowledge/sources`：稳定游标分页（默认 50，范围 1–100），包含停用来源。
- `GET /api/v1/projects/{project_id}/knowledge/sources/{source_id}`：详情，返回 `200`。
- `DELETE /api/v1/projects/{project_id}/knowledge/sources/{source_id}`：幂等停用，返回 `204` 空体；未知来源返回 `404`，重复停用不新增审计或事件。

所有入口仅允许当前组织的 owner/admin，并要求项目 manage 权限。角色取当前数据库事实；变更按现有授权锁顺序串行化并在持锁后检查权限，不能依赖登录时角色快照。非管理员、无项目权限、跨组织、跨项目、未知来源均返回 `404 not_found`，不泄露配置。会话失效 `401 session_invalid`；变更沿用 Origin/CSRF 校验，失败 `403`。

创建请求严格禁止额外字段：`name` 为去首尾空白后 1–200 字符的无控制字符文本；`documentId` 为 1–128 ASCII 字母或数字；`credentialRef` 为 `[A-Za-z][A-Za-z0-9_-]{0,63}`，仅是不透明别名；`accessPolicy` 必填且只接受 `project_members`。最后一项表示管理员明确确认可以把文档共享给当前有项目读取权限的成员，不能由应用本身可读自动推导。此登记不会改变项目 ACL 或让任何内容立即可检索。

响应字段为 `id`、`projectId`、`provider=feishu`、`name`、`documentId`、`credentialRef`、`accessPolicy`、`status=configured|disabled`、`createdAt`、`updatedAt`、`disabledAt`。`configured` 只表示已登记；不代表凭证已验证或同步已完成。拒绝共享链接、URL、appSecret、token 和客户端 orgId。请求 schema 验证错误统一 `422 validation_error`，非法分页游标沿用 `422 invalid_cursor`；同一组织/项目/凭证引用/文档重复登记（包括已停用）返回 `409 source_conflict`，不隐式启用或更新。此切片无重新启用/修改入口。

所有响应沿用知识边界 `Cache-Control: private, no-store`、`X-Request-ID`，错误体 `traceId` 与头一致。沿用凭证 CORS 行为；失败不回显输入、凭证或内部异常。数据库不可用为 `503 database_unavailable`，其他异常为 `500 internal_error`。OpenAPI 与生成 SDK 同步声明实际成功/错误契约、CSRF 和头。

不支持的方法返回 `405 method_not_allowed`，`Allow` 必须列出该路径支持的全部方法；例如来源详情路径同时支持 `GET, DELETE`。新增来源端点声明该错误及 `Allow` 头。复用框架的多个同路径路由时，不能只返回首个路由的方法。

## 持久化及一致性

新增 `knowledge_sources` 表与迁移 0006；组织/项目复合外键阻止跨租户绑定；唯一约束覆盖组织、项目、provider、credential_ref、external_id。状态和停用时间使用检查约束。来源 ID 将成为后续 `KnowledgeResource.source_id` 的稳定标识，本次不修改现有资源/任务模型或上传 API。

创建与首次停用分别写 `knowledge.source_created`、`knowledge.source_disabled` 审计和项目聚合 Outbox，与来源变更同事务提交。事件只含 sourceId/projectId/provider/status/accessPolicy 等安全字段；不含文档 ID、凭证引用或用户输入名称。重复创建/停用、鉴权失败、审计/事件失败不产生部分变更。来源变更使用项目锁串行化，重复创建竞争返回确定的 409。

## 验收

先写失败测试，再实现。覆盖成功 CRUD、分页、严格验证、owner/admin/member/viewer、具有 manage ACL 的非管理员、跨租户/跨项目隐匿、会话与 CSRF、实时角色变化、重复/并发创建、停用幂等、事务回滚、数据库/未预期异常、CORS/请求 ID/no-store、OpenAPI/SDK。真实 PostgreSQL 检验迁移、约束及持久化。完成审查按 `docs/review.md`，不同上下文先规格再质量，最后必须取得当前树 `pnpm verify` 的真实结果。

配套的[按组织解析凭证模块](stage-3b-feishu-credentials-design.md)在 Worker 内独立提供，来源登记 API 不调用它或验证部署引用。2026-09-24 的[内容授权与撤回切片](stage-3b-source-revocation-design.md)进一步将来源状态与共享策略接入已有内容读取和索引发布，采用迁移 0006 的显式项目共享策略。[持久化手动同步](stage-3b-feishu-sync-design.md)进一步交付版本幂等，并在读取与持久化前验证 configured 状态、共享授权及来源身份；上游失效传播、管理界面和真实飞书租户验收仍待完成。
