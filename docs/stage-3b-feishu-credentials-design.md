# Stage 3B：按组织解析飞书凭证

日期：2026-09-19。接续已登记的 `credentialRef`，提供独立、可测试的部署凭证解析边界，现由持久化手动同步任务按需调用。

## 范围

在 Worker 包新增 `FeishuCredentialResolver`，从部署环境中唯一指定的 `CAIRN_FEISHU_CREDENTIALS_JSON` 加载组织与别名映射。按可信来源记录的组织 UUID 与凭证别名精确查找，并按次创建独立 `FeishuDocumentClient`。本切片不改 API、数据库、SDK、任务类型、Worker 启动或 preflight，不运行同步，不访问真实飞书租户。

选择部署 JSON 映射，便于复用现有部署环境注入方式且不增加外部依赖。全局单凭证会丢失组织隔离，暂不采用；外部密钥服务需要额外设施，留给后续适配。别名始终是不透明键，不能解释为任意环境变量、路径或 URL。

## 输入与行为

配置格式为 `{组织UUID: {别名: {appId, appSecret}}}`；组织键必须是规范小写、带连字符的 UUID。别名精确匹配 `[A-Za-z][A-Za-z0-9_-]{0,63}`。凭证只接受 1–4096 字符的字符串，拒绝全空白、控制字符和 Unicode 代理字符；对象字段必须恰为 `appId`、`appSecret`。

缺失配置对应空映射；空根对象与空组织映射合法。显式空字符串、非对象 JSON、重复键、未知字段、错误类型、NaN/Infinity、过深 JSON、超过 1 MiB UTF-8 或超过 256 个绑定的配置均安全失败。解析后保存快照，外部环境的后续修改不改变已构造解析器。

`resolve(*, org_id: UUID, credential_ref: str)` 返回冻结的 `FeishuCredentials`；拒绝组织字符串等隐式转换。非法查找参数与未配置键返回同一种安全失败。同一别名可在不同组织对应不同凭证，不允许跨组织、全局默认或通配回退。

`create_client` 先精确解析，再创建全新客户端。加载、查找和构造均无网络请求；失败查找不创建客户端；客户端不跨调用共享 token 缓存。来源是否启用、项目授权和共享策略由可信同步调用方检查，凭证解析本身不授予内容权限。

## 错误与脱敏

专用 `FeishuCredentialFailure` 使用固定错误码和固定描述，`retryable=False`：

- `feishu_credentials_invalid`：部署配置非法。
- `feishu_credentials_not_found`：参数非法或组织绑定不存在。
- `feishu_credentials_unexpected`：解析边界出现其他普通异常。

解析器、凭证和异常的默认 repr/str，以及普通格式化 traceback 不包含原始 JSON、应用 ID、密钥、别名或上游异常文本。异常转换抑制异常链；`KeyboardInterrupt`、`SystemExit` 原样传播。不扩展尚未使用的持久化任务错误码。

## 验收

先取得缺失模块或行为的失败测试，再实现。覆盖同别名跨组织隔离、缺失和非法查找、配置快照、严格格式及边界、重复键、过深 JSON、Unicode、脱敏哨兵、异常链、进程中断、失败零网络、客户端实例独立，以及使用假传输观察正确组织的实际认证请求和 token 隔离。不得使用真实凭证。

运行新增测试与原飞书读取测试、Ruff、Pyright；按 `docs/review.md` 先规格后质量审查，并运行最终当前树完整 `pnpm verify`。新增模块无 HTTP 入站接口，状态码、trace ID、安全响应头和 OpenAPI/SDK 不适用；出站协议继续由已验证的读取器承担。

## 与来源授权和同步的衔接

[内容授权与撤回](stage-3b-source-revocation-design.md)采用显式 `project_members` 策略；[持久化手动同步](stage-3b-feishu-sync-design.md)按可信组织和凭证别名调用本模块。凭证解析器仍独立于来源表结构，本身不授予权限，也不验证共享策略。普通上传和 Worker 预检不要求配置飞书凭证。
