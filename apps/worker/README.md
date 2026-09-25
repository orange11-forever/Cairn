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

`pnpm infra:up` 先启动 PostgreSQL 16/pgvector 和 MinIO 并初始化 bucket/CORS。`pnpm dev:core` 会幂等初始化兼容的活动 Embedding Profile，并托管本地确定性假 Embedding、API、Worker 与 Web；Worker 提前退出会使核心命令失败。`pnpm dev:worker` 仍可用于单独调试。

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

## 飞书文档读取边界

`cairn_worker.feishu.FeishuDocumentClient` 是一个可独立调用的内部读取器。它使用服务端自建应用凭证读取一个明确的飞书新版文档 ID，并返回标题、revision、原样纯文本和内容 SHA-256。`cairn_worker.feishu_credentials.FeishuCredentialResolver` 提供独立的部署凭证解析边界：只读取可选的 `CAIRN_FEISHU_CREDENTIALS_JSON`，按组织 UUID 与不透明别名精确解析，并为每次调用创建独立客户端。配置格式如下，示例值均为合成数据：

```json
{
  "11111111-1111-4111-8111-111111111111": {
    "engineering_feishu": {
      "appId": "demo-app",
      "appSecret": "demo-secret"
    }
  }
}
```

调用方必须从经过授权检查的持久化来源上下文提供组织 ID 与 `credentialRef`：

```python
from uuid import UUID

from cairn_worker.feishu_credentials import FeishuCredentialResolver

resolver = FeishuCredentialResolver.from_environment()
client = resolver.create_client(
    org_id=UUID("11111111-1111-4111-8111-111111111111"),
    credential_ref="engineering_feishu",
)
```

环境变量缺失时解析器使用空映射，因此现有上传 Worker 不会因未启用飞书而增加启动要求。解析器不建立当前用户授权、不检查来源是否启用，也不决定 `project_members` 分享策略；加载、查找和客户端构造不联网，同一客户端实例内部的 token 缓存不会跨组织或凭证共享。索引处理器独立使用可信任务、资源和版本事实，在读取对象前验证来源，并在最终发布前锁定来源行后重新验证；停用先提交会阻止发布，发布先取得锁时停用等待提交，随后内容读取立即被过滤。

读取器和凭证解析器已接入管理员手动触发的 Worker 同步任务，但尚未接入用户界面或完成真实生产租户验收。读取流程在正文前后核对 metadata，但飞书纯文本接口不绑定 revision，不能据此声称获得服务端原子快照；后续仍须处理定时触发和外部删除传播。当前索引发布边界已经执行来源授权和停用撤回。

手动同步任务现已接入 Worker：运行时按需解析部署凭证，读取单个登记文档，把 UTF-8 快照写入对象存储并原子创建资源版本和既有索引任务。相同 revision/hash 复用事实，同 revision 不同 hash 安全重试，较旧 revision 终止且不会覆盖较新发布版本；软删除资源不会自动复活。普通上传启动和预检不要求配置飞书凭证。定时同步、webhook、外部删除传播与真实租户验收仍待完成。

## 对象存储与回滚边界

Worker 以流式/有界方式从 S3/MinIO 读取源对象。ZIP 子项写入对象存储后才在 PostgreSQL 中注册；如果数据库事务回滚或租约所有权丢失，只对本次新建且尚未被任何持久化版本引用的对象执行最大努力清理。清理失败不会伪造数据库提交，可由孤立对象维护边界后续处理。

## 非职责

当前 Worker 不：

- 提供或执行 Task 12 混合搜索查询；
- 执行 Temporal Agent 工作流、模型对话或 AgentRunner 调度；
- 执行资源软删除之后的对象/索引清除传播；
- 飞书周期/目录同步、GitHub/Wiki/云盘等其他连接器，或上游权限撤回与外部来源删除传播。

## 质量检查

```bash
pnpm test:worker
pnpm lint:worker
pnpm typecheck:worker
pnpm worker:preflight
```

`pnpm verify` 会运行 Worker 的 pytest、Ruff 和 Pyright；Worker 测试覆盖 PostgreSQL 租约、S3/MinIO 对象边界、OpenAI 兼容 Embedding 与原子索引发布语义，`pnpm verify:core` 另行验证真实 pgvector/MinIO 基础设施。
