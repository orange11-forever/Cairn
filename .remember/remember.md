# Handoff

最后更新：2026-07-30（**Day 9 完成**：Hooks、表单与副作用）。

## 本次会话（2026-07-30）做了什么

**Day 9 全部完成**，三层验证 + 生产构建全绿。**尚未 commit**（等用户批准）。

设计文档：`docs/superpowers/specs/2026-07-30-day9-hooks-forms-effects-design.md`
（七个已定决策 + 实测发现的五个问题 + 明确不做的六项都在里面）。

## State

**两个仓库**：
- `~/projects/ai-knowledge-base` — Tracebase 主项目。Day 9 的改动全在工作区里，**未 commit**（本项目一直只做本地提交，不推远端）。
- `~/projects/xiaochublog` — 博客站主题 + 文章源 + 发布工具链 + `practice/` 学习记录。

**验证现状**：
- `pnpm typecheck` 0 错
- `pnpm test` = `test:unit`（node --test，**59 个**）+ `test:react`（vitest，**49 个**）
- `pnpm verify` 八帧断言一行未改 + 登录前置 + 四帧新增，全通过
- `pnpm build` 268.89 kB / gzip 82.99 kB

## Day 9 的代码地图

**新依赖**（全部 `-E` 精确锁版）：`vitest` 4.1.10、`jsdom` 30.0.1、
`@testing-library/react` 16.3.2、`/dom` 10.4.1、`/user-event` 14.6.1、`/jest-dom` 7.0.0。

**测试双运行器并存**，不迁移旧测试：
```
pnpm test       = test:unit && test:react
pnpm test:unit  = node --test "tests/web/**/*.test.mjs"   （不需要 DOM 的纯函数）
pnpm test:react = vitest run                              （tests/react/*.test.tsx，jsdom）
```
理由：Day 7/Day 8 各验证过一次「不要在引入新东西的同一步动既有的验证网」。

**新增文件**
- `lib/validation.ts` — 校验纯函数。返回**错误文案**而非 boolean/错误码（文案就是这层的产出物）。
  `FileLike = {name,size}` 结构类型，不依赖 `File`，所以能在两个运行器里都跑。
- `lib/messages.ts` — `MessageDto → Message` 视图模型。`createUserMessage` 用 `crypto.randomUUID()`。
- `hooks/useAsyncAction.ts` — 请求生命周期。抽它的**硬理由**是卸载时 abort（前三条只是啰嗦）。
- `hooks/useAutoScroll.ts` — 贴底自动滚动。**用 ref 回调不用 useEffect**，理由见下面「Learned」第 1 条。
- `api/auth.ts` / `api/conversations.ts` / `api/uploads.ts` — 三个端点，`signal` 是**必需参数**（漏传不会编译错误但取消会静默失效）。
- `components/FormField.tsx` — label + input + 错误，把四条 aria 要求集中在一处。
  导出 `fieldAria(id, error, hasHint)` 供调用方展开（不用 cloneElement——那是脆弱且无法类型检查的做法）。
- `components/LoginForm.tsx` / `SessionGate.tsx` / `Workspace.tsx`
- `vitest.config.ts` / `tests/react/setup.ts`

**登录做成门**（`SessionGate`），未登录看不到工作台。session 在内存里，刷新即丢。
Day 8 的布局组合搬到 `Workspace.tsx`，`App.tsx` 现在只有 `<SessionGate />`——
那条「App 里出现 useState 或 await 就说明状态提太高了」的约束仍然成立。

**mock 后端加了三个 POST 端点** + CORS 预检（OPTIONS）+ `readJsonBody`：
- `POST /api/login` 700ms 延迟，`demo@tracebase.dev` / `tracebase123`，错密码回 **401**
- `POST /api/ask` **1500ms** 延迟（留出点「停止生成」的窗口，仍小于客户端 3000ms 超时）
- `POST /api/uploads` 服务端**重复**校验大小/类型，415/413/201

`api/client.ts` 加了 `method` / `body`。两个细节：`Content-Type` 只在有 body 时才发
（给 GET 加会触发多余的 preflight），`body` 用 `undefined` 不用 `null`。

## useEffect 的用与不用（本日核心）

**只用在三处**：`useAsyncAction` 的卸载清理、`useAutoScroll` 的滚动、内容变化后滚到底。
共同点是「有一个需要对称释放的资源」或「无法用渲染表达的 DOM 命令」。

**刻意不用的地方**，每处都在代码注释里写了理由：
- 派生数据 → `useMemo`（`DocumentsPanel` 的筛选和角标计数）。
  错误形状 `useEffect(() => setVisible(filter(...)))` 的三个具体问题：渲染两遍且中间那帧显示过期数据、
  多一份可推导的真相、依赖漏一个就静默失效。
- 响应事件 → 写在事件处理函数里（提交后清空草稿）。
- 请求本身**不**在 Effect 里发——它由用户点击触发。

**`useMemo` 的注释明确写了"理由不是性能"**：4 条数据下省的时间是零，
包 memo 大概比不包还慢。包它是为了建立「派生值从 state 算出来，不存进 state」的形状。
性能优化的决定必须在测量之后，这里没测量。

**`countByStatus`（Day 6 写的）今天第一次有 UI 消费者。** 角标统计**全部**文档而非筛选后——
否则筛到 completed 之后其他角标全变 0，用户没法用角标判断该切到哪。

## 可读错误的五条标准（已落进代码和测试）

1. 说清怎么改：「邮箱缺少 @，例如 name@company.com」而不是「格式错误」
2. 挨着出错的字段，不堆在表单顶部
3. `aria-describedby` 关联 + `aria-invalid="true"`
4. `role="alert"` 让读屏立刻播报
5. **提交时才校验**，已提交过后改为实时清除——
   **错误的消失可以是即时的，出现不行**

**校验时机的例外：`UploadZone` 选完文件立刻校验。**
判据是「输入是否已经完整」：打字是渐进的（"z" 还不是邮箱），选文件是原子的
（点"打开"那一刻输入就完整了）。

**两类错误必须分开**（`LoginForm` 文件头有完整论证）：
字段错误显示在字段旁（前端自己知道），服务端错误显示在表单级
（密码不对不代表密码字段填错了，可能是邮箱记错）。
把 401 挂到密码字段上会让用户盯着密码反复改。这条有专门的测试守着。

## 测试关注行为的具体落点

- 用 `getByLabelText("邮箱")` 而不是 `querySelector("#login-email")`
- 用 `getByRole("alert")` 而不是找 `.field-error`（alert 才是"用户会知道"的真正含义）
- 用 `toBeDisabled()` 而不是 `hasAttribute("disabled")`
- 断言**完整文案**而不只是"返回了非 null"——只断言非 null 的话，
  把文案改成"错误"仍会通过，而那违反标准第 1 条
- `toHaveAccessibleDescription` 走的是读屏解析 `aria-describedby` 的完整过程，没法手写等价断言

判据：**把组件从头重写一遍、只保证外部行为一致，这些测试应当全绿。**

**桩打在 `fetch` 上，不 mock `api/auth.ts`**：桩打得越靠外，被测范围越大
（真实的 client.ts 超时/错误分类 + 真实的 schema 校验都进来了）。

## 目标已明确：企业级可用（2026-07-30）

用户明确 Tracebase 的终点是**真正可实际企业级使用**的项目，不是作品集 demo。

**35 天大纲节奏不变**（Day 28-32 已覆盖容器化/部署/CI/可观测性/OWASP，这段够硬）。
但企业级采购需要五项**必须在 Day 17 建表前确定**的地基，已全部写进
`apps/api/README.md` 的「Day 17 建表时的硬约束」一节：

1. 资源表建成通用 `resources` 形状（原有约束）
2. **租户模型 = 组织级**（用户当天选的）。每张业务表带 `org_id`，进复合索引第一列
3. `audit_logs` append-only，Day 17 就建——审计数据不会追溯生成，晚一天永久少一天
4. `deleted_at`（软删可恢复）+ `purged_at`（合规彻底清除）**两个**字段
5. `acl_principals` 带类型前缀（`user:123`/`group:eng`/`org:7`/`role:admin`），不是裸 id

筛选判据：**事后再加需不需要回填历史数据或改写每一条查询？** 需要就现在建。

**别在 Day 11-15 插入多租户改造**——会打乱前端阶段的教学重点，而这些约束只在建表时兑现。
Day 16 开工前重读那一节。

## 项目名：保持 Tracebase（2026-07-30 判断，别再重新论证）

用户问了"这个项目取什么名字好"。**结论：不改，保持 Tracebase。**

理由：
1. 它命名的是**差异点**（可追溯 / 引用）而不是品类。叫 AI/GPT/Smart/Knowledge 开头的
   名字市场上已挤满、说不出区别、且随技术潮流过期。
2. 企业买家吃"可追溯"这个词——安全评审关心的正是"答案凭什么可信"。
3. 改名要动 75 个文件 + README + 记忆 + 已发的两篇博客，产品不会因此变好。
4. 它会出现在简历和 Day 33-35 的作品集里，念得出、拼得对、记得住。

**已知的一个风险**（用户自己判断过可接受）：Trace 在开发者圈里强烈指向分布式追踪
（OpenTelemetry / Jaeger），工程师可能误以为是可观测性工具。但目标买家是企业 IT /
知识工作者，那个受众读作"可追溯"，没问题。`-base` 后缀略有跟风感（Supabase/Metabase），
但也让人一眼知道是数据类产品。

**未核实**：商标和域名占用没查（搜索工具当时没返回内容）。要真做产品得自己查一遍。

**如果哪天真要改，最佳时机是 Day 33 做作品集那天**——那时产品成型、对它是什么最清楚，
而且那天本来要重写 README 和讲稿，顺手改成本最低。现在改是在信息最少时做一个不着急的决定。

## 用户在自学（2026-07-30 起）

用户决定在推进 Day 10 之前先自学 React 和数据库。清单在 `docs/study-plan.md`。

**给的建议是数据库优先（7:3）**，理由是补救成本不同：React 后面 Day 10-15 有六天连续在用、
天天被测试纠错；而**数据库只有 Day 17 一天**，且那天的 schema 决定改起来最贵。

React 部分的重点直接来自 Day 9 问答的失分位置：state 的机制与代价（第 1、4 题）、
渲染时机与何时不该用 Effect（第 3、6 题）。推荐 react.dev 官方文档，
**明确提醒别搜中文博客**（大量 class 组件时代的过时模式）。

用户回来续上时：可以先问他学到哪、拿 `docs/study-plan.md` 最后一节那三个验证题对一下
（对着 useAsyncAction / DocumentsPanel / useAutoScroll 的真实代码解释设计理由）。

## Next

1. **Day 10：服务端状态与 React 阶段验收**（大纲第 10 天）。
   学服务端状态 vs 本地状态、缓存、失效、重试；接 TanStack Query。
   项目：文档查询、上传 mutation、删除、自动刷新。
   验收：可交互 React 原型 + 核心组件测试通过 + **能现场解释一次状态更新为何触发重渲染**。
   - `useAsyncAction` 刻意做得薄，好让 Day 10 换掉它时能看清手写服务端状态缺了什么
     （缓存、失效、重试、去重）。别在 Day 10 之前给它加功能。
2. **Day 9 复盘未写**：`~/projects/xiaochublog/practice/day9-review.md`（用大纲第 8 节模板）。
   `day7-review.md` / `day8-review.md` 也仍未建（`day6-review.md` 已 commit b0aec34）。
3. **两件仍未亲自核验的事**（从 2026-07-29 挂过来，WPVibe 额度当时用尽，现已恢复）：
   - 确认 `wpcode_snippets` 选项里那三段扫光代码真的清掉了。
     `wp option pluck wpcode_snippets site_wide_header 0 code` 读回来比对。
     白光消失只是间接证据；万一那份缓存被回滚，白光会复发，办法是让用户去后台重新保存一次片段。
   - 可访问性扣的 5 分是一处 `color-contrast`。`audit_page` 不返回具体元素，
     要定位得用 PageSpeed Insights 网页版看那一项的元素列表，或读主题 CSS 逐个算对比度。
4. **Qt 飞书文档等用户自己导入**：文件已 commit（xiaochublog 2b61211），
   Windows 侧路径 `\\wsl$\Ubuntu\home\chr\projects\xiaochublog\docs\feishu\qt-cpp-getting-started.md`。
   **别再说"已经建好飞书文档"**——我没有飞书接入能力。
5. Day 7 的 5 道问答验收——**用户 2026-07-27 明确说忽略**，不用再提。
6. `mock` 加 dirty 场景 + UI 消费 `dropped` 计数（可选、非阻塞，从 Day 7 挂到现在）。
7. Recheck the `wpmu.php` null guard after any Colibri Page Builder update.

## 未决 / 设计问题

- **错误文案的路径不一致（Day 9 新发现）**：`AssistantPanel` 显示 `error.message`（后端原话），
  文档列表走 `describeStatus` 做统一映射（"服务器出错（500），请稍后重试"）。
  同一应用两条路径。写测试断言 500 那条时才发现。
  **Day 12 建统一请求层时收口**——那时该有"错误文案在哪一层决定"的答案。
- **`describeStatus` 的误导文案**：`documents` 为空且 `dropped > 0` 时命中 empty 早返回，
  显示「还没有文档，上传第一个吧」——可用户明明上传过，真相是前端一条都没看懂。
  当前行为已固定进 `status-text.test.mjs` 并注明理由。**Day 12 接正式请求层时重新考虑。**
- **`Sidebar` 组件名与现实不符**：它渲染的是横向顶栏 `.product-header`。
  Day 11 迁 Next.js 重排布局时一起改。
- **上传发的是元数据不是文件**：`{files:[{name,size}]}`。真 multipart 是 Day 19 的题目。
  客户端校验/错误显示/提交中禁用那些逻辑到时候一行不用改（它们和 body 怎么编码无关）。

## Learned（Day 9）

**1. 条件渲染的元素上，`useEffect(..., [])` 挂不上监听器——要用 ref 回调。**

`useAutoScroll` 原来在 `useEffect(..., [])` 里 `addEventListener`。
但滚动容器是条件渲染的（消息为空时 `MessageList` 渲染 `<p>` 而不是 `.message-scroll`），
首次挂载时 `containerRef.current` 是 null，Effect 直接 return，而依赖 `[]` 让它**再也不会重跑**。
监听器从此不存在，`stickToBottom` 永远停在初始 `true`，"是否贴底"的判断彻底失效，
退化成无条件滚动。

症状极隐蔽：**自动滚动看起来是好的**（无条件滚也会滚到底），坏掉的只有
"用户读历史时不打扰他"这一半。手工测试几乎发现不了。

改成 ref 回调（React 19 支持从 ref 回调返回清理函数）：它由 React 在节点真正
挂载/卸载时调用，条件渲染的元素出现时一定被调到。

**2. 新写的断言要先证明它会失败。**

自动滚动帧写完就是绿的，但那不说明什么——它可能因为无关原因通过。
把 hook 换回旧实现跑一遍，确认它报 `✗ 实际 scrollTop=375`，再换回来确认转绿。
这一步花了两分钟，买到的是"这条断言是真裁判"这个结论。
没做这一步的话，那 30 行代码只是一段装饰。
（和 Day 7/Day 8 的「裁判不能参与被验收的改动」是同一条的另一面。）

**3. 测试工具的默认行为可能让整段代码在测试里等于不存在。**

`userEvent.upload` 默认按 `accept` 属性**静默丢掉**不匹配的文件，
于是 `virus.exe` 根本进不了组件，`validateFiles` 里的类型校验分支永远不被走到。
失败信息是"找不到 alert"，看起来像组件忘了渲染错误——指不到真正的原因。

关掉 `applyAccept` 不是放宽测试，恰恰相反：**accept 是便利不是校验**，
真实用户能在系统选择器里切到"所有文件"绕过它。默认的 user 实例永远走不到那条路径。

**4. 源码排版会渗进无障碍输出。**

JSX 里折行会在两个文本节点之间留一个空格，`aria-describedby` 拼出来的描述里
它真实存在（读屏播报「10.0 MB， 一次最多」），而肉眼看页面看不出来（HTML 折叠空白）。
写 `toHaveAccessibleDescription` 断言时才发现。

**5. 写测试的过程会暴露产品问题，不只是代码问题。**

「按角色找 list」拿到两个匹配而失败 → 发现"对话记录"和"引用来源"两个列表
都没有 `aria-label`，读屏用户听到的是"列表，2 项"，不知道是哪个。
那个测试失败指向的是真实的可访问性缺陷，不是测试写法问题。
断言 500 错误文案时发现两条错误路径的文案策略不一致（见上面「未决」）。

**6. 库的入口选择会影响类型而不影响运行时。**

`expect.extend(matchers)` 和 `import "@testing-library/jest-dom/vitest"`
运行时行为一样，但前者不扩展 vitest 的 `Assertion` 接口——
测试跑得过，`tsc` 对每个 `toBeDisabled` 都报错。

## Context

**范围决策（2026-07-25）**：35 天范围不变；之后接约 60 天 Phase 2，把 Tracebase 扩成飞书/Glean 式企业统一搜索。Day 17 必须把 `documents` 建成通用 `resources` 表（`source_type` / `source_id` / `external_id`（与 source_id 组唯一约束保证摄取幂等）/ `source_updated_at` / `acl_principals text[]` + GIN 索引 / `metadata JSONB`），即使当时只有 upload 一个来源。Day 24 检索带 `source_type` 过滤。这些约束也写在 `apps/api/README.md` 里。`schemas/primitives.ts` 的 `ResourceIdSchema` 已在铺路，Day 17 收紧成 uuid 只改一处。

**用户要求加快最终项目进度**。教学节奏压缩：语法演示批量跑结论，重心放真迁移和实测。但阶段验收关不跳。

**每个学习日的四件事（2026-07-30 用户重申，缺一件不算完成，别等用户要求）**：
1. 开工前说清楚今天解决什么问题、为什么需要这些概念——不是直接开始写代码
2. 每个知识块讲完就出 2-3 道问答题，不攒到最后
3. 收尾主动给知识点梳理
4. 代码注释只是补充，不能代替讲解

Day 9 的反面教材：代码写完、验证跑绿、commit 完就收工，问答等用户问才给。
根因是把「代码通过验证」当成完成标准，而真正的标准是**用户学到了**。

**出题纪律**：只考已经讲过的东西，不能大跳步、不能在题目里引入还没解释的概念。
超前出题会让检验变成负担。

**别忘用户的起点**：整个 Web 栈零基础（HTML/CSS/JS/TS/React/Next.js），
后端的 FastAPI/SQLAlchemy/Alembic 也是新的。
可用 C++/Qt/多线程/网络/Python/LangChain/RAG 背景类比，但**别假设能直接迁移**——
懂多线程 ≠ 懂事件循环（抢占式 vs 协作式，直觉相反）。类比用来搭桥，不能省掉解释。

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
- **Day 8 两篇博客均已上线**：post 1024 `react-basics-declarative-rendering`、post 1043 `safely-replacing-a-layer`。
- **站点是私人博客**，`blog_public=0` 有意为之。**SEO 分数（66）永远别报**——唯一扣分项就是 noindex，正是想要的效果。
- 站点标题是 `Aliya-devlog`。`blogname` 驱动三处：浏览器标签、左上角品牌名、**首页 hero 大标题**。

**站点主题（2026-07-27 改动）**：按用户要求删掉了顶部导航的 C++ 项，现在是首页/文章/专题/关于/搜索五项。那一项是 `header.php` 里 `get_category_by_slug('cpp')` 动态生成的（连 `if/endif` 四行），搜 `category/cpp` 搜不到。改主题走 `create_draft_theme` → 改 → 预览 → `publish_draft_theme`，备份在 `colibri-wp-wpvibe-backup`。首页专题区是分类驱动的，删导航不影响它。

**WPCode Lite 存两份代码**（2026-07-29 踩的坑，已进 memory）：`post_content`（编辑器显示的）和 `wpcode_snippets` 选项（**前台实际输出的**）。改前者前台不生效，要进 wp-admin 让它重建选项缓存。

**注意**：`~/.claude/settings.json` 里 `ANTHROPIC_BASE_URL` 指向第三方中转端点，`ANTHROPIC_AUTH_TOKEN` 明文存储。会话内容都经由该第三方。已告知用户，处理生产密钥前值得重新评估。
