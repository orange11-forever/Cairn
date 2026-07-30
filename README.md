# Tracebase

企业知识库 AI SaaS。文档上传后异步解析入库，用混合检索找到出处，再由 LLM 生成带引用溯源的回答。

> 状态：**Day 9 / 35**，React + Hooks + 受控表单。当前只有前端原型和 mock 后端，真实 API 从 Day 16 开始。

## 现在能跑什么

登录进工作台，三条链路都走真请求（对接 mock 后端）：

- **登录** —— 字段校验与服务端 401 分开显示；错误关联到字段、读屏可播报、焦点自动落到第一个出错的字段
- **文档列表** —— 完整处理六种状态（空闲/加载中/成功/空数据/错误/用户取消），带状态筛选与角标计数
- **上传** —— 类型、大小、数量、空文件逐项校验，每个文件的错误显示在它自己那一行；服务端再校验一遍
- **问答** —— 提问乐观更新、等待占位、贴底自动滚动、停止生成（请求真的终止）、失败回滚并可重试

```bash
pnpm install
pnpm mock     # mock 后端，端口 8787
pnpm dev      # Vite dev server，端口 5500 —— 另开一个终端
```

打开 http://localhost:5500 ，用页面上的下拉框切换后端场景。Day 7 起源码含 `.ts`，浏览器
不认类型语法，必须经 Vite 转换才能加载（`pnpm dev` 即时转，`pnpm build` 预编译进 `dist/`）。

## 验证

```bash
pnpm test       # 108 个测试 = test:unit + test:react
pnpm test:unit  #   59 个：纯函数、Zod 校验层回归、表单校验、HTML/CSS 结构契约（node --test）
pnpm test:react #   49 个：组件行为，按 label/role 查询而非 class（vitest + RTL）
pnpm typecheck  # tsc --noEmit，零错误
pnpm verify     # 起 Vite + 真无头 Chromium 跑十二帧，断言零控制台错误并截图
```

两个测试运行器并存，不是历史包袱：`tests/web/` 那批不需要 DOM，跑得又快又稳，
把它们迁进 Vitest 的收益只是"统一工具"，成本是碰一批本来是绿的测试。

`typecheck` 故意不并进 `test`：类型错误和行为错误是两类问题，混在一条命令里，一个类型
报错会让你看不见行为测试的结果。

`verify` 是最硬的那道：它在真浏览器里跑，能证明 jsdom 证明不了的东西——真实的焦点管理、
布局驱动的自动滚动、以及"点了取消请求是否真的终止"。

`pnpm verify` 需要 Playwright 的系统依赖，首次在 WSL 上跑可能要先
`sudo npx playwright install-deps chromium`。

## 目录

```
apps/web/          前端。依赖单向朝下（Day 7 起全 .ts，Day 8 起 React）
  src/schemas/     校验层：Zod schema + DTO/领域模型，把 unknown 收成已知形状
  src/api/         请求层：超时、取消、错误归一成 ApiError 五种 kind（含 contract）
  src/lib/         纯函数层：数据 → 数据，不碰 DOM 不碰网络也不碰校验
  src/state/       状态机 + 陈旧响应竞态防护；useSyncExternalStore 桥接 React
  src/hooks/       自定义 Hook：请求生命周期（含卸载取消）、贴底自动滚动
  src/components/  React 组件，纯展示或持有自己那一份本地 state
  src/App.tsx      只把渲染交给 SessionGate——出现 useState 或 await 就说明状态提太高了
  src/main.tsx     挂载入口，不含业务逻辑
tsconfig.json      strict + noUncheckedIndexedAccess + allowImportingTsExtensions
vite.config.js     Day 7 引入的构建步骤（源码含 .ts 和 JSX，浏览器要经它转换）
vitest.config.ts   Day 9 引入，组件测试用 jsdom 环境
apps/api/          FastAPI 后端占位，Day 16 起建（README 里有建表硬约束）
apps/worker/       摄取 Worker 占位，Day 23 起建
mocks/             mock 后端（docs / login / ask / uploads），Day 16 后废弃
scripts/           verify-web.mjs：真 Chromium 跑十二帧
tests/web/         node --test：纯函数与静态文本，不需要 DOM
tests/react/       vitest + RTL：组件行为
docs/              设计文档（specs/）与自学清单
```

分层的判据是依赖方向，不是文件数量。`schemas/` 输入是 unknown（不可信），`lib/` 输入是
已校验的 `Document[]`；两层输入假设相反，所以分开。`lib/` 不 import 任何 DOM 或网络代码，
所以能在 Node 里裸测——`tests/web/` 那批测试不需要浏览器也不需要 mock。

## 技术栈演进

| 阶段 | 变化 |
|---|---|
| Day 1-5 | 原生 HTML/CSS/JS，ES Modules |
| Day 6-10（现在） | TypeScript（禁用 `any`）、Zod、React、Vitest + RTL |
| Day 11-15 | Next.js、Tailwind、TanStack Query、Zod |
| Day 16-20 | FastAPI、PostgreSQL、SQLAlchemy、Alembic |
| Day 21-27 | pgvector、Redis、Worker、混合检索、RAG 评估 |
| Day 28-35 | Docker Compose、Nginx、HTTPS、GitHub Actions、可观测性 |

目标形态：`Browser → Next.js → FastAPI → PostgreSQL+pgvector / Redis → Worker / 对象存储 / LLM API`

这个仓库只含 Tracebase 本体。学习笔记与博客相关的东西在另一个仓库。
