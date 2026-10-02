# GitHub / 飞书登录与身份绑定

## 本地功能与验收边界

默认不启用任何真实 provider。适配器测试使用 `httpx.MockTransport`，API 回归使用 mock provider 与独立临时 PostgreSQL；这不代表真实 GitHub / 飞书登录已验收。

用户先通过已有 Cairn 登录方式登录，再在账号菜单的「登录方式」页面绑定 GitHub 或飞书。绑定要求当前会话、同源请求、CSRF 和十分钟内的认证；用户过期后应退出并重新登录。以后两个已绑定的身份都进入同一 Cairn 用户及其唯一组织成员身份。第三方回调只记录待确认的已验证身份，不设置会话 cookie；返回页面点击「完成登录」后，由浏览器锁保护的一次性 POST 确认发放会话。首次出现的外部身份不会自动创建用户或组织，不会按邮箱、昵称、GitHub login 或飞书 union_id 自动合并账号。GitHub 使用数值用户 ID，飞书使用当前应用的 open_id，唯一键包含 provider 与 client ID。

解绑要求明确确认、CSRF 和近期认证。没有密码时，只有当前已启用、client ID 相同的另一绑定才算可用备选；不能删除最后一种登录方式。服务端行锁与唯一约束处理并发绑定、解绑和登录。第三方令牌只用于一次身份交换，不落库、不交给浏览器，也不用于文档或仓库访问。

## 用户需要完成的配置

1. 确定浏览器入口 `APP_URL`，例如本地 `http://localhost:<Web端口>`，生产必须使用 HTTPS。它只能是 origin，不能含路径、查询参数或凭据。浏览器入口上的 `/api` 必须代理到 API。开发可设置 `CAIRN_API_PROXY_TARGET=http://localhost:<API端口>`；生产由现有反向代理配置。浏览器端 `VITE_IDENTITY_API_URL` 应填写该入口 origin，确保 cookies 与回调使用同一主机。
2. 在 GitHub Developer settings 创建 **OAuth App**，设置 Homepage URL 为 `APP_URL`，Authorization callback URL 精确填写 `${APP_URL}/api/v1/auth/oauth/github/callback`。客户端使用 S256 PKCE；代码不请求仓库、邮箱、离线等额外 scope。勿使用已有授予私有仓库访问的应用来扩大登录授权。
3. 在飞书开放平台准备独立的企业自建网页应用，按当前控制台配置登录授权、适用用户和重定向 URL，精确填写 `${APP_URL}/api/v1/auth/oauth/feishu/callback`。仅配置获取用户基本身份所必需的权限，确认可取得 open_id；本功能不需要文档、知识库、邮箱或离线权限。应用发布及组织管理员允许访问的步骤由用户按本租户规则完成。本阶段没有替用户创建应用或授予权限。
4. 只在 API 进程的本地受保护环境中注入 `CAIRN_OAUTH_GITHUB_CLIENT_ID` / `CAIRN_OAUTH_GITHUB_CLIENT_SECRET` 和（或）`CAIRN_OAUTH_FEISHU_CLIENT_ID` / `CAIRN_OAUTH_FEISHU_CLIENT_SECRET`。每组必须成对、非空。不要提交 secret，也不要添加 `VITE_` 前缀。飞书登录变量与文档 Worker 的 `CAIRN_FEISHU_CREDENTIALS_JSON` 完全独立。
5. 由整合任务先备份目标数据库，执行迁移 `0010_oauth_identities`，再重启目标 API。缺少配置时 provider 显示未启用。当前任务未修改原数据卷或原服务。
6. 用已有密码登录 Cairn，依次绑定两种外部身份。退出后分别完成真实提供方授权，核实 Cairn 用户和组织 ID 相同；同时检查拒绝授权、已被其他账号绑定、已过期、重复回调和退出中途回调的结果。真实第三方授权验收仍须用户配置后执行。

## 登录协议与浏览器要求

前端首次匿名恢复、退出和运行中会话失效都先准备 `/api/v1/auth/login-context`，完成前不显示可操作登录表单。初始化通过同源 Web Locks 串行化，避免多个无 cookie 标签页创建不同浏览器上下文；要求支持 Web Locks 的当前浏览器，通过 HTTPS 或 localhost 访问。无法安全初始化时界面停留在可重试错误状态。

启用了第三方登录的直接 API 客户端，也必须先同源 POST login-context，携带 cookie，再提交密码或 OAuth start。会话失效查询不发送删除 cookie 的响应头，避免迟到查询擦除后来的登录。无效 cookie 在同源初始化或退出时清理；初始化、密码登录和退出都通过同一浏览器锁串行化。OAuth start 必须带预先准备的 cookie，不自行分配上下文。state 和浏览器令牌只存 SHA-256 摘要，授权请求五分钟有效、回调单次消费，GitHub 另有 PKCE。待确认身份五分钟有效，确认时重新检查绑定、账号状态、组织成员身份和 provider 配置；确认不能重放，也不能替换已存在的会话。飞书适配器使用官方 confidential-client 授权码流程；本实现没有声称已验证飞书 PKCE 支持。

回调只使用固定 APP_URL 与白名单路径，忽略 Host/forwarded headers；所有认证回调响应 no-store / no-referrer。已有会话不会被登录回调替换。退出会撤销浏览器 claim 及其已提交的登录会话，迟到响应里的 cookie 无法恢复有效登录。已领取的 claim 摘要有效期为31天，用于处理迟到退出；过期记录在下一次初始化时清理。

## 整合注意事项

- 本分支基于 `6a80fe8`，另一个飞书验收任务完成后由父会话整合；本任务不合并 main、推送或部署。
- 迁移在 `0009_feishu_sync_lifecycle` 之后。`users.password_hash` 可为空。已有用户数据保持不变。若存在外部身份或无密码用户，downgrade 拒绝销毁认证方式，需先由管理员完成账号恢复方案。
- `packages/sdk` 的 OpenAPI、类型及运行时 schema 必须和 API 一起整合；账号菜单、登录页、会话门控与 `/account/identities` 路由也必须同时带入。
- API 全量测试使用独立临时库。现有 PostgreSQL 集成清理 fixture 增加 browser_login_claims，避免新表跨测试遗留。
- 本轮不包含 RAG streaming、多轮会话或 long memory。

## 官方接口参考

- [GitHub OAuth App 授权与 PKCE](https://docs.github.com/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)
- [飞书获取授权码](https://open.feishu.cn/document/authentication-management/access-token/obtain-oauth-code)
- [飞书获取用户令牌 v2](https://open.feishu.cn/document/authentication-management/access-token/get-user-access-token)
- [飞书配置重定向 URL](https://open.feishu.cn/document/develop-web-apps/configure-redirect-urls)
