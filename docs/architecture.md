# Cairn 架构

本文只描述公开、稳定的架构边界，并明确区分当前已交付能力与目标能力。路线图中的组件不代表已经实现。

## 当前已交付

当前交付前沿为 Stage 3A Task 1–20，并包含项目知识单轮生成式回答。

- React 19、TypeScript 与 Vite 构成 Web 客户端；登录后默认进入 `/projects`，身份、项目、任务与 `/projects/:projectId/knowledge` 的资源、按需详情、搜索、按需引用上下文、授权下载和真实上传批次连接真实 FastAPI。旧 `/documents` 与 `/ask` 书签重定向到项目工作台。
- FastAPI 采用模块化单体边界，提供 Cookie 会话、组织身份与 RBAC、项目 ACL、成员角色管理、项目任务、追加式审计、事务性 Outbox、有界 SSE，以及项目授权下的知识上传与资源生命周期 API。
- PostgreSQL 16/pgvector 与 S3 兼容 MinIO 当前已使用：PostgreSQL 保存业务事实、持久化摄取任务、知识资源、切片和向量，MinIO 保存原始对象与 ZIP 展开产物；生成的 TypeScript SDK 对齐 OpenAPI。Redis 仍是规划中基础设施。
- Stage 3A Task 1–11 的独立 Worker 已交付，用租约和心跳处理受限归档展开、文档解析、结构化切分、OpenAI 兼容 1024 维 Embedding 与原子索引发布。
- 项目知识单轮回答复用混合搜索与共享限流，在模型调用前后核验全部证据及 `read` 权限，并返回服务器分配的 `S1`–`S6` 引用。真实部署通过可选 `ANSWER_*` 配置接入 Chat Completions、Responses、Claude Messages 或 Gemini GenerateContent 的结构化 JSON 输出；缺失配置时其余 API 保持可用。流式、多轮、历史持久化和网页检索尚未实现；飞书手动同步通过独立来源任务接入知识链路。
- 全文格式化预览、流式/多轮问答与周期性详情轮询仍在后续任务。

Task 18A Web 资源详情已交付：资源行按需内联展开，通过生成 SDK、Cookie credentials 和真实 `GET /api/v1/projects/{project_id}/knowledge/resources/{resource_id}` 读取详情。收起会取消请求并销毁局部详情，项目切换或会话代际变化同样取消并销毁旧状态；重新展开和手动刷新都会重新授权，请求中及离线等待期间隐藏旧详情和下载，并禁用自动重连刷新，不进行周期轮询。详情展示安全元数据与处理状态，并把已知失败码映射为安全中文错误指引；仅 `latestVersion.status=ready` 时提供指向 Identity API 的新标签页下载，Web 不读取或缓存最终预签名 URL。详情 `404` 会重新检查当前资源列表，并只把当前搜索标记 stale，不自动重跑搜索；资源列表仍为 `200` 时保留工作区，列表 `404` 才隐藏工作区。

Task 18B 资源操作已交付：仅最新资源列表声明 `canWrite` 且 `latestVersion.status=failed`、服务端返回 `latestVersion.retryable=true` 时允许重试；重试使用 Cookie CSRF 和请求中的精确 `resource_id`/`version_id`，严格接受 `200`，且返回体 `id` 与请求 `resource_id`、`latestVersion.id` 与请求 `version_id` 匹配。软删除使用列出当前资源名的行内确认，取消不发送请求，确认严格接受 `204` 空响应。变更不自动重试或离线回放，取消只取消浏览器操作且不承诺回滚；删除先取消当前项目相关读取，再清理列表、详情、引用缓存并重置当前项目搜索而不自动发起 `POST`，保留其他项目与上传跟踪。`401 session_invalid` 由 MutationCache 清理会话，已取消操作的迟到 `401` 不会使新会话失效；`404` 重检列表并按列表 `200`/`404` 决定局部资源或工作区隐藏，`409` 先刷新详情，契约错误须手动详情恢复后才重新提供操作。

对象存储公开 `PUT` URL 必须与 Web 页面使用不同 origin；客户端拒绝同源上传 URL，避免浏览器自动携带同源 Cookie。对象存储 `PUT` 不携带 Identity credentials；预签名上传 URL 与签名 headers 仅存于局部运行时，不进入 DOM、Query/Mutation 缓存、日志或浏览器存储。文件与 ZIP 子条目展示安全状态和局部错误，完成确认及批次终止时刷新资源列表，搜索仅标记 stale，不自动重跑。取消、路由切换、批次替换和会话失效会停止未完成的浏览器操作；自动跟踪超时保留已知 queued/processing 事实，显示“后台仍在处理”并允许手动刷新。

## 目标架构

- API 处理同步命令、查询、租户与权限边界；已交付的独立 Worker 处理知识摄取、解析和索引，Outbox 发布与其他异步工作仍按后续需求扩展。
- PostgreSQL 是业务事实来源；S3/MinIO 保存原始对象和派生产物；Redis 只用于可丢失的缓存、协调或实时扇出，Redis 不是真实数据来源。
- 当前知识层以 Resource 和 ResourceVersion 表达逻辑资源与不可变版本，并保留来源、校验和、解析及索引状态。
- Task 12 搜索先执行规范化 ACL 过滤，再进行关键词或向量召回；引用可追溯到资源版本和片段。

## 安全与数据不变量

1. `org_id` 是所有租户数据访问的第一过滤条件，客户端不能声明可信租户、actor 或创建者。
2. 规范化 ACL 和当前成员关系是授权事实来源；权限在数据库查询中预过滤，任何搜索、问答或 Agent 工具都不能先取回跨权限内容再在应用层遮盖。
3. 审计日志追加写入，不通过普通业务路径更新或删除。
4. 业务写入、审计记录与 Outbox 事件在同一事务提交。
5. 普通删除使用可审计的软删除；物理清除是独立、显式且受权限约束的流程。
6. 外部资源同步以 `source_id`、`external_id` 和 `source_version` 保持幂等。
7. 向量与索引记录携带版本化 embedding profile；模型或分块策略变化不覆盖旧索引事实。

## 阶段路线

Stage 3B 飞书连接器已建立自建应用凭证和单篇新版文档读取边界，并增加[管理员项目来源登记](stage-3b-feishu-sources-design.md)：组织 owner/admin 登记文档 ID、部署凭证引用和显式项目共享策略，可分页读取或幂等停用；来源、审计和项目 Outbox 同事务提交。Worker 的[凭证解析边界](stage-3b-feishu-credentials-design.md)只从可选部署 JSON 按组织 UUID 与不透明别名精确查找凭证，并按次创建隔离客户端；它不授予内容权限、不检查来源启用状态，也不联网同步。[来源内容授权与撤回](stage-3b-source-revocation-design.md)将配置状态和显式共享策略接入资源、批次、搜索、问答以及 Worker 索引发布：停用提交后，新授权读取不再返回来源内容，处理中任务在发布前重新检查来源；历史对象与索引保留，已经签发的短时效对象 URL 按原到期规则失效。独立的[手动持久化同步切片](stage-3b-feishu-sync-implementation.md)增加管理员排队/查询同步请求、Worker 读取可信来源、快照版本去重和索引任务排队；同步完成表示快照已经持久化，不等于索引已发布，验收状态以该切片记录为准。周期同步、上游删除传播、管理界面和真实生产租户验收仍在后续；范围与约束见[同步设计](stage-3b-feishu-sync-design.md)，读取一致性限制见[飞书读取基础设计](stage-3b-feishu-reader-design.md)。当前 Web 知识工作区尚无来源管理或触发同步入口。

- 阶段 2.5.0：许可证、公开架构、跨平台仓库规则与受 CI 保护的 PR 流程。
- 阶段 2.5A：RBAC/ACL（已交付），包含组织角色、项目 ACL、成员角色 API、concealment、CSRF，以及权限变化与审计/Outbox 的事务一致性。
- Stage 3A Task 1–11：知识摄取基础（已交付），包含 Worker、S3/MinIO、Resource/ResourceVersion、解析、分块、Embedding 与原子索引发布。
- Stage 3A Task 12：项目范围混合搜索 API（已交付），包含检索前权限过滤、关键词/向量召回、确定性融合、关键词降级、限流和审计。
- Stage 3A Task 13：真实 Web 知识工作区基础（已交付），包含受保护路由、资源分页与搜索 query 边界。
- Stage 3A Task 14：真实知识资源列表（已交付），包含标题、文件类型、大小、更新时间、处理状态、只读提示和游标续页。
- Stage 3A Task 15：真实知识搜索结果（已交付），包含服务端排序摘录、文件类型、类型化 locator、混合检索/关键词降级标签与取消/错误/会话/访问权撤销状态。
- Stage 3A Task 16：搜索卡片内按需引用上下文与授权下载（已交付），前文、命中片段和后文以纯文本展示，重新展开会重新授权；下载在新标签页中只导航到 Identity API，实时授权后由 `307` 重定向到短时效对象地址，Web 不缓存或读取最终预签名 URL。

- Stage 3A Task 17：真实上传批次（已交付）。`/projects/:projectId/knowledge` 仅向 `canWrite` 用户提供文件选择和拖放，最多 20 个文件先完成校验与 SHA-256 摘要，再以最多 2 个并发 `PUT` 直传对象存储并显示逐文件进度，随后调用 `complete` 确认；批次每 2 秒跟踪一次，终止或首次查询满 5 分钟后停止自动跟踪，保留手动刷新且不伪造处理失败。取消只停止当前浏览器操作，已确认的服务端任务仍会继续；可重试的传输或 `complete` 失败使用全新批次与预签名 URL，`contract` 错误不允许重试。
- Stage 3A Task 18A：Web 资源详情（已交付），包含按需真实 GET、收起取消与局部状态销毁、项目/会话隔离、重新展开/手动刷新重新授权、离线隐藏、无自动重连刷新或周期轮询、安全中文失败指引、ready-only Identity API 新标签页下载，以及 detail 404 后精确资源列表重检和搜索 stale/no-POST 边界。
- Stage 3A Task 18B：资源操作（已交付），仅最新资源列表 `canWrite` 且 `latestVersion.status=failed`、服务端返回 `latestVersion.retryable=true` 时提供带 CSRF 的请求 `resource_id`/`version_id` 精确重试，成功严格为 `200` 且返回体 `id` 匹配请求 `resource_id`、`latestVersion.id` 匹配请求 `version_id`；行内命名软删除确认取消零请求，确认严格为 `204` 空响应。无自动 mutation 重试/离线回放，取消不承诺回滚；删除先取消相关读取，再清理当前项目列表/详情/引用/搜索缓存而不自动 `POST`，并保留其他项目和上传跟踪，覆盖迟到 `401`、列表重检、冲突刷新和契约恢复边界。
- Stage 3A Task 19：Mock 产品路径退场（已交付），包含默认项目入口、旧 `/documents`/`/ask` 兼容重定向、生成 SDK 错误校验，以及 Node mock 与手写 contracts workspace 移除。
- Stage 3A Task 20：核心摄取验收（已交付），`dev:core`/`verify:core` 托管本地假 Embedding、API 与 Worker，以真实 MinIO 签名 PUT 验证上传、ready、混合检索、行号引用上下文和授权下载；默认验证不需要外网或 Provider 密钥。

后续 Agent、模型 Provider 和工作流能力必须建立在租户、权限、审计和知识边界之上，不能绕过这些基础能力提前接入生产数据。
