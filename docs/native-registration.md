# 邮箱密码直接注册

邮箱仅作为登录标识，不验证邮箱归属。注册默认开启，可设置 `CAIRN_REGISTRATION_ENABLED=false` 关闭；无需 SMTP，也不发送验证、通知、重发或找回邮件。

`GET /api/v1/auth/registration` 返回 `{enabled: boolean}`。`POST /api/v1/auth/register` 接受邮箱、12–128 个字符的密码和可选显示名，成功返回 `201 {message}`；同一事务创建个人账号、个人组织和 owner 成员关系。密码保留原始空格和 Unicode，使用 Argon2 保存，`email_verified_at` 为空。注册不创建或替换会话，用户需显式使用密码登录。

保留精确 Origin 检查、邮箱/IP 限流和并发唯一性保护。已有邮箱返回 `409 registration_conflict`，不覆盖密码、不重新启用停用账号、不合并第三方账号，也不加入已有组织。邮箱归属未经证明，不能用于自动关联其他账号或组织。

错误沿用 `{code,message,traceId}` 和 `X-Request-ID`：来源无效返回 `403`，参数无效返回 `422`，过频返回 `429` 及 `Retry-After`，注册关闭或数据库不可用返回 `503`，意外异常返回 `500`。响应设置 `no-store` 和 `no-referrer`。注册额度独立于登录：每邮箱每小时 5 次、每 IP 每小时 20 次，重复邮箱尝试也计入；额度键仅保存 HMAC 摘要。

下列旧接口已弃用，固定返回 `410 email_flow_disabled`，不处理旧凭据或触发邮件：

- `POST /api/v1/auth/register/resend`
- `POST /api/v1/auth/register/verify`
- `POST /api/v1/auth/password/reset/request`
- `POST /api/v1/auth/password/reset/confirm`

前端已移除邮件验证和邮件找回页面及入口。密码遗失恢复方式尚未交付。

历史数据库表与迁移保留，避免破坏已有数据库；升级不伪造旧账号的邮箱验证时间。`pnpm auth:cleanup` 继续清理历史过期申请、密码重置凭据及限流记录；迁移的降级保护继续阻止有效凭据或保留数据被丢弃。新注册不会创建邮件申请或密码重置凭据。
