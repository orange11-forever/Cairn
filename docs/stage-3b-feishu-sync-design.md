# Stage 3B：持久化飞书同步设计

日期：2026-09-25。状态：手动持久化同步切片已通过独立规格/质量审查和修复后当前树 `pnpm verify`，详见[验收记录](stage-3b-feishu-sync-acceptance.md)。完整连接界面和真实飞书租户验收仍待后续完成，当前验收不代表生产部署。具体约束以[实施规格](stage-3b-feishu-sync-implementation.md)为准。前置为[内容授权与撤回](stage-3b-source-revocation-design.md)。

## 目标与切片

管理员对已登记来源手动触发同步，API 只持久化请求；Worker 按来源记录的组织与凭证别名读取文档，将快照写入对象存储并创建现有索引任务。索引发布后，现有资源列表、搜索和问答直接使用新内容。首次支持单个明确文档，不扫描目录、不处理 webhook、不定时轮询、不查询飞书逐用户权限。

当前共享策略来自管理员明确确认 `project_members`；应用凭证可读不能代替共享授权。未来如选择逐用户权限，需要独立迁移设计和兼容层。

## 持久化边界

新增 `knowledge_source_syncs`，保存 org_id/project_id/source_id、requested_by、时间以及结果 resource_id/version_id；复用 ingestion_jobs 的租约、attempt、错误和重试状态，避免复制第二套队列。新增 job kind `sync_feishu_source`，target_id 指向 sync UUID，profile_version 使用固定 `feishu-sync-v1`。这样复用现有 `(job_kind,target_id,profile_version)` 唯一约束，不必把请求标识混入 Embedding Profile。

API 在现有管理员授权锁之后锁住来源行；如果该来源已有 queued/running 同步则返回同一请求，防止连点或并发创建重复活动任务。终态后再次触发产生新请求；失败自动重试沿用既有任务策略，手动再次同步产生新的可审计请求。完成同步不等于完成索引，响应需区分同步状态与资源版本处理状态。

端点为 `POST /api/v1/projects/{project_id}/knowledge/sources/{source_id}/syncs`（202）及 `GET .../syncs/{sync_id}`（200）；只允许当前 owner/admin，沿用项目 manage、CSRF、404 隐匿、安全头、trace ID 及数据库/异常响应契约。请求不接受 orgId、凭证、文档 ID 或任意 URL。轮询响应包含请求、项目、来源 ID、任务状态、attempt、安全错误码、时间和可空的结果资源/版本 ID；不包含独立的“是否复用”字段。结果 ID 必须同时为空或同时非空。新增迁移从当前 0006 后续接 0007，同步 OpenAPI/SDK。

## Worker 顺序与幂等

1. 由可信 claim 加载同 org/project 的 sync 与来源；验证 provider/configured/project_members，读取当前文档 ID 与别名。失败时不得创建飞书客户端或发出请求。
2. 凭证按 org UUID + credential_ref 精确解析，每次构造独立客户端。配置读取按需执行，未配置飞书不能使普通上传 Worker 启动失败。
3. 读取已验证的 `FeishuDocumentSnapshot`，明确保留读取器的限制：元数据前后 revision 检查不构成上游原子快照。
4. 使用 `str(revision_id)` 作为 source_version；内容采用 UTF-8 text/plain，保存 SHA-256 与字节长度。空白内容返回明确不可索引结果；revision 必须是非负整数（不接受 bool），十进制长度至多 255。内容和标题必须为有效 UTF-8 文本；标题去除首尾空白并裁剪至 512 字符，空标题使用来源名称。正文不进入日志、Outbox 或错误描述。
5. 网络读取期间不持有 job 锁。读取后检查 heartbeat，按 job/attempt → project → 已有 resource → source → sync 的顺序锁定并刷新事实；验证租约、attempt、状态、文档 ID 与凭证别名仍与读取时一致。索引发布按 version → resource → source 锁定，其中 version 使用 FOR NO KEY UPDATE：发布仅修改状态和时间，该锁仍排斥其他写入和删除，但兼容重复同步结果 FK 的 KEY SHARE，避免 resource/version 互等。该顺序兼容项目 FK、API 排队及租约回收；来源变动或停用拒绝发布。
6. 以 source identity 查找资源（包括软删除）：自动同步不得复活用户删除的资源。同一 source_version 已存在时比较正文哈希；相同则复用版本，不重复写对象、创建版本或索引任务；不同则作为可重试的 parser_failed 处理，遵守既有退避及重试上限，不能覆盖同版本内容。复用适用于 queued/running/failed/completed 索引状态，失败索引不得自动重排。
7. 新版本先写独立不可变对象，再在数据库事务中创建资源/版本、index_resource_version 任务、结果引用和审计/Outbox，并完成 sync 任务。对象写入失败不留下部分 DB 事实；事务失败采用现有 rollback cleanup 机制清理本次独占对象。进程崩溃造成的孤儿对象回收需另有留存清理策略，不得删除可能已提交引用的对象。
8. 更新到较新 revision 时保持旧 current_version 可检索，直到新索引原子发布；低于任一已存版本的 revision 在对象写入前终止；索引发布时也比较已发布 revision，防止较旧索引覆盖新指针。相同 revision/hash 仅复用既有版本和索引生命周期，不创建或补排索引任务。

## 错误与验收要求

飞书读取及凭证错误复用安全的 parser_failed，空内容使用 no_extractable_text，存储故障使用 object_store_unavailable；不新增错误枚举迁移。429、5xx、传输失败和读取期间 document_changed 沿用 0..3600 秒上限的 Retry-After 与自动退避；凭证缺失、401/403/404、非法快照、来源身份变化或撤回以及旧 revision 不自动重试。异常文本、密钥和 document ID 不进入 API 错误或日志。

验收使用假飞书传输与真实 PostgreSQL/MinIO：API 触发并发幂等、管理员实时降权、非法输入/CSRF/会话、跨租户；Worker 可信组织别名、成功同步到索引搜索、版本复用/更新/旧版本保护、处理中停用、租约失效、对象失败、事务回滚、自动重试、异常脱敏。检查 API 全响应契约和生成 SDK，并按规格审查→质量审查→当前树 pnpm verify 收口。真实飞书租户与管理 UI 仍是单独的验收切片。

## 已确定的边界与后续工作

- 同步和索引发布均保护 revision 顺序；实际交错测试覆盖旧索引执行期间新 revision 发布。
- 用户删除之后的重新接入入口：本切片默认拒绝自动恢复；未来需要显式的恢复或重新登记流程。
- 首切片明确保留上游 403/404/暂时故障之前已共享的快照。管理员主动停用立即隐藏检索；上游删除与权限变化传播仍需后续独立设计。
- 0007 在存在同步请求或同步任务时拒绝 downgrade，不删除事实；空库可随既有迁移测试恢复至旧版本并升级。
