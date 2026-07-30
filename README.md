# Tracebase

企业知识库 AI 问答。文档上传后异步解析入库，用混合检索找到出处，再由 LLM 生成**带引用溯源**的回答。

> **状态：Day 9 / 35 — 前端原型。** 界面与交互链路可用，对接 mock 后端；
> 真实 API 从 Day 16 起建，RAG 链路从 Day 21 起建。下面「已实现 / 未实现」写清了边界。

## 要解决的问题

企业内部资料散落在几百份文档里，人找不到、也记不住哪份是最新的。通用聊天机器人能答，
但答不出**依据**——而在企业场景里，一个没有出处的答案不能用来做决定。

Tracebase 的核心约束是一句话：**回答只依据已处理完成的知识文档，且每个事实型回答都必须
附可点击的原文出处；找不到依据时明确拒答，不编。**

这条约束不是功能列表里的一项，它决定了整个数据模型——引用（citation）的校验比答案文本
本身更严，因为一条指向不存在文档的引用比没有引用更坏：它让用户以为答案有依据。

## 跑起来

需要 Node 22+（`node --test` 直接跑 `.ts` 靠它原生的类型剥离）和 pnpm 10+。

```bash
pnpm install
pnpm mock     # mock 后端，端口 8787
pnpm dev      # Vite dev server，端口 5500 —— 另开一个终端
```

打开 http://localhost:5500 ，会先看到登录页。**演示账号写在页面上**
（`demo@tracebase.dev` / `tracebase123`），故意输错密码可以看 401 的处理。

进入工作台后，用「模拟场景」下拉框切换后端行为——成功 / 空数据 / HTTP 500 / 慢响应（触发超时）。

## 已实现

四条链路都走**真请求**，没有伪造的 loading：

| 链路 | 覆盖到什么 |
|---|---|
| **登录** | 字段校验与服务端 401 分开显示；错误关联到字段（`aria-describedby`）、读屏可播报（`role="alert"`）、焦点自动落到第一个出错的字段 |
| **文档列表** | 六种状态：空闲 / 加载中 / 成功 / 空数据 / 错误（网络·HTTP·超时·契约）/ 用户取消。带状态筛选与角标计数 |
| **上传** | 类型、大小、数量、空文件逐项校验，每个文件的错误显示在它自己那一行；服务端再独立校验一遍（415 / 413） |
| **问答** | 提问乐观更新、等待占位、贴底自动滚动（用户翻看历史时不打扰）、停止生成（请求真的终止）、失败回滚并可重试 |

两个贯穿全局的取舍值得单独说：

**错误分两类，显示位置不同。** 字段错误（邮箱缺少 @）前端自己就知道，显示在那个字段旁边；
服务端错误（邮箱或密码不正确）只有问过后端才知道，显示在表单级。把 401 挂到密码字段上
是常见做法也是错的——真正错的可能是邮箱，而用户会因此反复改密码。有测试专门守这条。

**校验时机取决于输入是否已完整。** 打字是渐进的，所以提交前不校验（否则是在指责用户
还没打完的字）；选文件是原子的，点「打开」那一刻输入就完整了，所以立刻校验。
统一成一种时机会在其中一个场景上做错。

## 未实现（当前边界）

- **没有真后端。** `mocks/docs-server.mjs` 提供四个端点，Day 16 起换成 FastAPI。
- **没有真鉴权。** 登录成功只在内存里留一个 user 对象，刷新即丢。token 怎么存、
  为什么用 HttpOnly Cookie、401 怎么自动处理，是 Day 13 和 Day 18 的题目。
- **没有真文件上传。** 上传接口发的是 `{files:[{name,size}]}` 元数据，不是二进制。
  multipart 编码要等 Day 19 有了存储层。
- **没有 RAG。** 回答是 mock 写死的，带一条固定引用。解析、切分、Embedding、
  向量检索从 Day 21 起建。

## 验证

```bash
pnpm test       # 108 个测试 = test:unit + test:react
pnpm test:unit  #   59 个：纯函数、Zod 校验层回归、表单校验、HTML/CSS 结构契约（node --test）
pnpm test:react #   49 个：组件行为，按 label/role 查询而非 class（vitest + RTL）
pnpm typecheck  # tsc --noEmit，零错误
pnpm verify     # 起 Vite + 真无头 Chromium 跑七组场景，断言零控制台错误并截 16 张图
pnpm build      # 生产构建
```

`pnpm verify` 需要 Playwright 的系统依赖，首次在 WSL 上跑可能要先
`sudo npx playwright install-deps chromium`。

### 三层各自能证明什么

这个项目在验证上花的行数和源码相当，而**分层的意义在于每层能证明的东西不同**：

| 层 | 能证明 | 证明不了 |
|---|---|---|
| `pnpm typecheck` | 类型契约一致 | 运行时行为（类型对了语义仍可能错） |
| `tests/web/`（node） | 纯函数的边界值、CSS 契约 | 组件渲染、用户交互 |
| `tests/react/`（jsdom） | 组件行为、无障碍属性 | **任何依赖布局的东西**——jsdom 没有布局引擎，`scrollHeight` 全返回 0 |
| `pnpm verify`（真 Chromium） | 真实焦点管理、布局驱动的滚动、取消是否真的终止 | — |

自动滚动只能在最后一层验证，这是刻意记录在 `tests/react/MessageList.test.tsx` 文件头的：
在 jsdom 里写 `expect(scrollTop).toBe(scrollHeight)` 会通过（`0 === 0`），
但它什么都没证明——**一条假绿的断言比没有测试更坏**，因为它让人以为这件事被验证过了。

### 两条从实战里来的规矩

**`typecheck` 故意不并进 `test`。** 类型错误和行为错误是两类问题，混在一条命令里，
一个类型报错会让你看不见行为测试的结果。

**验收的裁判必须没参与被验收的改动。** Day 8 换掉整个渲染层时，组件照原样输出既有的
`id` 和 `data-*`，不是因为那套选择器更好，而是不改它，浏览器验证脚本才仍然是独立裁判——
同时换选择器和改断言，全绿只证明「新代码和新断言自洽」。

同理，新写的断言要先证明它**会失败**：Day 9 加的自动滚动帧写完就是绿的，但那不说明任何事，
把被测的 Hook 换回旧实现跑一遍、确认它真的报错，才知道那条断言是真裁判而不是装饰。

## 架构

当前（Day 9）：

```
Browser → Vite dev server → React 组件树
                              ↓
                        api/ 请求层（超时·取消·错误归一）
                              ↓
                        schemas/ Zod 校验边界
                              ↓
                        mock 后端（Node http，4 个端点）
```

目标形态：

```
Browser → Next.js → FastAPI → PostgreSQL + pgvector
                        ↓            ↑
                      Redis → Worker（解析·切分·Embedding）
                        ↓
                   对象存储 / LLM API
```

**只有一个数据库。** 向量用 pgvector 存在 Postgres 里，不引入独立向量库——
这样权限过滤和相似度排序能在同一条 SQL 里完成，过滤下沉到数据库层，
不可能"忘记"加它。用独立向量库则要先取 Top-k 再回来过滤，既有召回不足的问题，
权限逻辑也散在应用代码里，漏一处就是跨租户泄漏。

## 目录

```
apps/web/          前端。五层分工，依赖单向朝下
  src/schemas/     校验层：Zod schema + DTO/领域模型，把 unknown 收成已知形状
  src/api/         请求层：超时、取消、错误归一成 ApiError 五种 kind（含 contract）
  src/lib/         纯函数层：数据 → 数据，不碰 DOM 不碰网络也不碰校验
  src/state/       状态机 + 陈旧响应竞态防护；useSyncExternalStore 桥接 React
  src/hooks/       自定义 Hook：请求生命周期（含卸载取消）、贴底自动滚动
  src/components/  React 组件，纯展示或持有自己那一份本地 state
  src/App.tsx      只把渲染交给 SessionGate——出现 useState 或 await 就说明状态提太高了
  src/main.tsx     挂载入口，不含业务逻辑
apps/api/          FastAPI 后端占位，Day 16 起建（README 里有建表硬约束）
apps/worker/       摄取 Worker 占位，Day 23 起建
mocks/             mock 后端（docs / login / ask / uploads），Day 16 后废弃
scripts/           verify-web.mjs：真 Chromium 跑七组场景
tests/web/         node --test：纯函数与静态文本，不需要 DOM
tests/react/       vitest + RTL：组件行为
docs/specs/        设计文档：已定决策与明确不做的事
```

**分层的判据是依赖方向和输入假设，不是文件数量。** `schemas/` 的输入是 `unknown`
（来自网络，不可信），职责是"证明它是什么"；`lib/` 的输入是已校验的 `Document[]`，
职责是"拿它算点什么"。两层的输入假设相反，所以必须分开——混在一起的后果是每个函数
都得自己判一遍空，而判过之后类型信息又传不给下一个函数。

这个划分在 Day 8 得到过一次实测验证：换掉整个渲染层（手写 DOM → React），
`api/` `schemas/` `lib/` `state/` **一行未改**。

## 设计文档

`docs/specs/` 下每份文档记的是**当时定下的决策和明确不做的事**，不是教程：

- `2026-07-27-day8-react-components-design.md` — 组件边界、`useSyncExternalStore` 桥接
- `2026-07-30-day9-hooks-forms-effects-design.md` — Hooks 边界、可读错误的五条标准、
  以及实测中发现并修掉的五个问题

`apps/api/README.md` 里有**建表前必须落地的五条硬约束**（组织级租户、审计日志、
软删除与彻底清除、ACL principal 格式）。筛选它们的判据是一句话：
**这个字段如果事后再加，需不需要回填历史数据或改写每一条查询？** 需要就现在建。

## 技术栈演进

| 阶段 | 变化 |
|---|---|
| Day 1-5 | 原生 HTML/CSS/JS，ES Modules |
| Day 6-10（现在） | TypeScript（禁用 `any`）、Zod、React、Vitest + RTL |
| Day 11-15 | Next.js、Tailwind、TanStack Query |
| Day 16-20 | FastAPI、PostgreSQL、SQLAlchemy、Alembic |
| Day 21-27 | pgvector、Redis、Worker、混合检索、RAG 评估 |
| Day 28-35 | Docker Compose、Nginx、HTTPS、GitHub Actions、可观测性 |

依赖全部锁精确版本（无 `^` 范围）。

## License

ISC
