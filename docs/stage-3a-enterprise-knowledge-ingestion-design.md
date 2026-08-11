# Stage 3A 企业知识摄取与检索设计

**状态：** 对话设计已批准，等待书面规格复核

**日期：** 2026-08-11

**交付状态：** 尚未实现；本文描述下一阶段边界，不代表当前产品能力

## 目标

阶段 3A 交付 Cairn 的第一个真实企业知识闭环。拥有项目权限的用户可以把常见办公文件或受限 ZIP 批量导入项目，独立 Worker 可靠地解析、切分并建立关键词与向量索引，随后在同一项目中执行权限过滤优先的混合检索并获得可追溯引用。

本阶段优先保证知识事实、租户隔离、项目权限、摄取幂等、版本可追溯和失败可恢复。它不生成 AI 答案，也不提前实现 Agent、完整模型治理或通用外部连接器。

## 用户流程

1. 用户进入一个已有项目并打开“知识文档”。
2. 用户选择或拖入常见办公文件，也可以上传一个受限 ZIP 批次。
3. Web 显示每个文件的直传进度，以及上传、解析、向量化、完成或失败状态。
4. Worker 完成全文与向量索引后，文档进入可搜索状态。
5. 用户在当前项目中输入关键词或自然语言查询。
6. Web 展示混合检索结果、原文片段和页码、幻灯片、工作表、行范围等引用位置。
7. 用户可以查看提取文本上下文，或通过短期授权地址下载原文件。

预签名地址、对象存储、任务租约、解析器和 Embedding 调用全部由系统处理。普通用户不配置 Provider；部署管理员通过受保护配置统一提供 Embedding 服务。

## 阶段划分

### 阶段 3A：本规格

- 企业常用文件与受限 ZIP 上传；
- Resource、ResourceVersion、摄取批次、任务与片段数据模型；
- MinIO/S3 预签名直传；
- 独立 PostgreSQL 租约 Worker；
- 结构化解析、切分与可定位引用；
- OpenAI 兼容 Embedding，包括阿里云百炼；
- PostgreSQL 多语言关键词检索与 pgvector 向量检索；
- 项目内、权限过滤优先的混合搜索；
- 真实 Web 上传、状态、搜索、引用和错误体验；
- 软删除、审计、Outbox 和离线可重复验证。

### 阶段 3B：后续独立规格

- 飞书云文档连接器；
- 管理员授权、目录选择、首次全量同步和版本增量同步；
- 删除与取消授权传播；
- 来源权限映射策略。

腾讯文档连接器只有在目标企业账号取得正式 API 资格并验证接口能力后才进入独立规格。在此之前，腾讯文档使用官方导出文件再上传的保底流程；禁止网页抓取、共享链接绕过或复用用户 Cookie。

## 明确不在阶段 3A 范围内

- 生成式问答、RAG 回答、会话记忆、重排序模型和答案引用编排；
- OCR、扫描 PDF、图片内容识别、音视频转写和多模态检索；
- 旧版 `.doc`、`.xls`、`.ppt`、邮件、CAD 和专业行业格式；
- 飞书、腾讯文档或其他 SaaS 的在线同步；
- 跨项目统一搜索、组织级知识门户和来源 ACL 镜像；
- Temporal、Redis 任务真相、长连接推送和 Agent 执行；
- 物理清除、法律保留和数据驻留策略；
- 面向最终用户的 Embedding Provider 管理界面。

## 架构

采用预签名直传、PostgreSQL 事实与租约任务、独立 Worker 的纵向切片：

1. FastAPI 从 Cookie 会话取得 `CurrentIdentity`，校验项目 `write` 权限后，在一个事务中创建摄取批次、条目与短期上传会话。
2. Web 使用预签名 `PUT` 把文件直接写入 MinIO/S3；文件字节不经过 FastAPI 请求进程。
3. Web 调用完成接口。API 校验对象元数据与 SHA-256，并在一个数据库事务中为普通文件创建资源、版本与索引任务，或为 ZIP 创建归档扩展任务；同一事务写入审计和 Outbox 事件。
4. Worker 使用 PostgreSQL 行锁和有期限租约领取任务，从对象存储读取内容，执行解析、切分和 Embedding。
5. Worker 以幂等事务写入片段、关键词索引、向量和状态事件。只有完整索引版本才进入 `ready`。
6. 搜索 API 先解析当前身份并在数据库中限制 `org_id` 与 `project_id`，随后并行执行关键词和向量召回，使用确定性融合排序返回引用。

本阶段不引入 Temporal。PostgreSQL 是任务与业务状态的真实来源；Redis 即使后续加入，也不能成为唯一任务真相。

## 租户与授权边界

- 每张租户业务表携带 `org_id`，项目知识表同时携带 `project_id`。
- 客户端不能声明可信 `org_id`、actor、创建者、对象键或权限主体。
- `read` 允许列出、读取、下载和搜索项目知识；`write` 允许上传、重试和软删除。
- 项目 `viewer` 的既有限权规则继续生效，其有效权限不会高于 `read`。
- 不存在、跨组织或权限不足的项目与资源统一返回 `404 not_found`。
- 搜索只面向一个显式项目。授权检查和 `org_id`/`project_id` 过滤发生在关键词与向量候选进入结果集之前。
- 引用只暴露资源、版本、片段和逻辑定位信息，不暴露对象存储键或永久下载地址。
- 下载端点每次重新校验实时项目权限，再签发短期 GET 地址。
- ACL 撤销或资源软删除立即影响列表、搜索、预览和下载，不等待索引刷新。
- 索引权限快照若后续加入，只能加速拒绝或重建，不能独立授予权限。

Cookie 会话下的上传创建、上传确认、删除、重试和搜索请求都要求合法 Origin 与会话绑定的 CSRF token。搜索虽然不修改文档，但会产生外部 Embedding 成本，因此同样采用受保护的 POST 命令边界。

## 数据模型

所有主键使用 UUID，时间使用 UTC。租户复合外键阻止跨组织与跨项目关系。

### `ingestion_batches`

表示一次用户提交，包括普通多文件提交或一个 ZIP 批次：

- `id`, `org_id`, `project_id`；
- `created_by`, `status`, `item_count`, `ready_count`, `failed_count`；
- `created_at`, `completed_at`。

批次状态从其条目派生，不能覆盖条目事实。部分成功的普通多文件或 ZIP 批次使用 `completed_with_errors`，不能把失败条目静默算作成功。顶层上传会话过期时，对应条目变为 `failed` 且错误码为 `upload_expired`；其他已完成条目继续处理。

### `upload_sessions`

表示一个待直传对象：

- `id`, `org_id`, `project_id`, `batch_id`；
- 原始文件名、声明媒体类型、字节数、SHA-256、随机对象键；
- `expires_at`, `completed_at`, `abandoned_at`；
- 完成后关联的资源版本或归档扩展任务。

上传会话有效期为 15 分钟。完成接口幂等：对已完成会话重复调用返回同一结果，不创建重复资源或任务。

### `ingestion_items`

表示批次中的一个普通文件或 ZIP 条目：

- `id`, `org_id`, `project_id`, `batch_id`；
- `parent_item_id`、标准化相对路径、媒体类型、字节数和 SHA-256；
- `status`, `error_code`, `error_detail`；
- `resource_id`, `resource_version_id`；
- `created_at`, `completed_at`。

ZIP 本身是批次输入，不是可搜索 Resource。Worker 验证并展开后，每个合法条目创建独立 Resource，并把条目原始字节保存为独立对象以支持授权下载。

### `knowledge_resources`

表示逻辑知识资源：

- `id`, `org_id`, `project_id`, `title`；
- `source_type`, `source_id`, `external_id`, `source_updated_at`；
- `current_version_id`, `created_by`, `created_at`, `updated_at`；
- `deleted_at`, `deleted_by`, `purged_at`。

阶段 3A 的 `source_type` 为 `upload` 或 `zip_entry`。数据模型预留后续 `feishu` 与 `tencent_docs`，但当前 API 不接受客户端任意指定这些值。

### `knowledge_resource_versions`

表示不可变资源版本：

- `id`, `org_id`, `project_id`, `resource_id`；
- `source_version`, `object_key`, `media_type`, `size_bytes`, `sha256`；
- `parser_profile`, `chunking_profile`, `status`；
- `error_code`, `created_at`, `processing_started_at`, `ready_at`。

`org_id + source_type + source_id + external_id + source_version` 构成来源幂等边界。上传来源使用稳定会话或 ZIP 批次标识、标准化路径与内容摘要构造这些字段。

### `ingestion_jobs`

表示可恢复的 Worker 工作：

- `id`, `org_id`, `project_id`, `job_kind`, `target_id`；
- `status`, `attempt`, `max_attempts`, `next_attempt_at`；
- `lease_owner`, `lease_expires_at`, `heartbeat_at`；
- `last_error_code`, `created_at`, `completed_at`。

`job_kind + target_id + profile_version` 使用唯一约束防止重复副作用。任务类型至少包含 `expand_archive` 和 `index_resource_version`。

### `knowledge_chunks`

表示可检索片段：

- `id`, `org_id`, `project_id`, `resource_id`, `resource_version_id`；
- `ordinal`, `kind`, `text`, `normalized_text`；
- `locator` JSON，保存页码、幻灯片、工作表、单元格或行范围；
- 多语言关键词索引字段；
- `created_at`。

`locator` 是类型化网络契约，不是任意前端解释的内部 JSON。每种解析器只能写入其声明的定位结构。

### `embedding_profiles` 与 `chunk_embeddings`

`embedding_profiles` 保存：

- `id`, 可空 `org_id`, `provider_key`, `model`, `dimensions`；
- `distance_metric`, `chunking_config`, `index_config`, `version`, `status`。

`chunk_embeddings` 保存 `chunk_id`, `embedding_profile_id`, `embedding`，并对二者建立唯一约束。Profile 变化创建新版本，不能覆盖旧向量事实。

API Key、Bearer token 和其他 Provider secret 不进入数据库、仓库、镜像或普通日志。`provider_key` 只引用部署配置。

## 文件与 ZIP 边界

阶段 3A 支持：

- `.pdf`：只支持可提取文本且未加密的 PDF；
- `.docx`：标题、段落和表格；
- `.pptx`：幻灯片文本和演讲者备注；
- `.xlsx`：工作表、行列范围和单元格文本；
- `.csv`：支持 UTF-8、UTF-8 BOM 与 GB18030 的表格行；
- `.html` / `.htm`：只提取可见正文，不执行脚本或加载外部资源；
- `.txt`：UTF-8 文本；
- `.md` / `.markdown`：Markdown 章节与正文；
- `.zip`：只作为包含上述格式的批量导入容器。

扩展名、声明 MIME 和文件签名必须一致。客户端 `accept` 只是便利提示，服务端与 Worker 是格式权威。

安全默认限制：

- 一次提交最多 20 个顶层文件；
- 普通文件最大 50 MiB；
- ZIP 压缩后最大 100 MiB；
- ZIP 解压后总计最大 500 MiB、最多 200 个文件；
- 禁止嵌套归档、加密条目、符号链接、绝对路径和 `..` 路径穿越；
- 限制单条目与整体异常压缩比；
- 标准化后路径必须唯一；大小、条目数或安全校验超限时拒绝相关归档；
- 不把 ZIP 中不支持的条目静默丢弃，批次详情逐项报告错误。

## 统一解析契约

每个解析器实现相同边界：输入不可变资源版本与受限对象流，输出有序 `ParsedBlock`：

- `kind`：heading、paragraph、table、slide、sheet_rows、code 或 text；
- `text`：规范化后的可检索文本；
- `locator`：原文定位；
- `metadata`：不包含 secret 的解析属性。

格式定位规则：

- PDF 使用页码；
- DOCX 使用标题路径、段落和表格序号；
- PPTX 使用幻灯片编号和备注区；
- XLSX 使用工作表名与行列范围；
- CSV 使用行范围；
- HTML 使用标题层级与正文区块；
- TXT/Markdown 使用章节与行范围。

HTML 永远以提取文本和受控结构展示，不能把上传的原始 HTML 注入 Web。电子表格解析不执行宏、外部链接或公式计算。

## 切分与版本化

切分器优先尊重结构边界，再按配置的字符或 token 上限拆分长块，并保留有限重叠。切分配置写入 Profile 版本；策略变化创建新索引事实，不原地覆盖旧版本。

一个资源版本只有在解析、切分、关键词索引和当前 Embedding Profile 的向量全部成功提交后才进入 `ready`。处理中或失败版本不参与搜索。切换 `current_version_id` 与新版本就绪在同一事务完成，旧版本在切换前继续提供稳定结果。

## Worker、租约与重试

Worker 使用 `FOR UPDATE SKIP LOCKED` 一类数据库领取语义，并写入 5 分钟租约。长任务每 60 秒续租；Worker 崩溃后，其他 Worker 只能在租约过期后重新领取。

- 默认最多尝试 5 次；首次失败后的重试延迟依次为 5 秒、30 秒、2 分钟和 10 分钟；
- 网络、对象存储、数据库和 Provider 短暂错误按上述间隔退避；Provider 明确提供更长 `Retry-After` 时采用更长值；
- 加密 PDF、扫描 PDF、无有效文本、危险 ZIP、格式伪装和向量维度不匹配属于永久错误；
- 每次写入以版本、任务类型和 Profile 为幂等键；
- 重试先清理同一未发布索引事实，再原子写入完整新结果；
- 实际业务状态变化、系统 actor 审计与 Outbox 事件在同一事务提交；
- 手动重试创建新的尝试事实，但不能复制 Resource 或 ResourceVersion。

稳定错误码至少包括：

- `unsupported_media_type`；
- `file_too_large`；
- `upload_expired`；
- `upload_checksum_mismatch`；
- `archive_encrypted`；
- `archive_nested`；
- `archive_limit_exceeded`；
- `archive_path_unsafe`；
- `encrypted_pdf_unsupported`；
- `no_extractable_text`；
- `parser_failed`；
- `embedding_unavailable`；
- `embedding_dimension_mismatch`；
- `ingestion_retry_exhausted`。

## Embedding Provider

阶段 3A 只实现 OpenAI 兼容 Embedding 客户端，不提前实现完整模型策略层。配置包含 Base URL、API Key secret 引用、模型、维度、超时和批大小。

首个 Profile 使用 1024 维。阿里云百炼是明确支持的首批 Provider，推荐 `text-embedding-v4`；其区域 Base URL 与 API Key 必须匹配。相同适配器也可以连接 LiteLLM Gateway、Ollama 或其他通过契约测试的 OpenAI 兼容服务。

百炼 `text-embedding-v4` 的同步批大小由 Provider 配置限制为最多 10 条。通用客户端不能假设其他 Provider 具有相同上限。

Worker 启动时验证活动 Profile、维度和 Provider 配置。测试与默认 CI 使用本地确定性假 Embedding 服务，不要求外网或真实 API Key；真实 Provider 冒烟测试是显式、可选且不进入默认验证链。

## 混合检索

搜索只在已授权的当前项目与 `ready` 当前版本中执行：

1. trim 后的查询必须为 3–500 个 Unicode code point，并进行确定性规范化；
2. 在数据库中固定 `org_id` 与 `project_id`；
3. 执行多语言关键词召回，最多取得 50 个已授权候选；
4. 使用活动 Profile 生成查询向量并执行 pgvector 召回，最多取得 50 个已授权候选；
5. 使用确定性的 Reciprocal Rank Fusion 合并排序；
6. 返回最多 20 条结果，默认 10 条；
7. 每条结果携带资源、版本、片段、摘录、文件类型与类型化 locator。

关键词侧同时使用 PostgreSQL 全文能力和 `pg_trgm`，避免把中文搜索建立在不适用的空格分词假设上。向量与关键词查询都把租户、项目、软删除和当前版本条件放在数据库查询中；禁止先在应用层取回未授权 Top-k 再过滤。

若查询 Embedding Provider 暂时不可用，搜索降级为关键词模式并返回 `retrievalMode = keyword_fallback`。Web 必须明确提示降级，不能伪装成完整混合结果。数据库或权限事实不可用时不降级为不安全查询，而是返回 `503 database_unavailable`。

搜索按用户与组织执行服务端限流，默认每名用户每分钟 30 次、每个组织每分钟 300 次；部署可以调低但不能关闭组织级限流。超限返回 `429 search_rate_limited`。审计记录 action、项目、检索模式、结果数量、查询长度与不可逆查询摘要，不把原始查询文本写入普通日志或审计 metadata。

## HTTP 契约

所有端点位于 `/api/v1`，身份从受保护会话解析，错误沿用 `message`、`code` 与 `traceId` 包装。

### 上传与状态

- `POST /projects/{project_id}/knowledge/uploads`：为 1–20 个顶层文件创建批次与上传会话，返回逐文件预签名 PUT 信息；
- 浏览器直接 `PUT` 到每个预签名对象地址；
- `POST /projects/{project_id}/knowledge/uploads/{upload_id}/complete`：验证对象并幂等创建资源版本或 ZIP 扩展任务；
- `GET /projects/{project_id}/knowledge/batches/{batch_id}`：读取逐项处理状态；
- `GET /projects/{project_id}/knowledge/resources`：稳定游标分页列出项目资源；
- `GET /projects/{project_id}/knowledge/resources/{resource_id}`：读取资源、当前版本与处理状态；
- `POST /projects/{project_id}/knowledge/resources/{resource_id}/versions/{version_id}/retry`：对可重试失败版本发起手动重试；
- `DELETE /projects/{project_id}/knowledge/resources/{resource_id}`：软删除并立即排除搜索；
- `GET /projects/{project_id}/knowledge/resources/{resource_id}/download`：重新授权后重定向到短期对象地址。

### 搜索与引用

- `POST /projects/{project_id}/knowledge/search`：提交查询、可选 limit，并返回检索模式和有序引用；
- `GET /projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}`：重新授权后返回引用上下文和 locator。

列表使用不透明稳定游标。请求字符串、文件数量、大小、枚举、路径和页大小由 Pydantic 设置硬边界。OpenAPI 是 Web 与其他客户端的唯一网络契约来源，TypeScript SDK 从 OpenAPI 生成。

## Web 体验

新增项目范围的知识工作区，建议路由为 `/projects/:projectId/knowledge`。现有文档、上传和问答 Mock 被真实 API 替换：

- 从项目进入知识文档，保留当前应用壳、主题、响应式和会话取消边界；
- 上传区支持拖拽、多文件、逐文件客户端校验、直传进度、取消和重试；
- ZIP 结果显示每个内部条目的成功或失败；
- 资源列表显示上传、解析、向量化、完成、失败和软删除前状态；
- 处理中使用 TanStack Query 有界轮询，不在本阶段引入长连接；
- 搜索页显示真实项目结果，不生成 AI 答案；
- 结果展示标题、摘录、文件类型、引用位置和检索模式；
- 点击引用读取受保护上下文；下载通过实时授权端点；
- 关键词降级、部分批次失败、重试耗尽和格式错误具有明确文案；
- 开发场景选择器和文档/上传/问答 Node Mock 从核心产品链路移除。

Worker 状态变化继续写项目聚合的 Outbox 事件，为后续事件推送保留边界；阶段 3A Web 只依赖有界查询和轮询。

## 删除与对象生命周期

普通删除设置 `deleted_at` 并在同一事务写审计和 Outbox。所有业务查询立即排除软删除资源；原始对象、版本和片段暂时保留，便于恢复与后续合规清除。

阶段 3A 不实现物理清除。过期且从未完成的上传对象与无资源归属的 ZIP 临时派生物由显式维护任务幂等清理。维护任务不能删除有效 ResourceVersion 引用的对象。

## 测试与验证

实现采用测试驱动开发，至少覆盖：

### 数据库与迁移

- pgvector 与 `pg_trgm` 扩展；
- 所有表、状态约束、租户复合外键、唯一幂等边界与索引；
- upgrade、downgrade 和迁移 head；
- 跨组织、跨项目关系被数据库拒绝。

### 对象存储与上传

- 真实 MinIO 预签名 PUT/GET、CORS、过期、对象缺失和 checksum 不匹配；
- 重复 complete 返回同一结果；
- 未完成对象维护清理不误删有效版本；
- API 不接收或代理文件字节。

### 解析与 ZIP 安全

- 每种支持格式的最小、中文、英文、表格、长文档和空内容 fixture；
- PDF 页码、PPTX 幻灯片、XLSX 工作表、CSV 行、HTML 标题与文本行定位；
- 加密与扫描 PDF；
- 路径穿越、绝对路径、符号链接、嵌套、加密、重复路径、异常压缩比、条目数和解压总量；
- ZIP 部分成功具有完整逐项结果。

### Worker 与索引

- 租约竞争、心跳、过期恢复和崩溃重领；
- 重复任务与重复尝试不产生重复片段或向量；
- 五次重试、永久错误和手动重试；
- Profile 版本并存、1024 维校验和维度错误；
- 版本只在全部索引提交后原子切换为 ready。

### 搜索与安全

- 中文、英文、精确词、语义相关和混合融合顺序；
- Provider 正常、超时和关键词降级；
- 当前版本、软删除与项目过滤；
- 项目 read/write 角色矩阵；
- 不存在、跨租户、无权、ACL 撤销并发和下载重新授权；
- 未授权片段在数据库结果与响应中均不可见；
- 搜索限流、CSRF、审计无原始查询和稳定错误包装。

### SDK 与 Web

- OpenAPI 生成与 drift 检查；
- 上传进度、取消、逐项错误、ZIP 部分成功、状态轮询与重试；
- 搜索结果、引用上下文、授权下载和关键词降级；
- 360、768 与 1280 像素响应式验收；
- 文档、上传和搜索不再调用 Node Mock。

### 完整验证

核心 Compose 加入 pgvector PostgreSQL 与 MinIO，验证流程启动真实 API 和 Worker，但使用本地假 Embedding 服务。最终验收要求聚焦测试、`git diff --check`、OpenAPI/SDK parity、迁移 head、生产 Web 构建、浏览器验收与完整 `pnpm verify` 全部通过。

## 验收标准

- 有项目 `write` 权限的用户可以直传所有支持格式和受限 ZIP；无权用户不能创建上传会话。
- 普通文件与 ZIP 合法条目分别形成可追溯、不可变的 ResourceVersion；危险条目不会被处理。
- Worker 重启、重复领取和自动重试不会丢任务或产生重复索引事实。
- 阿里云百炼 `text-embedding-v4` 可通过 OpenAI 兼容配置使用 1024 维 Profile；默认测试无需真实密钥或外网。
- 已授权用户能在当前项目获得中文与英文混合检索结果，并定位到原始文档结构。
- Provider 短暂不可用时搜索明确降级为关键词模式；摄取任务按策略重试。
- 跨组织、跨项目、权限不足、ACL 撤销和软删除内容不会进入列表、预览、下载或搜索结果。
- 资源、版本、片段、向量、审计和 Outbox 的事务边界满足现有架构不变量。
- Web 核心链路不再使用文档、上传或问答 Mock。
- 飞书与腾讯文档连接器不混入阶段 3A 实现，但数据模型不阻塞阶段 3B。
- 完整仓库验证通过，且没有真实 secret、临时对象、私有设计目录或无关文件进入提交。

## 外部契约参考

- [阿里云百炼 Embedding 与 OpenAI 兼容接口](https://www.alibabacloud.com/help/en/model-studio/text-embedding-synchronous-api)
- [飞书新版文档 OpenAPI 概述](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/docx-overview)
- [飞书获取文档纯文本内容](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/raw_content?lang=zh-CN)
- [腾讯文档官方产品能力说明](https://www.tencent.com/zh-cn/products/tencent-docs/)
