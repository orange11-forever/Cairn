# Tracebase

企业知识库 AI SaaS。文档上传后异步解析入库，用混合检索找到出处，再由 LLM 生成带引用溯源的回答。

> 状态：**Day 5 / 35**，第一阶段（Web 基础）已收口。当前只有前端原型和 mock 后端，真实 API 从 Day 16 开始。

## 现在能跑什么

一个文档列表页，对接 mock 后端，完整处理六种状态：空闲、加载中、成功、空数据、错误（网络/HTTP/超时）、用户取消。

```bash
pnpm install
pnpm mock     # mock 后端，端口 8787
pnpm web      # 静态服务，端口 5500 —— 另开一个终端
```

打开 http://localhost:5500 ，用页面上的下拉框切换后端场景。

## 验证

```bash
pnpm test     # 27 个测试：纯函数单测 + HTML/CSS 结构契约
pnpm verify   # 真无头 Chromium 跑八帧，断言零控制台错误并截图
```

`pnpm verify` 需要 Playwright 的系统依赖，首次在 WSL 上跑可能要先
`sudo npx playwright install-deps chromium`。

## 目录

```
apps/web/          前端。ES Modules 四层，依赖单向朝下
  src/api/         请求层：超时、取消、错误归一成 ApiError 四种 kind
  src/lib/         纯函数层：数据 → 数据，不碰 DOM 不碰网络
  src/state/       状态机 + 陈旧响应竞态防护
  src/ui/          渲染层：吃 state 吐 DOM
  src/main.js      接线，不含业务逻辑
apps/api/          FastAPI 后端占位，Day 16 起建（README 里有建表硬约束）
apps/worker/       摄取 Worker 占位，Day 23 起建
mocks/             mock 后端，Day 16 后废弃
scripts/           静态服务与浏览器验证
tests/web/         前端测试
```

分层的判据是依赖方向，不是文件数量。`lib/` 不 import 任何 DOM 或网络代码，所以它能在
Node 里裸测——`tests/web/documents-transform.test.mjs` 那 19 个测试不需要浏览器也不需要 mock。

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
