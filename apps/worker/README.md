# apps/worker: 后台 Worker

当前处于阶段 0，仅保留目录和职责边界。Worker 将作为独立进程和镜像运行，任何慢任务都不能阻塞 FastAPI 请求进程。

## 职责

- 阶段 3：资源解析、切分、Embedding、索引和删除传播；
- 阶段 4：执行 Temporal Activity，包括内置 Agent 与模型调用；
- 阶段 5：外部 Agent、代码索引和仓库分析活动；
- 阶段 8：连接器增量同步和自动化触发。

Temporal 保存跨进程、跨天且需要恢复的业务工作流历史。Worker 执行幂等 Activity，并通过稳定 `run_id`、attempt 和幂等键避免重试产生重复副作用。

Redis 只用于缓存、限流、短期消息和实时分发，不承担任务或项目状态的唯一真相。业务状态、查询模型和 Outbox 落在 PostgreSQL，大型输入与产物落在 S3/MinIO。

最低验收要求：API 重启不丢任务、Worker 重启可恢复、重复执行不产生重复数据、取消能传播到下游调用。
