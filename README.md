# Tracebase

**工程组织的知识层与智能体平台。** 代码是一等公民，每个答案可追溯到出处，AI 智能体受治理。

> **状态：阶段 A（Web 客户端地基）进行中 — 前端原型。**
> 界面与交互链路可用，对接 mock 后端。真实 API 在阶段 B，RAG 链路在阶段 C。
> 下面「已实现 / 未实现」写清了当前边界；完整产品定义与阶段路线见
> [`docs/product-vision.md`](docs/product-vision.md)。

## 要解决的问题

工程组织的知识散落在文档、代码、PR 讨论、事故复盘和聊天记录里。最难回答的问题是：

> **"这段代码为什么是这样的？"**

答案通常分散在五个地方，串起来的唯一办法是去问那个待了五年的人。
通用聊天机器人能答，但答不出**依据**——而在企业场景里，没有出处的答案不能用来做决定。

核心约束一句话：**回答只依据已处理完成的资料，每个事实型回答必须附可点击的原文出处；
找不到依据时明确拒答，不编。**

这条约束不是功能列表里的一项，它决定了整个数据模型——引用（citation）的校验比答案文本
本身更严，因为一条指向不存在文档的引用比没有引用更坏：它让用户以为答案有依据。

同一条原则约束将来的代码架构图：**图必须从真实的 import 与调用关系推导，不能让 LLM 画**。
LLM 画的图会自信地错，而图比文字更容易让人相信。

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

- **没有真后端。** `mocks/docs-server.mjs` 提供四个端点，阶段 B 换成 FastAPI。
- **没有真鉴权。** 登录成功只在内存里留一个 user 对象，刷新即丢。token 怎么存、
  Web 用 HttpOnly Cookie 而原生客户端用 Bearer、401 怎么自动处理，都在阶段 B。
- **没有真文件上传。** 上传接口发的是 `{files:[{name,size}]}` 元数据，不是二进制。
  multipart 与断点续传要等阶段 B 有了存储层。
- **没有 RAG。** 回答是 mock 写死的，带一条固定引用。解析、切分、Embedding、
  向量检索在阶段 C。
- **没有代码感知、没有智能体治理、没有多端客户端。** 分别在阶段 E、F、G，
  见 [`docs/product-vision.md`](docs/product-vision.md)。

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

当前（阶段 A）：

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
apps/api/          FastAPI 后端占位，阶段 B 起建（README 里有建表与跨平台硬约束）
apps/worker/       摄取 Worker 占位，阶段 C 起建
mocks/             mock 后端（docs / login / ask / uploads），阶段 B 后废弃
scripts/           verify-web.mjs：真 Chromium 跑七组场景
tests/web/         node --test：纯函数与静态文本，不需要 DOM
tests/react/       vitest + RTL：组件行为
docs/              product-vision.md（产品定义与阶段路线）+ specs/（逐次的设计决策）
```

**分层的判据是依赖方向和输入假设，不是文件数量。** `schemas/` 的输入是 `unknown`
（来自网络，不可信），职责是"证明它是什么"；`lib/` 的输入是已校验的 `Document[]`，
职责是"拿它算点什么"。两层的输入假设相反，所以必须分开——混在一起的后果是每个函数
都得自己判一遍空，而判过之后类型信息又传不给下一个函数。

这个划分在 Day 8 得到过一次实测验证：换掉整个渲染层（手写 DOM → React），
`api/` `schemas/` `lib/` `state/` **一行未改**。

## 设计文档

[`docs/features.md`](docs/features.md) 是按「用户能做什么」组织的功能清单，
每项标注了所属阶段，末尾写明 MVP 是哪五条。

[`docs/product-vision.md`](docs/product-vision.md) 是产品定义与阶段路线的权威文档：
三根支柱（可追溯问答 / 代码感知 / 智能体治理）、成品的多端样貌、八个阶段的依赖关系，
以及一份**明确不做的清单**（IM、独立向量库、自研 LLM、LLM 直接画图）。

`docs/specs/` 下每份文档记的是**当时定下的决策和明确不做的事**，不是教程：

- `2026-07-27-day8-react-components-design.md` — 组件边界、`useSyncExternalStore` 桥接
- `2026-07-30-day9-hooks-forms-effects-design.md` — Hooks 边界、可读错误的五条标准、
  以及实测中发现并修掉的五个问题

`apps/api/README.md` 里有**建表前必须落地的五条硬约束**（组织级租户、审计日志、
软删除与彻底清除、ACL principal 格式）。筛选它们的判据是一句话：
**这个字段如果事后再加，需不需要回填历史数据或改写每一条查询？** 需要就现在建。

## 技术栈演进

| 阶段 | 内容 | 技术 |
|---|---|---|
| **A**（现在） | Web 客户端地基 | TypeScript、Zod、React、Vitest + RTL → Next.js、TanStack Query |
| B | 后端与数据地基 | FastAPI、PostgreSQL、SQLAlchemy、Alembic |
| C | RAG 垂直链路 | pgvector、Redis、Worker、混合检索、评估 |
| D | 部署与工程化 | Docker Compose、Nginx、HTTPS、GitHub Actions、可观测性 |
| E | 代码感知 ★ 差异化 | AST 解析、符号索引、调用图、推导式架构图 |
| F | 智能体治理 | 权限继承、运行审计、成本账本、注入防线 |
| G | 多端客户端 | PWA → VS Code 插件 → Tauri 桌面 → React Native |
| H | 企业统一搜索 | 多连接器、增量同步、跨源排序、实体图谱 |

依赖全部锁精确版本（无 `^` 范围）。

## License

ISC
