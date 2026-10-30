# Windows 桌面可行性样机

样机把现有 Cairn 界面装入 WinForms / WebView2 原生窗口，由应用管理独立的 PostgreSQL 18、pgvector、本地 API、文件存储与后台摄取任务。运行时无需 Docker、单独安装 Python/PostgreSQL 或配置 SMTP。当前仅验收 Windows x64；这不是已发布的跨平台安装包。

## 启动

运行 Windows 安装程序，选择独立的程序目录（默认 `%LOCALAPPDATA%\Programs\Cairn`），完成后从开始菜单启动 Cairn。Cairn 程序安装到当前用户目录；补装系统组件可能需要管理员授权。ZIP 运行包仍可完整解压后双击 `Cairn.exe`，但不包含安装器的组件补装流程。

当前随包 PostgreSQL 要求**程序目录完整路径只含 ASCII 字符**（英文、数字及符号，可以有空格）；安装器会提前拒绝中文等非 ASCII 程序路径。若 Windows 用户目录含非 ASCII 字符，请另选当前用户有写权限的 ASCII 路径。此限制也适用于 ZIP 的解压位置。项目数据目录可使用中文，与程序目录分开。

安装器会检测 .NET Framework 4.8+、Microsoft Edge WebView2 Runtime 和 Visual C++ v14 x64 运行库（至少 14.44.35207）。缺失时联网从微软下载，验证数字签名后安装并重新检测；已有符合版本的组件会直接跳过。.NET/Visual C++ 安装可能请求管理员授权。取消、下载失败、签名错误或安装后仍不可用会停止安装；组件要求重启时请保存工作、重启 Windows 后重新运行同一个安装包，不会自动重启。首次启动自动初始化数据库并执行迁移，随后显示注册/登录页。邮箱密码直接注册，不发送邮件。

手动更新时先正常关闭 Cairn，再运行新安装包并选择原安装目录。仅接受空目录或带本安装器标记的目录；ZIP 解压目录请另选空目录安装，原数据目录仍可通过 `--data` 使用。更新前建议登录后从「账户 → 设置 → 数据管理」备份。写入失败会明确报错，修复占用或权限后可重新安装；不承诺失败时自动回滚程序文件。

可从 Windows「已安装的应用」或程序目录的 `Uninstall.exe` 卸载。卸载不会移除共享的 .NET、WebView2 或 Visual C++ 运行库；仅删除安装包列出的程序文件，不递归清空目录；项目、资料、模型配置、备份、自定义文件和未列入当前版本的旧文件保留。运行中的 Cairn、被占用的可执行文件、目录联接或符号链接会阻止安装/卸载，安装器不结束其他 Python/PostgreSQL 进程。安装包尚未签名，也不包含自动更新。

默认数据目录为 `%LOCALAPPDATA%\Cairn\DesktopPrototype\data`，与程序文件分开。也可通过 `Cairn.exe --data "D:\Cairn data"` 指定目录。程序为该目录设置当前用户、SYSTEM 和管理员的访问权限，同一目录只允许一个实例运行。数据库和 API 只绑定 `127.0.0.1`，自动选择空闲端口。API 在既有账号会话外还要求每次启动生成的应用凭据，凭据通过父子进程管道交给原生窗口。

关闭窗口会先停 API 和后台任务，再让数据库正常退出。Windows Job Objects 管理整个进程树，强制结束后由 PostgreSQL 在下次启动恢复已提交数据。失败写入数据目录 `logs/runtime.log`，不会自动重置数据库。

## 备份与恢复

登录后的「账户 → 设置 → 数据管理」提供备份、恢复到新目录及打开数据目录。登录和注册页面不显示 API 配置或数据管理；启动失败时提供错误说明与「重试启动」。备份先停服，生成带 SHA-256 清单的 `.cairn` 文件，再重新启动。恢复会校验内容并创建新目录，保留现有数据；默认启动方式会记住恢复位置，自定义启动仍以 `--data` 为准。已有备份文件和已有恢复目录均不会被覆盖。

备份是 Windows PostgreSQL 18 冷备份，包含账号、项目、文件及应用内部密钥，不包含AI模型凭据（`model-settings.dpapi`）、浏览器缓存、日志或程序文件。恢复后服务地址、模型名和API Key均需重新填写；已有索引仍须使用相同地址/模型。已有项目、索引与资料保留。仅导入自己信任的备份并妥善保管。异常退出后须先启动再正常关闭，才能备份。跨平台恢复与数据库大版本升级尚未支持。

## AI 模型设置

登录后，工作区顶部的「AI / API 配置」可直接打开模型设置；也可从「账户 → 设置 → AI 服务 → AI / API 配置」进入。分别提供回答模型与知识索引配置，可只启用其中一项，也可全部留空。回答模型支持现有openai-compatible、openai-responses、anthropic和gemini协议，填写服务基础地址、模型名称与API Key；首版只有一个稳定default模型，不下载模型或管理OAuth。知识索引使用兼容`/embeddings`接口的基础地址、模型与API Key，固定1024维。云端和本机服务使用同一输入方式，无鉴权本机服务也须明确填写`local-no-auth`等非空占位值。

API Key输入框以密码方式显示，打开对话框不会读回或显示旧Key；留空保留该组已保存的Key，新配置必须填写。取消启用并保存会清除此组配置；「清除全部模型配置」需要明确确认，保留项目、文件和已有索引。服务地址不能含用户名/密码、查询参数或片段。保存会安全停止服务、校验并加密写入，再正常重启；「已配置」只表示本机配置存在，不表示已联网或推理成功。

模型凭据独立保存在数据目录的`model-settings.dpapi`，由Windows同用户DPAPI加密，沿用目录ACL和DataLock，通过临时文件和atomic replace保存，不改内部`settings.json`。Key仅经原生进程的UTF-8 stdin传给运行时，不放在命令行、环境变量、WebView、公共HTTP接口、状态元信息或日志。配置损坏时启动明确失败，原生菜单保持可用，可明确清除后重新填写；不会静默忽略损坏配置。默认备份不包含模型凭据，恢复后重新填写。

配置命令复用正常桌面数据库初始化/升级。保存索引配置前只启动随包PostgreSQL，在DataLock与profile排他事务内检查绑定；没有任何历史向量、ready版本或current版本时，允许首次绑定或修正填错的地址/模型。默认profile的固定ID、default-v1版本、1024维、cosine、切片和索引参数保持原样；provider_key保存规范化实际`/embeddings`地址的SHA-256指纹，不含Key。任何历史向量、ready版本或current版本存在后，只允许保持已绑定地址与模型并更换Key；改地址/模型在替换加密文件前拒绝，旧profile、凭据和业务数据保持。尚未绑定地址的旧default索引不能被新配置认领；额外或组织级profile、不兼容合同明确拒绝。缺凭据或清除配置不重写profile。

运行时的`model-status`仅返回安全地址/模型/协议、hasKey、corrupt与indexingPaused，`model-configure`从stdin接收JSON，不接受Key参数。公开API和Web不提供凭据读写路由。原生对话框是正常设置入口，不要把真实Key写入终端历史或提交到仓库。

## 当前限制

桌面版通过「AI / API 配置」填写回答与知识索引服务。GitHub/飞书身份登录尚未接通，登录页会明确说明并使用本机邮箱密码账号；这与 GitHub Skills 导入和飞书文档来源是独立能力。飞书文档同步的桌面服务凭据入口也尚未交付。未配置回答模型时，问答/分析/规划/助手操作生成不可用；项目、任务及历史读取继续可用。未配置索引时，索引任务暂停领取并保留queued，后台文件解包继续工作；已有资料可按关键词检索，响应明确标记keyword_fallback。旧failed上传仍沿现有手动重试入口恢复，不自动改为ready。本地软件与受控服务验收不代表真实云端或本地模型已连通。样机不读取仓库 `.env` 或继承进程中的服务凭据，包括恢复的来源任务也不读取服务器飞书密钥。

新账号可在空工作区点击“创建第一个项目”；已有项目时可从项目任务页标题旁点击“创建项目”。owner/admin/member可创建，viewer没有入口；打开表单保留原任务区，取消不丢任务输入。成功后逐页读取直到找到新项目ID再进入；响应未知时完整读取列表供人工核对，保持该次提交锁定，明确关闭后才返回列表。节点图支持阶段分组、进展与依赖提示，编辑复用现有任务详情。完整 V1 仍须完成下列交付项。

正式交付仍需签名、真实模型验收，以及 macOS/Linux 原生运行与升级验收。当前更新方式是关闭应用后手动运行安装包；缺少系统前置组件时由安装器联网补装，不承诺缺失组件情况下的离线安装。

## 运行依赖范围

| 依赖 | 交付方式 |
| --- | --- |
| Python 3.13、Python 包及扩展 | 随包提供，不使用用户安装的 Python |
| PostgreSQL 18、pgvector | 随包提供独立实例，不需要另装数据库 |
| .NET Framework 4.8+、WebView2、Visual C++ v14 x64 | 检测后下载缺失项，校验微软签名后安装 |
| Docker、Node.js、Git、SMTP | 正常使用桌面版不需要安装或配置 |
| AI 回答与 1024 维 Embedding 服务 | 用户填写服务地址、模型与 Key，不随包提供模型 |

随 PostgreSQL 二进制带入的可选 Perl/Tcl 扩展不在 Cairn 的运行路径中，不要求用户安装这些语言。打包前检查 WebView2 DLL、Python 运行文件、数据库工具和 pgvector 扩展是否完整；安装后的隔离启动验证需覆盖实际加载的 Python 扩展和数据库扩展。

组件部署依据：[WebView2 分发指南](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)、[.NET Framework 部署指南](https://learn.microsoft.com/en-us/dotnet/framework/deployment/deployment-guide-for-developers)、[Visual C++ 运行库](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。

## 开发构建

构建环境为 WSL + Windows，需要已有 Windows PostgreSQL 18 开发文件、Visual Studio C++ 工具链/Roslyn，以及仓库的 Node/pnpm/uv。构建只复制 PostgreSQL 的 `bin/lib/share` 与许可证，不复制或修改现有数据库。可用 `--postgres`、`--vcvars` 指定构建工具位置。

将以下官方材料下载到 `.superpowers/desktop-downloads/`，并核对 SHA-256：

| 文件 | 来源 | SHA-256 |
| --- | --- | --- |
| `python-3.13.17-embed-amd64.zip` | [Python](https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip) | `9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38` |
| `pgvector-0.8.7.zip` | [pgvector](https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.7.zip) | `7b3b8188a5cc0aa96db3c8f3fca1e78a8a612c46545065490c76448705c6b29e` |
| `webview2-1.0.4258.31.zip` | [Microsoft WebView2](https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/1.0.4258.31/microsoft.web.webview2.1.0.4258.31.nupkg) | `56f7f4b8bf9aee4b8efefbbdd4f67d5f74ebd1b100ed0806da71bf76af481aa9` |

```bash
mkdir -p .superpowers/desktop-build
uv export --frozen --package cairn-api --package cairn-worker --no-dev --no-emit-workspace --format requirements-txt --output-file .superpowers/desktop-build/requirements.txt
uv pip install --python-platform x86_64-pc-windows-msvc --python-version 3.13 --only-binary :all: --target .superpowers/desktop-build/python-libs --require-hashes -r .superpowers/desktop-build/requirements.txt
python3 apps/desktop/tools/build_windows.py --output /mnt/c/path/to/cairn-bundle
```

输出目录须在 Windows 本地磁盘。已完成一次构建后，修改自身代码可加 `--code-only` 复用第三方运行文件。前端使用同源 API；不能仅拷贝 `Cairn.exe`，须保留整个目录。

使用官方 NSIS 3.13 Unicode 编译器包装现有运行包（构建不下载依赖、不读取数据目录）：

```bash
python3 apps/desktop/tools/build_installer.py --bundle /mnt/c/path/to/Cairn --output output/desktop/Cairn-Windows-Setup.exe --makensis /mnt/c/path/to/nsis-3.13/makensis.exe --version 0.1.0
```

构建同时生成逐文件 SHA-256 清单。安装器拒绝把数据配置、模型凭据、链接或 Windows 大小写冲突文件纳入负载；程序目录中的 `.cairn-install.marker` 与 `.cairn-owned.ini` 用于确认安装及文件归属，请保留。

## 验证

```bash
PYTHONPATH=apps/desktop/src .venv/bin/python -m pytest apps/desktop/tests/test_object_store.py apps/desktop/tests/test_runtime_boundary.py -q
```

在 Windows 使用包内 Python 执行真实闭环（`--work` 须为不存在的新目录）：

```powershell
.\python\python.exe C:\repo\apps\desktop\tests\windows_smoke.py --bundle C:\path\to\cairn-bundle --work C:\Temp\cairn-desktop-proof
```

验证实际启动数据库、创建账号和任务、上传及解包文件，并检查访问隔离、端口冲突、正常退出、强制结束、数据持久化、备份恢复与文件字节一致性。不启动假模型，不修改原有 PostgreSQL 数据。另在实际机器验收原生窗口、注册登录、工作区、数据菜单和关闭行为。

实现参考：[WebView2 WinForms](https://learn.microsoft.com/en-us/microsoft-edge/webview2/get-started/winforms)、[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[PostgreSQL initdb](https://www.postgresql.org/docs/18/app-initdb.html)。


桌面模型边界的Linux测试与Windows专项：

```bash
PYTHONPATH=apps/desktop/src .venv/bin/python -m pytest apps/desktop/tests/test_model_settings.py -q
PYTHONPATH=apps/desktop/src CAIRN_TEST_DATABASE_URL='<隔离的postgresql+psycopg测试库cairn_test>' .venv/bin/python -m pytest apps/desktop/tests/integration/test_model_binding.py -q
```

```powershell
.\python\python.exe -X utf8 C:\repo\apps\desktop\tests\windows_model_config.py --bundle C:\path\to\Cairn --work C:\Temp\cairn-model-proof-new
```

Windows专项只使用合成Key和新数据目录，验证真实DPAPI/UTF-8 CLI、绑定拒绝保留旧凭据、备份恢复保留profile及缺凭据时不领取索引任务。原生对话框密码遮挡、键盘操作和中文模型保存另由实际窗口验收；此脚本不调用真实外部模型。
