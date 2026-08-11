# 持续集成设计

## 目标

Cairn 使用 GitHub Actions 对所有指向 `main` 的 Pull Request 和每次推送到
`main` 执行与本地相同的完整门禁：`pnpm verify`。

CI 只验证代码，不发布制品、不部署环境，也不需要仓库 Secret。

## 触发与并发

工作流由以下事件触发：

- `pull_request`，目标分支为 `main`；
- `push`，分支为 `main`。

同一个 Pull Request 的新提交取消尚未完成的旧运行。每次 `main` 推送使用唯一并发组，
因此主分支运行不会互相取消。

并发组使用工作流名与 Pull Request 编号；非 Pull Request 事件回退到唯一的 run ID。
`cancel-in-progress` 只在 `pull_request` 事件上启用。

## 执行环境与权限

工作流使用固定的 `ubuntu-24.04` GitHub-hosted runner，并设置 30 分钟任务硬超时。
`GITHUB_TOKEN` 只授予 `contents: read`，checkout 不持久化凭据。

工具链与仓库声明保持一致：

- Node.js 22；
- pnpm 10.34.5，由根 `package.json` 的 `packageManager` 字段约束；
- Python 3.12；
- uv 与仓库根 `uv.lock`；
- Docker Compose、OpenSSL 和 Playwright Chromium。

第三方及 GitHub 官方 Action 固定到审核过的完整提交 SHA，并在行尾标注对应版本，避免可变标签在
不修改仓库的情况下改变 CI 行为。版本升级应作为独立依赖维护提交处理。

## 单一验证任务

工作流只包含一个 `verify` job，步骤顺序如下：

1. checkout 当前提交；
2. 安装 pnpm、Node.js 22、Python 3.12 和 uv，并启用 pnpm/uv 下载缓存；
3. 运行 `pnpm install --frozen-lockfile`；
4. 运行 `uv sync --all-packages --all-groups --frozen`；
5. 运行 `pnpm --filter cairn-web exec playwright install --with-deps chromium`；
6. 运行 `pnpm verify`。

缓存只保存包管理器下载内容，不缓存 `node_modules`、`.venv`、构建产物、数据库卷或浏览器结果。
锁文件变化自然使相应缓存失效。

`pnpm verify` 继续作为唯一质量门禁，负责共享契约、SDK 漂移、Web、API、Ruff、Pyright、发行包、
PostgreSQL 16 集成、生产构建、Chromium 和认证代理验证。CI 不复制或重写这些阶段。

## 失败与清理

任何安装或验证步骤非零退出都会使 job 失败。工作流不使用 `continue-on-error`，也不自动重试测试。

`verify:core` 负责正常失败路径下的 Compose 项目、容器、网络和卷清理。任务取消或 runner 异常退出时，
GitHub-hosted 临时 runner 被整体销毁，因此不会污染后续运行。

## 验收

实现必须满足以下条件：

- 仓库契约测试能验证触发分支、只读权限、PR 专用取消策略、硬超时和唯一 `pnpm verify` 门禁；
- workflow YAML 可被解析；
- 本地 `pnpm verify` 在新增 workflow 后仍完整通过；
- 推送后 GitHub Actions 能在 `main` 上完成一次绿色运行；
- `main` 使用 `CI / Full verification` 作为 required status check。

## 主分支治理

本个人项目采用零审批 Pull Request：功能分支完成本地验证后推送，创建面向 `main` 的 PR，不要求 approving review，但必须等待 `CI / Full verification` 成功。通过后使用 squash merge，并删除已合并的远端功能分支。

本地提交前仍按[代码审查规范](review.md)依次完成规格审查和质量审查；这两类审查用于提高缺陷发现率，不增加 GitHub required approval，也不替代唯一的 `pnpm verify` 自动化门禁。

仓库规则禁止直接推送 `main`，禁止强制推送和删除 `main`，不得配置持久 bypass。仓库所有者也遵循同一条 CI 门禁；临时排障不能通过关闭 TLS 校验、强推或绕过 required check 完成。

## 官方依据

- [GitHub Actions workflow 与 concurrency 语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [actions/checkout](https://github.com/actions/checkout)
- [actions/setup-node](https://github.com/actions/setup-node)
- [actions/setup-python](https://github.com/actions/setup-python)
- [pnpm/action-setup](https://github.com/pnpm/action-setup)
- [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv)
