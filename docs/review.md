---
review:
  sequence:
    - specification
    - quality
  scope:
    - diff
    - affected-boundary
  negativePaths:
    - validation
    - authentication-authorization
    - infrastructure
    - unexpected-exception
  contractDimensions:
    - status
    - body-schema
    - request-trace-id
    - security-protocol-headers
    - openapi-sdk
  requiredGate: "pnpm verify"
  requiredApprovals: 0
---

# 代码审查规范

## 目标与门禁

审查的目标是证明改动满足需求且没有破坏受影响边界，而不只是确认 diff 看起来合理。仓库仍采用零审批 Pull Request；唯一必需的自动化门禁是 `pnpm verify`，具体 CI 与分支规则见[持续集成设计](ci.md)。

## 审查顺序

1. 规格审查先对照需求、设计和验收条件，确认没有漏做、越界或错误解释。
2. 规格问题修正后，质量审查再检查正确性、安全性、回归风险、可维护性和测试充分性。
3. 任一审查引发实质代码变更，都必须重跑相关测试；若变更影响已审结论，重新执行对应审查。

两类审查应由不同上下文完成，结论必须以当前工作树和真实测试输出为依据。

## 受影响边界

审查者必须同时阅读改动和它触及的边界，包括调用者、下游消费者、中间件顺序、框架默认行为、公开契约及生成制品。不能因为文件未出现在 diff 中就排除边界检查。

每个受影响入口至少覆盖以下路径：

- 正常成功；
- 输入与请求验证失败；
- 认证或授权失败；
- 数据库、网络或其他基础设施失败；
- 未预期异常。

若某一类路径不适用，审查结论中应说明原因。

## API 契约检查

对 HTTP/API 边界，逐项核对：

- 状态码与方法语义；
- 成功和错误响应体 schema；
- `X-Request-ID` 与响应 `traceId` 的关联；
- CORS、安全头以及 `Allow`、`Retry-After` 等协议头；
- OpenAPI 声明和生成 SDK 是否与运行时一致。

测试必须在消费者可观察的边界断言行为。只断言源码包含某行、只覆盖成功路径，或只确认某个状态码存在，都不足以关闭相关风险。

## 审查输出

发现项按严重性列出，并给出文件位置、可复现证据、影响和缺失测试。没有发现时也要说明检查过的边界与运行过的命令。最终结论只能基于最新提交；不能把进行中的检查点写成完成状态。
