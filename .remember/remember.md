# Handoff

最后更新：2026-07-26 Day 7 收尾。

## State

**两个仓库**：
- `~/projects/ai-knowledge-base` — Tracebase 主项目。Day 7 全绿，**本次收尾已 commit**。
- `~/projects/xiaochublog` — 博客站主题 + 文章源 + 发布工具链 + `practice/` 学习记录。

**Day 7（TypeScript 工程实践 + Zod 运行时校验）已完成并验收通过。** 但过程有个坑，记清楚：

**接手时是红的。** Day 6 上午收尾后，有一个会话在当天 19:4x 把 Day 7 代码写了一大半（Vite 集成、Zod 装好、`schemas/` 六个文件、全模块迁 `.ts`、写了 `schema-parity.test.mjs`），但**留下的是红的、没 commit、没更新交接**。本次会话接手后修到全绿：

- **typecheck 红**：17 个 `TS5097`，根因是 import 路径直接写 `.ts` 扩展名，而 tsconfig 没开 `allowImportingTsExtensions`。补一行修好——Vite 打包、`node --test` strip-types 都认 `.ts`，选 `.ts` 不选 `.js` 是因为文件真是 `.ts`，import 不该对现状撒谎。
- **test 红**：`schema-parity.test.mjs` 加载即炸。根因是上个会话把顺序做反了——那个测试文件头自己写着「**等它全绿了，再切换调用方**」，但上个会话是 parity 网还红着就先把老 `normalizeDocuments` 删了，导致没有「老」可对照「新」，安全网自我拆除。
- 另有两处迁移收尾没做干净：`documents-transform.test.mjs` 还 import 已删的 `normalizeDocuments`（9 个测试其实已迁到 parity，删掉那部分、保留 filterByStatus/countByStatus/statusLabel）；`html-structure.test.mjs` 还断言入口 `src/main.js`，实际已是 `src/main.ts`。

**怎么证明「新 Zod 层 ≡ 旧 normalizeDocuments」的：** 没有直接信 `schema-parity` 自己写的期望值（那套 schema 和那套期望值是同一个会话写的，会一起错）。而是从 `git HEAD:apps/web/src/lib/documents.js` 取出 Day 5 那份**没被碰过的**老实现当**独立预言机**，拿它并排跑同一批脏数据，逐字节比对——15 条全过（含刻意差异：非数组从 `throw TypeError` 变成 `throw ApiError("contract")`，两者都拒绝，新的带 kind 让 UI 能关掉重试按钮）。证完等价后，才把提交进仓库的 `schema-parity.test.mjs` 从「并排比对旧实现」转成「Phase 2 回归护栏」（只测新层）。

**验证（三关全绿）：** `pnpm typecheck` 0 错；`pnpm test` 28/28；`pnpm verify` 八帧全过，JS 零错误，Vite→浏览器整条链打通（文档真走了 `parseList` 校验层才渲染出 4 行），且「超时文案 ≠ 断网文案」证明 `ApiError.kind` 在真实分类。

## Day 7 的代码地图（都在 apps/web/src/）

- `schemas/primitives.ts` — 跨资源共用字段。`ResourceIdSchema = union([number, string])`，**故意不 coerce**（coerce 会把 null 变 "null" 这种看着合法的脏值，正是 Day 5 bug 的形状）。
- `schemas/documents.ts` — **两套文档形状**：`DocumentDtoSchema`（严格契约，status 三种、title 非空，当文档 + Day 19 后端自测用）vs `DocumentSchema`（日常宽松，title 坏给占位符、status `.catch("unknown")` 降级、多字段自动剥）。`.catch("unknown")` 建在**四值**的 `DocumentStatusSchema` 上而非三值的 `KnownStatusSchema`，否则得靠 `as never` 硬掰。`type Document = z.infer<...>`，类型从 schema 派生。
- `schemas/parse.ts` — 两种拒绝策略：`parseOrThrow`（全有或全无，单个关键对象用）vs `parseList`（逐条筛、报 dropped 计数，列表用）。抛 `ApiError` 而非 `ZodError`：UI 不该 import zod，这是「模块边界 = 哪些类型允许跨过去」的实际含义。`parseList` 整体不是数组必须**抛错**（契约整个坏了），不能降级返回 `[]`（会把后端故障谎报成"你没有文档"）。
- `schemas/users.ts` / `schemas/conversations.ts` — 用户、对话、引用的 schema（对应大纲 Day 7「为用户/文档/对话/引用/API 错误定义类型与 Schema」）。
- `api/errors.ts` — `ApiError` 加第五种 kind `"contract"`，`retryable` 对它返回 false（代码 bug，重试一万次一样）。`toApiError(unknown)` 收编 catch 到的任意东西。
- `api/documents.ts` — `fetchDocuments` 在网络边界调 `parseList`，往上传 `dropped`。
- `lib/documents.ts` — 只剩纯函数（filterByStatus/countByStatus/statusLabel），归一化已搬走。`statusLabel(status: unknown)` 的 Day 6 未决问题：Day 7 定了保持 `unknown`——校验层现在收口不可信数据，但这函数还服务绕过校验层的调用者（测试、将来的 localStorage/URL 参数）。

## Next

1. **Day 8：React 组件与状态**（大纲）。学 JSX、函数组件、Props、State、事件、列表 key、组件组合。项目：拆分侧栏、文档列表、上传区、消息列表、输入框、引用组件。验收：组件职责单一无超大页面组件，交互状态不互相污染。求职：用自己的话解释 React 声明式渲染和状态更新。
2. `state/documentStore` 迁 TS 时按可辨识联合重写 state 形状（Day 6/7 一直挂着的活）。注意 `documentStore.js:54` 的 `error.message`：catch 到的是 unknown，用 `toApiError` 收编。
3. **给「错误 API 数据被校验层拒绝」加一个浏览器现场演示**（可选、非阻塞）：mock 目前只有 success/empty/error/slow 四个场景，没有「脏数据」场景。这条验收现在只在单元测试里证明了，没在浏览器里跑过。要现场演示得给 mock 加个 dirty 场景 + UI 消费 `dropped` 计数。
4. **积压：Day 5 博客未发布**。草稿 `~/projects/xiaochublog/docs/blog/2026-07-25-es-modules-layering-testing.md`，slug `es-modules-layering-unit-testing`，13KB 超 11KB 历史失败线，用 `blog-to-wordpress` skill 的分块写入。封面用户自己挑。
5. **Day 6 博客也没写**（选题「类型系统能抓什么、抓不到什么」，Step 7 实测是现成材料）。
6. **Day 7 复盘未写**：`~/projects/xiaochublog/practice/day7-review.md` 还没建（用大纲第 8 节模板）。xiaochublog 仓库还有个上个会话遗留的 `practice/day6-review.md` 未提交。
7. Recheck the `wpmu.php` null guard after any Colibri Page Builder update.

## 本次已发布

**Day 7 配套博客已发布**：post 1014，slug `typescript-basics-labels`，
https://xiaochublog.top/typescript-basics-labels/ 。选题「TypeScript 入门：给 JavaScript 的每样东西提前贴一张标签」，面向零基础、去掉 C++ 对照、贯穿「贴标签」类比。分类 Web开发，标签 TypeScript(新建 id 60)/JavaScript/前端/前端入门。封面用户自己挑的淡紫抱杯图（attachment 1023）。线上验证过：HTTP 200、8 章齐、无锚点残留、代码块正常。

## Learned（Day 7）

**1. 自证测试发现不了「schema 和期望值一起写错」。** 用 Zod 重写一层校验时，最大风险不是写不出来，是「写出来了但悄悄放宽了当年抓 bug 的那一条」。而如果新 schema 和验证它的测试是同一个人/同一次写的，测试的期望值可能跟着一起错，自证测试照样绿。破法是引入**独立预言机**——本次是从 git 取未被改过的 Day 5 老实现当裁判。凡是「用新实现替换旧实现」的迁移，都该找一个旧实现没被这次改动碰过的版本来对照。见 [[types-vs-runtime-boundary]]。

**2. 删旧实现的时机：安全网全绿之后，不是之前。** `schema-parity` 文件头写的顺序（先证等价、再切调用方、最后退休老实现）是对的，上个会话做反了就留下一片红。迁移的正确姿势是新旧并存到证明等价为止。

**3. `.ts` 扩展名 import 的三方分歧。** Node `--test`（strip-types）、Vite（bundler 解析）都认 import 里写 `.ts`；`tsc` 默认拒绝，要 `allowImportingTsExtensions`（只在 noEmit/bundler 下成立）。这不是配置玄学，是「同一份代码三个工具三种解析」的真实边界。

## 未决 / 设计问题（Day 8+）

`state/documentStore` 还没迁 TS。迁的时候 state 形状要改成可辨识联合（Day 6 Task 3 学过的形状），让「加载中不可能同时有错误」这类矛盾状态在类型上就构造不出来。

## Context

**范围决策（2026-07-25）**：35 天范围不变；之后接约 60 天 Phase 2，把 Tracebase 扩成飞书/Glean 式企业统一搜索。Day 17 必须把 `documents` 建成通用 `resources` 表（`source_type` / `source_id` / `external_id`（与 source_id 组唯一约束保证摄取幂等）/ `source_updated_at` / `acl_principals text[]` + GIN 索引 / `metadata JSONB`），即使当时只有 upload 一个来源。Day 24 检索带 `source_type` 过滤。这些约束也写在 `apps/api/README.md` 里。Day 7 的 `schemas/` 已经在为这个铺路：`ResourceIdSchema` 抽在 `primitives.ts`，Day 17 收紧成 uuid 只改一处。

**用户 2026-07-26 明确要求加快最终项目进度**。教学节奏压缩：语法演示批量跑结论，重心放真迁移和实测，最后用问答验收。但阶段验收关不跳。**注意**：Day 7 的问答验收（5 道题：模块边界、DTO vs 领域模型、两种拒绝策略、`.catch` 建在哪、独立预言机为什么必要）**本次没做完就去写博客了**，用户选择「修复到绿再问答验收」但中途转去写博客并直接收尾。Day 8 开始前可补问一下，或直接推进。

学习者是 **vibe coding 模式**：不手写代码，考核逐行解释、代码审查、定规格、验证。有 C++/Qt/多线程/网络/Python/LangChain/RAG 背景，讲前端可用其工程直觉类比；但**博客面向基础同学，要去掉 C++ 对照**。

权威大纲：`/mnt/e/AI_Fullstack_35_Day_Plan.md`，复盘用第 8 节模板。

**博客发布经验（本次新增/确认）**：
- 用 `rest_api` 的 **`query` 结构化对象**传中文，工具自己做百分号编码，能避开 skill 记的 `body` 中文 bug（body 带一个中文字就报 `expected string, received object`）。本次八块全用 query 传成功。
- 分块用 `<!--NEXT-->` 锚点 + `/wpvibe/v1/content/edit` 逐块 `str_replace` 追加，最后一块不带锚点。每块原文 ≤2.4KB（编码后约 6KB，稳在 URL 限内）。追加前先本地脚本校验「所有块拼回逐字节等于原文」，追完核对最终 bytes == 本地文件字节数（本次 16856 完全吻合）。
- **封面用户自己挑**：本地图用 `request_upload` → 用户拖进面板 → `check_upload` 取 staging URL → `upload_media` 入库 → PUT `featured_media`。别 `search_images`。
- 发布需显式批准，不用 subagent，未经授权不 commit。WPVibe OAuth 已连接。主题在 `/www/wwwroot/xiaochublog.top/wp-content/themes/colibri-wp`，回滚副本 `/www/backup/xiaochublog-theme-before-manual-release-/colibri-wp` 不要删。
- `content/search` 端点要 POST（GET 会 404）。核查线上用 `get_page_html`（服务端渲染）或 curl 抓 HTML。本环境 Playwright MCP 缺 chrome 二进制，截不了图。

**注意**：`~/.claude/settings.json` 里 `ANTHROPIC_BASE_URL` 指向第三方中转端点 `https://www.lingzhan.top`，`ANTHROPIC_AUTH_TOKEN` 明文存储。会话内容都经由该第三方。已告知用户，处理生产密钥前值得重新评估。
