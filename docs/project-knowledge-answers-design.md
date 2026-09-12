# 项目知识生成式问答

首版在项目知识工作区提供单轮、非流式问答。只读成员可提问；请求使用 Cookie 会话、CSRF 和项目 `read` 权限。问题经 NFKC 与 trim 规范化后必须为 3–500 个 Unicode codepoint。

`POST /api/v1/projects/{project_id}/knowledge/answers` 复用 `KnowledgeSearchService.search(limit=6)`，共享用户/组织限流、Embedding 降级和搜索审计。服务在模型调用前后重新检查项目权限及全部当前 ready 版本；任一证据变化都会舍弃回答并返回 `409 knowledge_changed`。数据库事务不跨模型网络调用。

回答为 `answered` 或 `insufficient_evidence`。已回答状态至少包含一段，每段至少引用一个服务器分配的 `S1`–`S6`；引用是现有 `KnowledgeCitation` 的平铺扩展。证据不足时正文和引用均为空。服务只渲染纯文本。

Provider 使用独立的 `ANSWER_BASE_URL`、`ANSWER_API_KEY`、`ANSWER_MODEL` 和 `ANSWER_TIMEOUT_SECONDS`，兼容 `/chat/completions` 非流式 JSON object 模式。响应体上限 256 KiB，最多八段、每段 1000 codepoint、总正文 6000 codepoint；拒绝截断、拒绝、工具调用、未知或重复引用。缺失或部分配置不会阻止 API 启动，问答返回 `503 answer_unavailable`。生产非回环 URL 必须使用 HTTPS。

Web 不持久化问题、回答或来源。新提交、取消、项目或会话变化、资源删除及离线都会清除旧回答并中止请求；恢复在线不自动生成。引用复用现有上下文和授权下载组件。首版不包含流式、多轮、跨项目、网页检索、工具执行、长期记忆或连接器。

默认核心验证使用本地确定性假 Provider，通过真实 HTTP、授权检索和引用上下文验证链路；它不验证生产模型质量。
