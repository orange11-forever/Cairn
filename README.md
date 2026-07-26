# Tracebase

企业知识库 AI SaaS。文档上传后异步解析入库，用混合检索找到出处，再由 LLM 生成带引用溯源的回答。

> 状态：**Day 7 / 35**，全模块迁 TypeScript + Zod 运行时校验层。当前只有前端原型和 mock 后端，真实 API 从 Day 16 开始。

## 现在能跑什么

一个文档列表页，对接 mock 后端，完整处理六种状态：空闲、加载中、成功、空数据、错误（网络/HTTP/超时）、用户取消。

```bash
pnpm install
pnpm mock     # mock 后端，端口 8787
pnpm dev      # Vite dev server，端口 5500 —— 另开一个终端
```

打开 http://localhost:5500 ，用页面上的下拉框切换后端场景。Day 7 起源码含 `.ts`，浏览器
不认类型语法，必须经 Vite 转换才能加载（`pnpm dev` 即时转，`pnpm build` 预编译进 `dist/`）。

## 验证

```bash
pnpm test       # 28 个测试：纯函数单测 + Zod 校验层回归 + HTML/CSS 结构契约
pnpm typecheck  # tsc --noEmit，零错误
pnpm verify     # 起 Vite + 真无头 Chromium 跑八帧，断言零控制台错误并截图
```

`typecheck` 故意不并进 `test`：类型错误和行为错误是两类问题，混在一条命令里，一个类型
报错会让你看不见 28 个行为测试的结果。

`pnpm verify` 需要 Playwright 的系统依赖，首次在 WSL 上跑可能要先
`sudo npx playwright install-deps chromium`。

## 目录

```
apps/web/          前端。ES Modules 五层，依赖单向朝下（Day 7 起全 .ts）
  src/schemas/     校验层：Zod schema + DTO/领域模型，把 unknown 收成已知形状
  src/api/         请求层：超时、取消、错误归一成 ApiError 五种 kind（含 contract）
  src/lib/         纯函数层：数据 → 数据，不碰 DOM 不碰网络也不碰校验
  src/state/       状态机 + 陈旧响应竞态防护
  src/ui/          渲染层：吃 state 吐 DOM
  src/main.ts      接线，不含业务逻辑
practice/day6/     TypeScript 语法演示，九个可跑可改的文件
tsconfig.json      strict + noUncheckedIndexedAccess + allowImportingTsExtensions
vite.config.js     Day 7 引入的构建步骤（源码含 .ts，浏览器要经它转换）
apps/api/          FastAPI 后端占位，Day 16 起建（README 里有建表硬约束）
apps/worker/       摄取 Worker 占位，Day 23 起建
mocks/             mock 后端，Day 16 后废弃
scripts/           Vite + 浏览器验证
tests/web/         前端测试
```

分层的判据是依赖方向，不是文件数量。`schemas/` 输入是 unknown（不可信），`lib/` 输入是
已校验的 `Document[]`；两层输入假设相反，所以分开。`lib/` 不 import 任何 DOM 或网络代码，
所以能在 Node 里裸测——`tests/web/` 那批测试不需要浏览器也不需要 mock。

## 技术栈演进

| 阶段 | 变化 |
|---|---|
| Day 1-5（现在） | 原生 HTML/CSS/JS，ES Modules |
| Day 6-10 | TypeScript（禁用 `any`）、React |
| Day 11-15 | Next.js、Tailwind、TanStack Query、Zod |
| Day 16-20 | FastAPI、PostgreSQL、SQLAlchemy、Alembic |
| Day 21-27 | pgvector、Redis、Worker、混合检索、RAG 评估 |
| Day 28-35 | Docker Compose、Nginx、HTTPS、GitHub Actions、可观测性 |

目标形态：`Browser → Next.js → FastAPI → PostgreSQL+pgvector / Redis → Worker / 对象存储 / LLM API`

博客站（xiaochublog.top）的主题与发布工具链已拆到独立仓库 `../xiaochublog`。
