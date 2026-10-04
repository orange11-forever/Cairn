# 原生邮箱注册

注册默认关闭。运营者同时启用 `CAIRN_REGISTRATION_ENABLED=true` 并配置 SMTP 和 `APP_URL` 后，登录页「创建邮箱账号」可完成注册。缺少 SMTP 时 `/api/v1/auth/registration` 返回 `{enabled:false}`，页面提示暂不可注册。

密码为 12–128 个字符，原始空格和 Unicode 保留。提交只创建 30 分钟的短期申请；不创建用户、组织或会话。邮件链接固定为 `APP_URL/register/verify#token=…`，不会使用请求 Host。打开链接只显示确认表单，并清除地址栏 fragment。用户必须输入注册时设置的密码并明确确认，才会在一个事务中创建已验证的用户、随机个人组织及 owner 成员。成功后仍需正常密码登录。邮件扫描、GET、HEAD、页面挂载均不创建账号；注册不替换或恢复现有会话。

已有邮箱返回通用 accepted 文案和不可用 receipt，不设置密码、不合并账号、不重新启用用户、不加入已有组织。不同注册申请不能改写彼此的密码；并发验证最多创建一个用户及个人组织。第三方绑定继续通过登录后的账号设置明确操作。

| 接口 | 成功契约 |
| --- | --- |
| GET `/api/v1/auth/registration` | 200 `{enabled}` |
| POST `/api/v1/auth/register` `{email,password,displayName?}` | 202 `{message,registrationReceipt,resendAfterSeconds}` |
| POST `/api/v1/auth/register/resend` `{registrationReceipt,email,password}` | 202，同上 |
| POST `/api/v1/auth/register/verify` `{token,password}` | 200 `{message}` |

所有变更要求精确 Origin；没有 session Set-Cookie。错误沿用 `{code,message,traceId}` 和 `X-Request-ID`，包括 400 无效/过期/重放 proof、403 来源、422 参数、429 过频及 Retry-After、503 注册/邮件/数据库不可用、500 意外异常。API 响应 no-store/no-referrer；verification HTML 的部署静态服务器也需设置这两个响应头。开发和 Vite preview 使用相同页面保护。

额度独立于密码登录：发送每邮箱 5 次/小时、每 IP 20 次/小时，重发冷却 60 秒；验证每 IP 20 次/15 分钟、每申请 5 次错误密码/15 分钟。失败仍计入额度。SMTP 在提交 pending/额度后、数据库锁外发送；SMTP 接受不代表成功入箱。重发立即撤销旧 token、不延长 30 分钟寿命；确定邮件失败只撤销当前 generation，不影响更新的重发。receipt、token 只存摘要，密码只存 Argon2；前端仅在内存保存 pending receipt/password/token，不写浏览器存储。未知注册错误日志只包含类型及 trace ID。

运营者应至少每分钟运行现有 `pnpm auth:cleanup`，分批删除过期/已消费申请（含废弃邮箱和密码哈希）及旧 registration limiter。迁移 `0012_native_registration` 保留旧账号；有有效 pending proof 时拒绝降级。旧账号不伪造邮箱验证时间，也不因升级失去登录能力。

SMTP 只在 API 配置：`CAIRN_SMTP_HOST`、`CAIRN_SMTP_PORT`（默认 587）、`CAIRN_SMTP_SECURITY`（`starttls` 或 `tls`）、`CAIRN_SMTP_USERNAME`、`CAIRN_SMTP_PASSWORD`、`CAIRN_SMTP_FROM`。TLS 使用系统证书验证并要求认证，超时 10 秒；页面请求期限 15 秒。明文 `plain` 仅允许显式 test 环境的 loopback 捕获服务。不要打开 SMTP debug，也不要把 SMTP 凭据放入 VITE 变量、截图、日志或提交。

## 本机捕获验收

真实 SMTP 未提供；本轮只证明本机捕获，不宣称真实邮箱入箱。私有 harness 不读取 `.env`/OAuth 文件，不发送外部邮件，邮件只保存在内存，最多 20 条。只有 loopback `cairn_test` 数据库可使用；不要连接历史库或 OAuth 验收库。

在当前仓库中，先升级自己拥有的独立临时验收库，再启动：

```sh
# CAIRN_TEST_DATABASE_URL 指向独立 test 库，不放生产 URL。
DATABASE_URL="$CAIRN_TEST_DATABASE_URL" UV_OFFLINE=1 pnpm db:migrate
UV_OFFLINE=1 uv run --package cairn-api python scripts/registration-preview.py
```

另一个终端启动同源 UI：

```sh
CAIRN_API_PROXY_TARGET=http://127.0.0.1:55828 VITE_IDENTITY_API_URL=http://localhost:5503 pnpm --filter cairn-web exec vite --host localhost --port 5503 --strictPort
```

浏览器从 `http://localhost:5503/register` 注册；打开 `http://localhost:55827/` 刷新本机收件箱，再点「打开验证邮件」。页面需明确密码确认。成功后用邮箱密码正常登录、检查个人组织、旧组织/项目拒绝、退出再登录。不要把链接 fragment、receipt 或密码粘贴到终端/报告；关闭 harness 清空捕获邮件。端口可用命令行覆盖。

真实投递验收待 SMTP 配置：授权发件域、TLS/认证、实际入箱、链接 fragment 保留、同设备/跨设备确认、密码登录及组织隔离，需单独记录。
