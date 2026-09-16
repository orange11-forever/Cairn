# Stage 3B：飞书文档读取基础

日期：2026-09-16。范围：Stage 3B 的第一个内部适配器切片；不代表完整连接器交付。

## 目标与阶段安排

现有上传、索引、检索和项目问答已交付。下一阶段要让企业授权的飞书文档进入同一知识链路。本切片先建立可独立测试的外部读取边界，避免在应用凭证、文档版本和失败语义尚未明确时接入持久化任务。

完整连接器后续依次实现：管理员配置与项目来源绑定；选定文档或目录的持久化同步任务；以来源、外部文档 ID 和版本实现幂等摄取；删除及撤权传播；管理界面与真实租户验收。来源 ACL 策略必须在持久化摄取前落实，不能把应用可读取解释为全部项目成员均可读取。

现有 `knowledge/models.py` 已预留 `source_type=feishu`，资源以组织、项目、来源类型、来源 ID 和外部 ID 标识，资源版本另有 `source_version` 唯一约束。但现有 job kind 仅包含归档展开和资源版本索引，来源配置、同步任务与撤权状态尚未实现。后续应从这些明确边界接入，不让上传 API 接受任意客户端声明的飞书来源。

本次只实现 Worker 包内的 `FeishuDocumentClient`：服务端自建应用凭证换取 tenant token，读取一个明确 document ID 的新版文档，返回标题、版本、纯文本及内容摘要。不上线 API、Web、定时同步、数据库迁移或新的 Worker job 类型。现有启动流程不依赖飞书配置。

## 方案选择

1. 直接加入全量目录同步会同时引入权限、任务和版本发布边界，超出本切片验收范围。
2. 使用官方 SDK 可获得更多接口，但本切片只需三个请求契约，会增加当前不需要的依赖。
3. 采用标准库受限 HTTP 适配器，沿用 Worker Embedding 客户端模式，保留可注入 opener 用于确定性测试。本切片采用此方案。

## 官方协议依据

核对日期为 2026-09-16：

- [自建应用获取 tenant_access_token](https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal)：`POST /open-apis/auth/v3/tenant_access_token/internal`，请求为 `app_id`、`app_secret`。
- [文档基本信息](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/get)：`GET /open-apis/docx/v1/documents/{document_id}`。
- [文档纯文本](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/raw_content)：`GET /open-apis/docx/v1/documents/{document_id}/raw_content`。
- 官方页面正文依赖动态渲染；请求方法、字段与 token 顶层响应另以 [官方 SDK token manager](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/core/token/manager.py)、[文档模型](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/docx/v1/model/document.py)、[纯文本请求模型](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/docx/v1/model/raw_content_document_request.py) 交叉核对。

不引入未经官方资料确认的数字业务错误码映射。HTTP 状态与非零业务码分别检查，HTTP 200 并不代表业务成功。

## 内部接口

新增 `apps/worker/src/cairn_worker/feishu.py`，必要时只按单一职责拆分邻接私有模块。

```python
class FeishuDocumentClient:
    def __init__(self, *, app_id: str, app_secret: str,
                 timeout_seconds: float = 10.0,
                 maximum_response_bytes: int = 2 * 1024 * 1024,
                 opener_factory=build_opener, clock=monotonic): ...
    def read_document(self, document_id: str) -> FeishuDocumentSnapshot: ...
```

`FeishuDocumentSnapshot` 是冻结值对象，包含 `document_id: str`、`revision_id: int`、`title: str`、`content: str` 和 `content_sha256: str`。SHA-256 基于原样正文的 UTF-8 字节，不对内容进行 HTML 解释、执行或规范化。标题和正文不进入默认 repr。空正文允许返回，是否可索引由后续摄取层判断。

`FeishuFailure` 提供稳定 `code`、固定安全描述、`retryable` 与可选 `retry_after_seconds`。错误对象、客户端 repr、异常文本和常规 traceback 不包含应用密钥、token、正文、上游响应文本或任意上游异常文本。异常转换使用 `from None`；`KeyboardInterrupt`、`SystemExit` 不被吞掉。

## 请求与缓存

- 只允许固定 HTTPS origin `https://open.feishu.cn`；不接受用户提供的主机、完整 URL、共享链接或 Cookie。
- document ID 只接受 1–128 个 ASCII 字母或数字，非法输入在任何网络请求前失败。此限制是本地适配器输入政策，不声称是飞书全部 ID 的官方语法。
- 非空 app ID、secret 有界至 4096 字符，拒绝控制字符；不在错误中回显输入。
- 超时必须是有限正数且不大于 60 秒，拒绝 bool；响应限额必须为 1–8 MiB 之间的非 bool 整数，默认 2 MiB。
- token 请求仅含 JSON 凭证；文档 GET 使用 `Authorization: Bearer ...`；请求声明接受 JSON。拒绝全部重定向，包括相同 origin，防止凭证被转发。
- 响应总读取使用 limit+1 的有界读取，不信任 Content-Length。token 响应另限制为 64 KiB。成功必须为 HTTP 200、JSON object、严格非 bool 整数 `code == 0`。
- tenant token 必须为非空、有界（4096 字符）、不含空白或非 ASCII 字符的 header-safe 字符串；`expire` 必须为 1–86400 的非 bool 整数。使用请求开始时的单调时钟计算过期时间，提前 `min(60, expire / 2)` 秒失效，不把请求耗时重新算进 TTL。
- 缓存仅在当前客户端实例内；一个实例服务一组自建应用凭证，不用于跨租户共享。不提供并发共享保证，调用方按 Worker 操作独占实例。认证拒绝及非零业务码清除缓存；本次调用失败，不隐式重放。
- 不自动 sleep、不自动重试；由后续持久化任务层控制重试与总预算。

## 文档读取与一致性

每次 `read_document` 顺序执行：获取或复用 token；读取基本信息 A；读取纯文本；读取基本信息 B。A/B 的 document ID 必须与请求完全一致，revision 为非负严格整数，title 为至多 4096 字符的有效 UTF-8 文本。正文也必须是有效 UTF-8 字符串。

A/B revision 或 title 不同则失败 `feishu_document_changed`，不返回部分快照。最后一次请求失败同样不返回已读正文。此检查仅检测可观察到的并发修改：纯文本接口不绑定 revision，所以不能宣称提供飞书服务端原子快照或消除最终一致性风险。后续同步保存 revision 和内容摘要，并结合重试/再次核验。

## 失败分类

| 场景 | code | retryable |
|---|---|---|
| HTTP 401 | feishu_auth_failed | false |
| HTTP 403 | feishu_access_denied | false |
| HTTP 404 | feishu_not_found | false |
| HTTP 429 | feishu_rate_limited | true |
| HTTP 5xx、连接/读取失败、超时 | feishu_unavailable | true |
| HTTP 3xx | feishu_redirect_rejected | false |
| 其他 HTTP 非 200 | feishu_request_rejected | false |
| 非零整数业务 code | feishu_request_rejected | false |
| 无效 JSON/schema/UTF-8、错误文档 ID、非法 token/TTL | feishu_invalid_response | false |
| 读取响应超限 | feishu_response_too_large | false |
| 读取期间版本或标题变化 | feishu_document_changed | true |
| 未预期普通异常 | feishu_unexpected | false |

HTTP 错误状态优先于错误 body 的格式，不读取或公开错误正文。429/5xx 的 `Retry-After` 只接受 ASCII 非负十进制秒并限幅 3600；缺失、非法或 HTTP 日期值忽略。此为内部重试提示，不自动等待。不把 HTTP 403/404 当作需要删除本地资源的证据；删除传播属于后续同步决策。

## 验收

测试从调用者可观察的请求、返回值和失败行为断言：正确方法/path/body/header；同实例 token 复用与提前过期；慢 token 请求不延长缓存；不同实例不共享凭证；版本变化；空内容；非法 ID 零网络；重定向不发生第二次请求；超限、深层 JSON、非法字段/UTF-8；各 HTTP 分类与非零业务码；403/404 无部分快照；Retry-After；连接、读取及未预期异常的脱敏与资源关闭。

至少包含一次真实 urllib opener/handler 链的本地传输测试，避免只验证注入 fake 的假设。测试不访问飞书、不使用真实密钥。测试、Ruff、Pyright 必须通过，并运行当前树的完整 `pnpm verify`。按 `docs/review.md` 先独立规格审查，再独立质量审查；无公开 API 变化时说明入站鉴权、trace ID、安全响应头、OpenAPI/SDK 均不适用，并审查出站协议和凭证边界。

## 交付说明

此切片是可调用且有测试的内部读取客户端，不是用户已可操作的飞书同步功能。真实飞书租户授权、生产网络联调、来源 ACL、持久化和 UI 都是后续验收项。
