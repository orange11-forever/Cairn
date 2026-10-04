# Cairn 原生邮箱验证注册

用户在 20:44 新增原生注册，20:47 确认邮箱＋密码且必须验证邮箱后才能使用，21:00 确认先完成代码与本地邮件测试，真实 SMTP 以后配置。本功能在独立树 feat-native-email-registration-20261003 续作，基线完整保留已验证的 32 个 OAuth／布局候选文件；原 OAuth 树继续真实授权验收，互不改写。

## 行为

注册提交只保存短期 PendingRegistration，不创建 User、Organization、Membership 或会话。提交有效邮箱、12–128 字符密码和可选显示名；密码保留原始字符，只存 Argon2 哈希。验证码与重发 receipt 用独立高熵随机值，只存 SHA-256 摘要。邮件链接有效 30 分钟，重发不会无限延长尝试寿命。

邮件链接使用固定 APP_URL 的 `/register/verify#token=...`。GET、HEAD、预取、扫描和页面挂载不消费令牌或创建账号；页面把 fragment 令牌取入内存后清除地址栏。用户输入原注册密码并明确确认，POST 验证邮箱令牌及密码。验证成功在单一事务里创建邮箱用户、随机个人组织、owner Membership 和审计，并标记验证单次消费；不自动发放／清理／替换任何浏览器会话。用户随后正常密码登录。已有密码及 OAuth 用户维持原行为。

新账号不按邮箱／名称合并、不加入已有组织，不为既有用户设置密码、不重新启用禁用用户。邮箱 casefold 唯一约束仍为最终权威；同令牌及同邮箱不同尝试并发验证只形成一个用户／组织，无孤立行。拥有 pending 邮箱不构成预约，另一申请不能改写原申请密码或阻止原申请完成。验证令牌＋密码确认防止单纯邮件扫描／误点激活别人设置的密码。

## 邮件及接口

标准 SMTP 发送，后端配置独立于 OAuth；默认关闭注册。运营者显式启用且邮件配置可用后才开放，不具备 SMTP 时保留可说明状态，不伪称已经发送。使用 smtplib／EmailMessage，生产要求 STARTTLS 或隐式 TLS、证书验证和认证；无 TLS 只限显式 test 环境的本机捕获服务。超时 10 秒，前端发送超时 15 秒，不打印 SMTP 调试／密码／验证 URL。

公开稳定契约：GET `/api/v1/auth/registration` 返回 `{enabled}`；POST `/api/v1/auth/register` 接受 `{email,password,displayName?}`，成功 202 `{message,registrationReceipt,resendAfterSeconds}`；POST `/api/v1/auth/register/resend` 接受 `{registrationReceipt,email,password}`，同样 202；POST `/api/v1/auth/register/verify` 接受 `{token,password}`，成功 200 `{message}`。所有变更要求精确 Origin，接口均不发 session cookie。既有邮箱、无效重发 receipt 采用通用 accepted 文案和不可用 decoy receipt，不能改变已有账号。无效／过期／重放验证 400，过频 429＋Retry-After，邮件失败 503，数据库及未知异常沿用标准错误。

SMTP 与 DB 不是同一事务：先提交短期状态与发送额度，SMTP 在锁外发送。确定失败按 token generation 保护失效处理，不能使较新的重发失效；发送结果不宣称入箱。重发原子轮换令牌，旧链接立即失效。邮件失败仍计入额度。同步发送的时延并不构成完美的邮箱存在性隐藏，本轮不引入加密发信 outbox。

独立 purpose-scoped 持久限流，不与密码登录互相清除：重发冷却 60 秒、每邮箱 5 次／小时、每 IP 20 次／小时；验证每 IP 20 次／15 分钟、每尝试 5 次错误密码／15 分钟。计数原子并发、失败计数提交，锁顺序一致。清理过期／已消费 pending 与旧额度，不长期保留废弃邮箱／密码哈希。

## UI／交付边界

登录页添加原生注册入口；注册、查收邮件、重发、输入密码确认、验证成功返回登录形成真实流程。沿用山峰品牌、岑宁、明暗主题、原表单和 44px 控件。敏感令牌、receipt、密码不写 localStorage；页面变化取消读取／忽略迟到结果，任何注册响应均不调用 establishSession。无 SMTP 的产品提示说明暂不可注册，不展示部署实现细节。

迁移 0012 接在 0011 后；保留现有用户。SMTP 后端变量只有 API 读取，不含 VITE 前缀；不使用用户 OAuth 密钥、不发送外部真实邮件。已有认证／跨组织权限／SDK／浏览器锁回归保留。真实邮件入箱与链接验证待 SMTP 配置，必须单独报告为未验收。

先消费端 RED 再实现。独立临时 cairn_test 和本机邮件捕获服务；不使用 OAuth 验收库或历史卷。断言账户／组织／会话创建时点、密码及 token 安全、扫描／重放／过期／并发、邮件／DB／意外错误回滚、重发与额度、既有账号／旧组织拒绝、正常密码登录及后续显式 OAuth 绑定。HTTP 状态／完整 schema／traceId-X-Request-ID／CORS／安全及协议头／无 session Set-Cookie、OpenAPI／SDK 生成一致性均检查。最终 pnpm verify；规格先、质量后，不同上下文。未全部约定验收前不提交、合并、推送、PR 或部署。
