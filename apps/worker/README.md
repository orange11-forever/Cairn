# apps/worker: 知识摄取 Worker

`apps/worker` 是 Stage 3A Task 1–11 已交付的独立 Python 进程。它从 PostgreSQL 租用持久化摄取任务，从 S3 兼容 MinIO 读取对象，并把解析、切分、Embedding 与索引发布与 FastAPI 请求进程隔离。PostgreSQL 保存任务和业务事实，MinIO 保存大型输入与 ZIP 展开产物；Redis 仍是规划中基础设施。

## 运行模式

在仓库根目录运行：

```bash
pnpm dev:worker
pnpm worker:once
pnpm worker:preflight
```

- `pnpm dev:worker` 以持续模式运行 Worker，循环租用并处理当前可执行任务。
- `pnpm worker:once` 执行完整启动预检后，最多处理一个当前可租用任务，适合调试和调度器单次触发。
- `pnpm worker:preflight` 只检查配置、PostgreSQL 连接与必需 profile 表、S3/MinIO bucket、活动 Embedding Profile 以及 OpenAI 兼容 Embedding Provider 响应，不租用任务。

`pnpm infra:up` 先启动 PostgreSQL 16/pgvector 和 MinIO 并初始化 bucket/CORS。Worker 不由 `pnpm dev:core` 托管，需要单独启停。

## 持久化任务契约

- Worker 在 PostgreSQL 中以 `FOR UPDATE SKIP LOCKED` 租用一个到期可执行任务，因此多个 Worker 不会阻塞地抢占同一行。
- 运行中任务使用 5 分钟有界租约和 60 秒心跳；所有终态提交都再次检查 `lease_owner` 与租约有效性，失去所有权的 Worker 不能发布结果。
- 过期的运行中租约会把旧 attempt 记为 `lease_lost` 并重新租用；可重试失败按持久化 `next_attempt_at` 退避，达到 `max_attempts` 后以 `ingestion_retry_exhausted` 进入终态。
- 失败 attempt、job、批次 item 和资源版本只保存稳定错误码与经过清洗的 `safe_detail`；终态失败的审计与 Outbox 事实与业务状态一起提交。

这些是当前已实现的耐久任务语义：进程中断后，租约过期使任务可由后续 Worker 重新租用，而不依赖进程内存保存进度。

## 解析、切分与索引

当前支持文本、Markdown、HTML、CSV、PDF、DOCX、PPTX 和 XLSX。受限 ZIP 展开会拒绝绝对路径、路径穿越、符号链接/重解析点、加密、重复规范化路径和超出单项、条目数或展开总量上限的归档。Office 格式同样经过受限 OPC 容器读取，解析输入和 XML 解码都有硬上限。

解析器保留可追溯的结构化 locator：PDF 页码、DOCX 标题/段落/表格、PPTX 幻灯片与正文/备注、XLSX sheet/单元格范围、CSV 行范围、HTML 标题块，以及文本/Markdown 标题路径与行号。切分器在可配置但有界的字符限额内尽量保留这些结构边界。

Worker 通过 OpenAI 兼容 `/embeddings` 接口分批生成严格 1024 维向量。Embedding Profile 记录 provider、model、dimensions、distance metric、chunking/index config 与 version；每个向量都绑定 profile，不兼容的活动 profile 会在 preflight 或写入前失败。新切片、关键词搜索文档和 pgvector 向量在所有解析与 Embedding 成功后原子替换目标版本的旧索引，部分结果不会成为已发布版本。

## 对象存储与回滚边界

Worker 以流式/有界方式从 S3/MinIO 读取源对象。ZIP 子项写入对象存储后才在 PostgreSQL 中注册；如果数据库事务回滚或租约所有权丢失，只对本次新建且尚未被任何持久化版本引用的对象执行最大努力清理。清理失败不会伪造数据库提交，可由孤立对象维护边界后续处理。

## 非职责

当前 Worker 不：

- 提供或执行 Task 12 混合搜索查询；
- 执行 Temporal Agent 工作流、模型对话或 AgentRunner 调度；
- 执行资源软删除之后的对象/索引清除传播；
- 同步 GitHub、Wiki、云盘等连接器或处理外部来源删除传播。

## 质量检查

```bash
pnpm test:worker
pnpm lint:worker
pnpm typecheck:worker
pnpm worker:preflight
```

`pnpm verify` 会运行 Worker 的 pytest、Ruff 和 Pyright；Worker 测试覆盖 PostgreSQL 租约、S3/MinIO 对象边界、OpenAI 兼容 Embedding 与原子索引发布语义，`pnpm verify:core` 另行验证真实 pgvector/MinIO 基础设施。
