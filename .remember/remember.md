# Handoff

最后更新：2026-07-25 Day 5 收尾。

## State

**两个仓库**（2026-07-25 拆分，Git 之前零 commit，所以拆分没有改写历史）：
- `~/projects/ai-knowledge-base` — Tracebase 主项目。1 个 commit，main 分支，工作区干净。
- `~/projects/xiaochublog` — 博客站主题 + 文章源 + 发布工具链 + `practice/` 学习记录。3 个 commit，main 分支，工作区干净。

**Day 5（第一阶段验收关）已完成**，六项里五项收口：
- `apps/web/` 从空目录按 ES Modules 重建，四层依赖单向朝下：`src/api/`（超时/取消/错误归一成 ApiError 四种 kind）、`src/lib/`（纯函数，不碰 DOM 不碰网络）、`src/state/`（六态状态机 + 陈旧响应竞态防护）、`src/ui/`（吃 state 吐 DOM）、`src/main.js`（只接线）。
- `tests/web/documents-transform.test.mjs` 19 个测试补完「数据转换函数」验收项。
- 这些测试抓出并修掉两个真原型链 bug（见下面 Learned）。
- 复盘 `practice/day5-review.md`（在 xiaochublog 仓库）。
- Git 分支与 clean commit：两仓库共 4 个 commit。
- 验证：Tracebase `pnpm test` 27/27、`pnpm verify` 真无头 Chromium 八帧全过零 JS 错误；xiaochublog `pnpm test` 25/25。

## Next

1. **Day 5 唯一剩项：博客发布**。草稿已写完并提交：`~/projects/xiaochublog/docs/blog/2026-07-25-es-modules-layering-testing.md`，八节约 6300 字，构建产物 slug `es-modules-layering-unit-testing`。卡在通路，不是内容：
   - 上个会话调不到 wpvibe MCP 工具（`~/.claude/.mcp.json` 里配了但没挂载）。若本会话能调到，按 `blog-to-wordpress` skill 的分块写入流程发（每块 3-5KB + 移动锚点），能规避大小限制。
   - 备选是让用户自己跑 `node scripts/wordpress/publish-post.mjs es-modules-layering-unit-testing <user> "<app-password>"`。但该脚本一次性 POST 完整正文，本篇 13,286 字符，超过 skill 记录的 11KB 历史失败线，可能失败。
   - **封面图用户要自己挑选并上传**，别去 search_images 找图。`publish-post.mjs` 也不处理封面，那步得单独做。
   - 标签计划：复用 JavaScript(38)、前端入门(35)；新建 ES Modules / 单元测试 / 原型链，ASCII slug 已在 `scripts/wordpress/tag-slugs.mjs` 里备好。
   - 发布需显式批准。
2. 之后进 Day 6 TypeScript：把 `apps/web/src/` 迁到 TS 且禁用 `any`。`lib/documents.js` 的 Document typedef 是第一个要改成真 interface 的地方。
3. Recheck the `wpmu.php` null guard after any Colibri Page Builder update.

## Learned（Day 5 的两个 bug，都在 apps/web/src/lib/documents.js，已修）

`obj[key] ?? fallback` 查的是**整条原型链**。key 若是 `toString`/`constructor`/`valueOf`/`hasOwnProperty`，会拿到 `Object.prototype` 上继承的方法，那是个函数、是 truthy，`??` 兜不住：
- `statusLabel('toString')` 返回 `[Function: toString]` 而不是「状态未知」→ 改用 `Object.hasOwn`。
- `countByStatus` 里 `counts[status] ?? 0` 拿到函数后 `+1` 退化成字符串拼接，产出 `"function toString() { [native code] }1"` → 计数表改用 `Object.create(null)`。

规律：**任何拿外部输入当对象 key 查表的写法都有这个洞**，是原型污染的标准入口。写查表函数时固定问一句。同一个洞在 `scripts/wordpress/tag-slugs.mjs` 里也预防了。

副作用要知道：`Object.create(null)` 的对象不能直接和普通对象做 strict deep-equal（原型不同），测试里要 `{ ...obj }` 展开再比。

## Context

**范围决策（2026-07-25）**：35 天范围不变；之后接约 60 天 Phase 2，把 Tracebase 扩成飞书/Glean 式企业统一搜索。Day 17 必须把 `documents` 建成通用 `resources` 表（`source_type` / `source_id` / `external_id`（与 source_id 组唯一约束保证摄取幂等）/ `source_updated_at` / `acl_principals text[]` + GIN 索引 / `metadata JSONB`），即使当时只有 upload 一个来源。Day 24 检索带 `source_type` 过滤。这些约束也写在 `apps/api/README.md` 里。

学习者是 **vibe coding 模式**：不手写代码，考核逐行解释、代码审查、定规格、验证，而不是脱离 AI 背写。有 C++/Qt/多线程/网络/Python/LangChain/RAG 背景，讲前端可用其工程直觉类比；但**博客面向基础同学，要去掉 C++ 对照**。

权威大纲：`/mnt/e/AI_Fullstack_35_Day_Plan.md`，复盘用第 8 节模板。

**博客发布的两个坑**（详见 xiaochublog 的 README 和 skill）：大段中文正文超限；封面不由仓库管，`publish-post.mjs` 不消费 `coverPath`，特色图片在 WordPress 媒体库手动绑定。

发布需显式批准，不用 subagent，未经授权不 commit。WPVibe OAuth 已连接。主题在 `/www/wwwroot/xiaochublog.top/wp-content/themes/colibri-wp`，回滚副本 `/www/backup/xiaochublog-theme-before-manual-release-/colibri-wp` 不要删。

**注意**：`~/.claude/settings.json` 里 `ANTHROPIC_BASE_URL` 指向第三方中转端点 `https://www.lingzhan.top`，`ANTHROPIC_AUTH_TOKEN` 明文存储。会话内容都经由该第三方。已告知用户，处理生产密钥前值得重新评估。
