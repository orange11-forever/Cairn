# Handoff

最后更新：2026-07-29（站点维护 + Qt 文档日，**没有推进 Day 9**）。

## 本次会话（2026-07-29）做了什么

**不是学习日**，全部是收尾和站点维护。三个 commit，两个仓库工作区都干净：

- `xiaochublog` **f1c0556** — Day 8 两篇博客文章源入库
- `xiaochublog` **2b61211** — Qt/C++ 飞书文档（新目录 `docs/feishu/`）
- `ai-knowledge-base` **526bde3** — 交接笔记更新到 Day 8

**1. Day 8 第二篇博客已发布**：post 1043 `safely-replacing-a-layer`《怎么安全地换掉一层》，八节 18309 字节，分类 19，标签 React/代码审查/前端/单元测试/系统架构，封面 1059。线上逐项核验过（八节齐、代码块转义正常、无锚点残留、上一篇导航正确）。**开头找了很久那篇"遗留的 C++ 博客"其实不存在**——C++ 那篇（post 996）2026-07-25 就发了，用户记混了，遗留的是 Day 8 这篇。

**2. 站点性能实测**（移动/桌面）：性能 91/92、可访问性 95、最佳实践 100。LCP 1.0–1.5s、TBT 0ms、**CLS 已经是 0**（之前的 0.08 没了）。Lighthouse 无优化项。Speed Index 移动端 9.3–9.8s 仍飘，属主机 TTFB。

**3. 确认这是私人博客**：用户明确说不对外公开，`blog_public=0` 是有意的。**SEO 分数（66）以后永远别报**——唯一扣分项就是 noindex，正是想要的效果。已告知 noindex ≠ 私密（要真私密得加登录墙/密码保护），用户没要求做。写进 [[wordpress-blog-setup]]。

**4. 站点标题改为 `Aliya-devlog`**。注意 `blogname` 驱动三处：浏览器标签、左上角品牌名、**首页 hero 大标题**（`front-page.php` 渲染的就是站点名）。用户没反对 hero 一起变。想让 hero 保留独立文案得改模板。

**5. 删掉首页标题的流动白光** —— 踩了个大坑，已写进 [[wpcode-snippet-dual-storage]]：**WPCode Lite 把片段代码存两份**，`post_content`（编辑器显示的）和 `wpcode_snippets` 选项（**前台实际输出的**）。我改了 `post_content` 三处（`.home-intro h1::after` 块、`@keyframes heroShine`、reduced-motion 覆盖），`replaced:1` 全成功、大括号也核对过，但白光照旧——因为选项那份没同步。**期间走了一串弯路**：以为是浏览器缓存让用户开无痕、查 LiteSpeed CCSS/UCSS、`litespeed-purge all`、甚至去数用户截图的像素亮度（那些亮区是背景夜景图自己的城市灯光 RGB≈(136,131,152)，会误导）。最后用户进 wp-admin 看了一眼，WPCode 自动用 `post_content` 重建了选项缓存，白光就没了。用户以为是缓存问题，已纠正过。

**6. 写了 Qt/C++ 基础入门文档**：`~/projects/xiaochublog/docs/feishu/qt-cpp-getting-started.md`，1.5 万字八节，面向零基础同学。**我没有飞书接入能力**（无 API 凭据、无 MCP），只产出 Markdown，用户需自己粘贴或导入飞书。一开始说"直接粘进飞书就能用"让用户误以为云文档已建好，已澄清。

## State

**两个仓库**：
- `~/projects/ai-knowledge-base` — Tracebase 主项目。**Day 8 已 commit `d065931`**（24 文件，+1397/-206），工作区干净，未推远端（本项目一直只做本地提交）。
- `~/projects/xiaochublog` — 博客站主题 + 文章源 + 发布工具链 + `practice/` 学习记录。

**Day 8（React 组件与状态）已完成，三层验证全绿**：`pnpm typecheck` 0 错 / `pnpm test` 42 全过 / `pnpm verify` 九帧通过。

设计文档在 `docs/superpowers/specs/2026-07-27-day8-react-components-design.md`（三个已定决策 + 明确不做的五项都在里面）。

## Day 8 的代码地图

**依赖**：`react`/`react-dom` 19.2.8、`@vitejs/plugin-react` **5.2.0**（不是 6.x——6.0.4 要 vite ^8，我们是 7.1.12，报未满足 peer；5.2.0 的 peer 范围同时含 ^7 和 ^8，将来升 vite 8 也不用动）。全部 `-E` 精确锁版。

**组件（9 个，都在 `apps/web/src/components/`）**
- 大纲六项：`Sidebar` `DocumentList` `UploadZone` `MessageList` `MessageInput` `Citation`
- 另外三个：`StatusBar`、`DocumentsPanel`（**唯一消费 store 的组件**）、`AssistantPanel`（持有 messages 本地 state）
- `App.tsx` 只做布局组合——**里面出现 useState 或 await 就说明状态提得太高了**，这条约束是「无超大页面组件」验收的落点。

**状态**
- `state/useDocumentStore.ts` 用 `useSyncExternalStore(store.subscribe, store.getState)` 桥接，`documentStore.ts` 一行未改。
- store 必须模块级单例（写组件体里 = 每次渲染造新 store，状态永远回 idle 还可能死循环）。
- `getSnapshot` 要求状态未变时返回同一引用。现有 store 恰好满足，因为 `setState` 是整体替换而非合并——**那个决定当初纯粹是为「可辨识联合不能合并」的类型正确性做的**，在这里意外满足了一个无关的运行时要求。
- `UploadZone`/`MessageInput` 持本地 state，和 store 的服务端状态对照（铺垫 Day 9/10）。

**抽离**
- `lib/statusText.ts` — `describeStatus(state) => {tone,text}` 从旧 `renderStatusBar` 抽出。硬理由：Node `--test` 不认 JSX，纯 `.ts` 才能直接单测；原来嵌在 DOM 操作里，只能靠八帧脚本验证。
- `ui/` 目录（`main.ts`/`statusBar.ts`/`documentList.ts`）**已删**，先证新层等价再删旧实现（Day 7 教训）。

**纯逻辑层 `api/`/`schemas/`/`lib/documents.ts`/`documentStore.ts` 一行未改**——换 UI 框架没波及任何业务逻辑，这是 Day 5 分层的回报，本次实测确认。

## 验证的三个变化

1. `tests/web/status-text.test.mjs` 新增 14 个（总数 28 → 42）。
2. `html-structure.test.mjs` / `css-contract.test.mjs` 瘦身：结构断言搬进浏览器（结构进了组件，检查跟着进）；静态测试只留 `index.html` 真正拥有的东西（lang/charset/stylesheet/`#root`/入口 `.tsx`），CSS 侧改为守「CSS 文件仍持有组件渲染的那些钩子」——这个方向同样会坏且更隐蔽（改了 class 名页面照渲染，只是样式静悄悄失效）。
3. `verify-web.mjs`：**既有八帧一条未改**（独立回归网，逐帧与 Day 7 一致），追加两段——
   - **结构关卡，必须在首次截图之前跑**：Playwright 的 `fullPage` 截图会临时注入样式并留残留，晚一步就会被测量工具自己弄脏（第一次跑就撞上了，报「内联样式 2 处」而源码里 0 处）。
   - **第九帧「状态污染」**：写好草稿 + 选好文件后跑完整轮加载，断言草稿/已选文件完好且列表正常更到 4 行。这类「重渲染吃掉用户输入」是换渲染层引入的新失败模式，手写 DOM 时代不存在。
   - `expect` 从 try 块里的 `const` 提成模块级函数声明——结构关卡在它之前调用会撞 TDZ 直接崩。

## Next

1. **Day 9：Hooks、表单与副作用**（大纲第 9 天）。学 `useState`/`useEffect`/`useMemo`/`useRef`、受控表单、自定义 Hook、何时不该用 Effect。项目：登录表单、上传表单、消息输入、自动滚动、请求取消。测试：引入 Vitest + React Testing Library 测表单校验与消息渲染。验收：关键表单有可读错误；测试关注用户行为而非组件内部。
2. **两件我没能亲自核验的事**（2026-07-29 撞上 WPVibe 免费版 24 小时用量上限，额度约 **2026-07-30 08:15 UTC**（北京时间 7/30 下午 4:15）恢复）：
   - **确认 `wpcode_snippets` 选项里那三段扫光代码真的清掉了**。`wp option pluck wpcode_snippets site_wide_header 0 code` 读回来比对。白光消失只是间接证据；万一那份缓存被某个操作回滚，白光会复发，处理办法是让用户去后台重新保存一次片段。
   - **可访问性扣的 5 分是一处 `color-contrast`**（对比度不足）。`audit_page` 不返回具体元素，要定位得用 PageSpeed Insights 网页版看那一项的元素列表，或读主题 CSS 逐个算对比度。用户没催，可以留到下次动样式时一起做。
3. **Qt 飞书文档等用户自己导入**：文件已 commit（2b61211），用户需在飞书里粘贴或用「导入 Markdown」。Windows 侧路径 `\\wsl$\Ubuntu\home\chr\projects\xiaochublog\docs\feishu\qt-cpp-getting-started.md`。**别再说"已经建好飞书文档"**。
4. **Day 8 复盘未写**：`~/projects/xiaochublog/practice/day8-review.md`（用大纲第 8 节模板）。`practice/day6-review.md` 已 commit（b0aec34），`day7-review.md` 仍未建。
5. Day 7 的 5 道问答验收——**用户 2026-07-27 明确说忽略**，不用再提。
6. `mock` 加 dirty 场景 + UI 消费 `dropped` 计数（可选、非阻塞，从 Day 7 挂到现在）。
7. Recheck the `wpmu.php` null guard after any Colibri Page Builder update.

## 未决 / 设计问题

- **`describeStatus` 的误导文案**：`documents` 为空且 `dropped > 0` 时（校验层丢光所有数据）命中 empty 早返回，显示「还没有文档，上传第一个吧」——可用户明明上传过，真相是前端一条都没看懂。Day 8 刻意没改（改了会让八帧的「行为等价」判决失效），当前行为已固定进 `status-text.test.mjs` 的「全部被丢掉」用例并注明理由。**Day 12 接正式请求层时重新考虑。**
- **`Sidebar` 组件名与现实不符**：它渲染的是横向顶栏 `.product-header`，名字跟的是大纲措辞。Day 11 迁 Next.js 重排布局时一起改，今天为改名去动 CSS 类名不值得。

## Learned（Day 8）

**1. 断言报错时先分清三种情况**：断言写错了 / 代码真有问题 / **测量方式有问题**。结构关卡第一次报「内联样式 2 处」，源码里 0 处、单独探针查也是 0 处——两个结果都真，差别是有没有先截图。根因是 Playwright `fullPage` 截图污染了被测对象。当时完全可以把断言从「必须 0 处」放宽到「不超过 2 处」让它过去，代价是这条检查从此永久瞎掉。修的是测量时机，不是断言。

**2. 验收的裁判必须没参与被验收的改动。** 换渲染层时组件照原样输出既有 id 和 `data-*`，不是因为那套选择器更好，而是不改它，八帧脚本才仍然是独立裁判。如果同时换选择器 + 改断言，全绿只证明「新代码和新断言自洽」——同 Day 7 的独立预言机那一课。

**3. 测试成本决定了哪些问题会被问。** `describeStatus` 抽成纯函数后，问「dropped=4 但列表为空时文案对不对」只需三行；原来嵌在 DOM 操作里，得起 mock 服务器 + 浏览器，成本高到没人愿意为边缘 case 加一帧，于是那个问题一直没被问。

**4. 接入新框架时让新框架适应旧代码。** 选 `useSyncExternalStore` 而不是把 store 重写成 Context/状态库：后者等于把 store 里那些实战细节（取消在飞请求防陈旧响应、用户取消不算错误、四态可辨识联合）全部重新经历一遍风险，而它们跟 React 半点关系没有。

## Context

**范围决策（2026-07-25）**：35 天范围不变；之后接约 60 天 Phase 2，把 Tracebase 扩成飞书/Glean 式企业统一搜索。Day 17 必须把 `documents` 建成通用 `resources` 表（`source_type` / `source_id` / `external_id`（与 source_id 组唯一约束保证摄取幂等）/ `source_updated_at` / `acl_principals text[]` + GIN 索引 / `metadata JSONB`），即使当时只有 upload 一个来源。Day 24 检索带 `source_type` 过滤。这些约束也写在 `apps/api/README.md` 里。`schemas/primitives.ts` 的 `ResourceIdSchema` 已在铺路，Day 17 收紧成 uuid 只改一处。

**用户要求加快最终项目进度**。教学节奏压缩：语法演示批量跑结论，重心放真迁移和实测。但阶段验收关不跳。

学习者是 **vibe coding 模式**：不手写代码，考核逐行解释、代码审查、定规格、验证。有 C++/Qt/多线程/网络/Python/LangChain/RAG 背景，讲前端可用其工程直觉类比；但**博客面向基础同学，要去掉 C++ 对照**。

权威大纲：`/mnt/e/AI_Fullstack_35_Day_Plan.md`，复盘用第 8 节模板。

**博客发布（2026-07-27 实测更新）**：
- `rest_api` 的 **`body` 参数又坏了**（带中文报 `expected string, received object`，纯 ASCII 也报）。**可靠路径是把参数百分号编码进 route 查询串**，那天 14 次写入全走这条零失败。
- **socket 中断后不要盲目重试**：先查 `modified` 时间戳 + `content/search` 搜特征句和锚点，证明写入没生效才重试。直接重试会重复一整块，而锚点机制让它看起来一切正常。
- 分块用脚本校验「拼回逐字节等于原文」，最后核对线上 bytes == 本地字节数（21045 == 21045）。900 字节原文 ≈ 5KB route，稳。
- 封面图**用户自己挑**：`request_upload` → 用户上传 → `check_upload` 拿 staging URL → `upload_media` 入库 → PUT `featured_media`。别 `search_images`。
- `get_page_html` 的 selector 只吃裸标签/单 class/单 id，`nav.primary-nav` 这种组合写法不支持。
- 发布需显式批准，不用 subagent，未经授权不 commit。本环境 Playwright MCP 缺 chrome 二进制，截不了图（但项目自己的 `pnpm verify` 用的是 devDependency 里的 playwright，能正常跑）。
- **2026-07-29 复核**：路子仍然有效，16 块零失败。两个新坑——① `get_page_html` 传 `path=` 会走草稿主题预览分支并报「No draft theme to preview」，必须传完整 `url=`；② 本机 shell 的 `curl` 连 xiaochublog.top 直接 TLS 握手失败（`SSL_ERROR_SYSCALL`），线上核验只能靠 MCP，别浪费时间调 curl 参数。`upload_media` 的 `title` 会变成媒体库文件名，传中文标题就得到百分号编码的图片 URL（能用但难看）——**下次传 ASCII title**。
- **Day 8 两篇博客均已上线**：post 1024 `react-basics-declarative-rendering`、post 1043 `safely-replacing-a-layer`（2026-07-29 发，八节 18309 字节，分类 19，标签 React/代码审查/前端/单元测试/系统架构，封面 1059）。

**站点主题（2026-07-27 改动）**：按用户要求删掉了顶部导航的 C++ 项，现在是首页/文章/专题/关于/搜索五项。那一项是 `header.php` 里 `get_category_by_slug('cpp')` 动态生成的（连 `if/endif` 四行），搜 `category/cpp` 搜不到。改主题走 `create_draft_theme` → 改 → 预览 → `publish_draft_theme`，备份在 `colibri-wp-wpvibe-backup`。首页专题区是分类驱动的，删导航不影响它。

**注意**：`~/.claude/settings.json` 里 `ANTHROPIC_BASE_URL` 指向第三方中转端点，`ANTHROPIC_AUTH_TOKEN` 明文存储。会话内容都经由该第三方。已告知用户，处理生产密钥前值得重新评估。
