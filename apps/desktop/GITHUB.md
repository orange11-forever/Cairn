# GitHub 桌面授权与仓库关联

桌面版使用 GitHub OAuth App 的 Device Flow。Cairn 显示短期验证码，用户在系统浏览器的 GitHub 页面确认；应用不会接收 GitHub 密码，也不需要在安装包内保存 Client Secret。网页登录与飞书登录保持各自独立的配置。

## 发布方配置

1. 使用发布方 GitHub 账号打开 **Settings → Developer settings → OAuth Apps → New OAuth App**。
2. 应用名称填写 `Cairn`，主页填写 Cairn 项目主页。注册表中的回调地址可填写 `http://127.0.0.1/cairn-github`；设备流程不使用浏览器回调。
3. 勾选 **Enable Device Flow**，保存后复制公开的 **Client ID**。无需生成或分发 Client Secret。
4. 构建时传入 `--github-client-id PUBLIC_CLIENT_ID`。构建产物的 `github-app.json` 只包含 `{"clientId":"PUBLIC_CLIENT_ID"}`。普通用户不需要注册应用或填写此配置。

未配置 Client ID 的开发包仍可用邮箱登录和关联本地仓库；尝试 GitHub 授权时会明确提示发布方配置缺失。桌面运行时不读取服务器 OAuth 环境变量。发布方应在实际注册页面核对 Device Flow 开关；注册方式见 [GitHub 官方指南](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app)，协议见 [Device Flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow)。

## 用户流程

- 登录页的「使用 GitHub 登录」只发起身份验证，完成后仍需在 Cairn 点击「完成登录」。已有邮箱账号可在「登录方式」绑定 GitHub，避免另建账号。
- 「GitHub 仓库授权」单独请求 `repo` 权限。这是 OAuth App 访问私有仓库所需的权限范围，也包含写权限；实际仓库列表和可写状态受账号及组织授权限制。登录成功不会自动保存仓库访问凭据。
- 在「项目任务 → 代码仓库」选择本地已有仓库，或者选择 GitHub 仓库后克隆到一个尚不存在的新目录。关联现有仓库并选择 GitHub 仓库时，`origin` 必须匹配。
- 关联按 Cairn 用户和项目分别保存。重新打开或刷新时检查本地目录、分支、origin、GitHub 仓库访问权及关联账号；凭据过期、撤权、仓库不可访问或账号变化都会显示具体状态。
- 更换或解除关联保留所有代码文件。克隆失败不建立新关联，并保留新建目录供用户检查；重新操作前先检查该目录。
- 「清除本机仓库授权」仅清除本机保存的访问凭据，保留项目关联和文件。在 GitHub 撤销应用授权请使用 GitHub 的应用设置。授权过期后重新授权；当前没有自动刷新令牌。

## 存储与运行组件

仓库访问令牌和机器相关目录绑定由同用户 Windows DPAPI 加密，存于数据目录 `workspace-settings.dpapi`。不写入数据库、普通 `.cairn` 备份、源码或日志；恢复备份后需要重新授权、重新关联本地目录。代码仓库本身也不在应用数据备份内。

Git for Windows MinGit 随包提供，固定为 `2.56.0.windows.4`。构建验证官方归档 SHA-256；普通用户无需自行安装 Git。克隆使用固定的 HTTPS GitHub 地址、当前用户明确授予的令牌和独立进程环境；凭据不进入命令行、remote URL 或仓库配置。克隆不继承 Git credential helper、hooks、fsmonitor 或系统 Git 配置，不递归获取子模块。架构解析的只读文件清单会遵守全局忽略规则，但仍禁用 hooks 和 fsmonitor。Git LFS 和子模块内容下载尚未提供操作入口。

## 验收范围

自动化覆盖设备授权等待/取消/过期、会话和浏览器绑定、独立仓库权限、错误响应、项目权限、持久化、文件保留和界面操作。受控 GitHub 响应不代表真实 GitHub 授权已经验收。

真实验收需要发布方 Client ID、明确获准的测试账号和仓库：登录并确认、授权仓库、列出并选择仓库、克隆、重启读取、验证只读权限、撤销授权和移除仓库访问权。完成这些步骤前，不能把阶段 2 标记为完整外部验收通过，也不据此发布新版安装器。

2026-10-31 已用专用 Client ID 和获准的 `orange11-forever/mikuOJ` 验证真实身份登录、独立仓库授权与仓库列表。首次授权克隆遇到网络超时，准确返回失败并保留目录；匿名及授权请求恢复后，复用已加密的凭据完成 Windows 克隆、加密状态重读及解除/重新关联。GitHub 侧撤权和私有/只读仓库的真实账号验收仍待补齐。代码与架构工作台见[使用说明](ARCHITECTURE.md)。
