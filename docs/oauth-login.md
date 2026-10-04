# GitHub / 飞书注册、登录与身份绑定

## 本地功能与验收边界

默认不启用任何真实 provider。适配器测试使用 `httpx.MockTransport`，API 回归使用 mock provider 与独立临时 PostgreSQL。2026-10-03 已另外完成 GitHub / 飞书首次注册、显式身份绑定和再次登录的真实授权验收；部署者仍需配置自己的应用与回调地址，自动化门禁不使用真实凭据。

首次 GitHub／飞书授权在第三方回调中只保存短期已验证身份，不创建账号、组织或会话。用户返回 Cairn 并完成最终确认后，首次身份在同一事务中创建独立 User、个人 Organization、owner Membership、ExternalIdentity 与会话；没有邮箱时 email 和 normalized_email 为 null，不制造邮箱地址。新账号不能读取已有组织或项目，也不会按邮箱、昵称、GitHub login、飞书租户或 union_id 自动合并或加入已有组织。GitHub 使用数值用户 ID，飞书使用当前应用的 open_id，唯一键包含 provider 与 client ID。

已有 Cairn 用户可先登录，再在账号菜单的「登录方式」页面显式绑定另一身份。绑定要求当前会话、同源请求、CSRF 和十分钟内的认证；认证过期后应退出并重新登录。以后两种已绑定身份都进入同一 Cairn 用户及其唯一组织成员身份。回调不设置会话 cookie；最终确认由浏览器锁和一次性服务端 claim 保护。已有绑定在回调后被解绑或用户被禁用，最终确认拒绝，不创建替代账号。

解绑要求明确确认、CSRF 和近期认证。没有密码时，只有当前已启用、client ID 相同的另一绑定才算可用备选；不能删除最后一种登录方式。服务端行锁与唯一约束处理并发绑定、解绑和登录。第三方令牌只用于一次身份交换，不落库、不交给浏览器，也不用于文档或仓库访问。

## 用户需要完成的配置

1. 确定浏览器入口 `APP_URL`，例如本地 `http://localhost:<Web端口>`，生产必须使用 HTTPS。它只能是 origin，不能含路径、查询参数或凭据。浏览器入口上的 `/api` 必须代理到 API。开发可设置 `CAIRN_API_PROXY_TARGET=http://localhost:<API端口>`；生产由现有反向代理配置。浏览器端 `VITE_IDENTITY_API_URL` 应填写该入口 origin，确保 cookies 与回调使用同一主机。
2. 在 GitHub Developer settings 创建 **OAuth App**，设置 Homepage URL 为 `APP_URL`，Authorization callback URL 精确填写 `${APP_URL}/api/v1/auth/oauth/github/callback`。客户端使用 S256 PKCE；代码不请求仓库、邮箱、离线等额外 scope。勿使用已有授予私有仓库访问的应用来扩大登录授权。
3. 先检查已有飞书自建应用的网页登录能力、安全设置和适用用户；能支持当前授权码流程时可复用，无需重复建应用。需要添加应用能力、扩大权限或新建应用时由用户单独确认。按当前控制台配置重定向 URL，精确填写 `${APP_URL}/api/v1/auth/oauth/feishu/callback`。仅配置获取用户基本身份所必需的权限，确认可取得 open_id；本功能不需要文档、知识库、邮箱或离线权限。应用发布及组织管理员允许访问的步骤由用户按本租户规则完成。本阶段没有替用户创建应用或授予权限。
4. 只在 API 进程的本地受保护环境中注入 `CAIRN_OAUTH_GITHUB_CLIENT_ID` / `CAIRN_OAUTH_GITHUB_CLIENT_SECRET` 和（或）`CAIRN_OAUTH_FEISHU_CLIENT_ID` / `CAIRN_OAUTH_FEISHU_CLIENT_SECRET`。每组必须成对、非空。不要提交 secret，也不要添加 `VITE_` 前缀。飞书登录变量与文档 Worker 的 `CAIRN_FEISHU_CREDENTIALS_JSON` 完全独立。
5. 首次验收使用全新隔离数据库并完成最新迁移，当前为 `0012_native_registration`。升级已有部署时按既定备份和迁移流程处理；缺少配置时 provider 显示未启用。
6. 用未绑定身份分别验收两家首次注册，确认产生独立个人组织、没有邮箱时保持为空、不能访问既有项目。再从该账号绑定第二身份，退出后分别授权登录，核实 Cairn 用户和组织 ID 相同。已有密码账号绑定、拒绝授权、已被其他账号绑定、过期、重复回调和退出中途回调也须检查。更换应用或回调配置后，须针对该部署重新验证。

## 登录协议与浏览器要求

前端首次匿名恢复、退出和运行中会话失效都先准备 `/api/v1/auth/login-context`，完成前不显示可操作登录表单。初始化通过同源 Web Locks 串行化，避免多个无 cookie 标签页创建不同浏览器上下文；要求支持 Web Locks 的当前浏览器，通过 HTTPS 或 localhost 访问。无法安全初始化时界面停留在可重试错误状态。

启用了第三方登录的直接 API 客户端，也必须先同源 POST login-context，携带 cookie，再提交密码或 OAuth start。会话失效查询不发送删除 cookie 的响应头，避免迟到查询擦除后来的登录。无效 cookie 在同源初始化或退出时清理；初始化、密码登录和退出都通过同一浏览器锁串行化。OAuth start 必须带预先准备的 cookie，不自行分配上下文。state 和浏览器令牌只存 SHA-256 摘要，授权请求五分钟有效、回调单次消费，GitHub 另有 PKCE。待确认身份五分钟有效，确认时重新检查绑定、账号状态、组织成员身份和 provider 配置；确认不能重放，也不能替换已存在的会话。飞书适配器使用官方 confidential-client 授权码流程；本实现没有声称已验证飞书 PKCE 支持。

回调只使用固定 APP_URL 与白名单路径，忽略 Host/forwarded headers；所有认证回调响应 no-store / no-referrer。已有会话不会被登录回调替换。退出会撤销浏览器 claim 及其已提交的登录会话，迟到响应里的 cookie 无法恢复有效登录。已领取的 claim 摘要有效期为31天，用于处理迟到退出；过期记录在下一次初始化时清理。

## 整合注意事项

- OAuth、原生注册、项目工作台和生成 SDK 必须作为完整版本部署；服务启动前应完成数据库迁移。
- OAuth 基线迁移为 `0010_oauth_identities`，首次注册迁移为 `0011_oauth_registration`。`users.email`、`normalized_email`、`password_hash` 可为空，已有用户数据和标准化邮箱唯一约束保持不变。首次注册迁移降级遇到无邮箱用户时拒绝；OAuth 基线降级遇到外部身份或无密码用户也拒绝，需先由管理员完成账号恢复方案。
- `packages/sdk` 的 OpenAPI、类型及运行时 schema 必须和 API 一起整合；账号菜单、登录页、会话门控与 `/account/identities` 路由也必须同时带入。
- API 全量测试使用独立临时库。现有 PostgreSQL 集成清理 fixture 增加 browser_login_claims，避免新表跨测试遗留。
- 本轮不包含 RAG streaming、多轮会话或 long memory。

## 官方接口参考

- [GitHub OAuth App 授权与 PKCE](https://docs.github.com/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)
- [飞书获取授权码](https://open.feishu.cn/document/authentication-management/access-token/obtain-oauth-code)
- [飞书获取用户令牌 v2](https://open.feishu.cn/document/authentication-management/access-token/get-user-access-token)
- [飞书配置重定向 URL](https://open.feishu.cn/document/develop-web-apps/configure-redirect-urls)
