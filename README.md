# HTU Connect

Windows、Linux、macOS 校园网管理工具。Rust 实现唯一的校园网业务，Python 提供本机网页与后台运行，CLI 调用同一本机服务。当前版本 **2.0.0**

完整的功能、接口与实现归属见 [功能接口与实现梳理](docs/功能接口与实现梳理.md)。

## 使用桌面包

选择与操作系统、CPU 架构及 Python 架构匹配的桌面 ZIP，完整解压。需要 Python **3.10+**；发布包已包含 Rust 核心与 CLI，运行时不需要 Cargo 或 curl 命令。

Linux 原生文件使用 OpenSSL 3、zlib、zstd 系统库；CI 在 Ubuntu 22.04 构建。Windows 包使用 64 位 Python。macOS 包的架构以文件名为准。

### Windows

运行 `Setup.cmd`。脚本建立 `.venv`、安装所需依赖并打开本机网页。默认是前台运行，关闭服务进程会停止后台检测；关闭浏览器不会停止服务。

如果同一用户数据目录的新版后台服务已在运行，再次运行 `Setup.cmd` 会直接打开它的网页，使用正在运行服务的实际端口，不重复安装依赖或启动第二个服务。`--install-only` 仍只准备运行环境。

### Linux / macOS

```bash
python3 scripts/setup.py --install-only
bash scripts/start.sh
```

默认端口 8765，可以使用 `bash scripts/start.sh --port 8877`。启动脚本只启动服务，不重复安装依赖。

### 账号和操作

网页以 **HTU Toolbox** 工具箱呈现，采用深色 Material 3 界面，左侧按“控制台 / 校园服务 / 工作区”分组导航，底部状态卡实时显示网络与自动登录。顶部“工作区设置”可调整主题、源色、密度与动效，偏好只保存在本浏览器中；搜索（Ctrl/Cmd + K）可跳转到各页面；窄屏通过菜单按钮展开抽屉导航。

图标采用 Lucide 配合 [Morphicons](https://github.com/guillermolg00/morphicons)，主题、菜单和操作加载状态支持图标变形。图标资源随程序本地提供，无需连接 CDN；“减少动效”会将变形切换为即时更新。版本与许可证见 [图标依赖说明](web/static/vendor/README.md)。

1. 连接校园网，填写账号、运营商及完整门户地址。门户限定为 `http(s)://10.101.2.194:6060/portal.do?...`。
2. 可以点击“自动获取门户地址”，再点击“保存并连接”。首次必须输入密码，以后密码留空保留已有密码。
3. “立即检测”只检测网络。“立即登录”提交认证；认证接受与公网联网分别判断。
4. “停止自动登录”停止后续检测并保存停止状态，不会登出校园网。重新打开服务也不会自行恢复已停止的任务。

程序仅使用一个公网探针。请求失败或响应异常时显示检测错误；只有识别出支持的校园门户，后台才尝试认证。元数据读取失败会终止本次认证。更换网络导致门户参数失效时，重新获取并保存门户地址。

## 系统自启

在网页启用“系统启动时恢复自动登录”，并启动自动登录。停止前台实例后，安装当前用户的系统服务：

```bash
# Windows 使用 .venv\Scripts\python.exe；Linux/macOS 使用 .venv/bin/python
python scripts/install-user-service.py
# 自定义端口
python scripts/install-user-service.py --port 8877
# 停止并移除系统服务，保留账号与日志
python scripts/install-user-service.py --remove
```

三个系统分别使用一个 Windows 计划任务 `HTU-Connect`、一个 systemd 用户服务、一个 LaunchAgent。它们只启动同一个桌面宿主，不执行另一套认证逻辑。

`autoStart` 控制系统启动后的恢复，`enabled` 记录用户的启停选择。只有两者都开启，系统启动才恢复自动登录。手动打开服务则恢复 enabled 状态。

## CLI

CLI 必须使用正在运行的桌面服务。会话端口与令牌从当前用户数据目录读取，不维护第二套账号配置。

```bash
# Windows 文件名为 native\htu-toolbox-cli.exe
native/htu-toolbox-cli net status
native/htu-toolbox-cli net check
native/htu-toolbox-cli net login
native/htu-toolbox-cli net start
native/htu-toolbox-cli net stop
native/htu-toolbox-cli net detect-portal
native/htu-toolbox-cli net logs --tail 250
# 登出前停止自动登录，避免立即重新认证
native/htu-toolbox-cli net logout
```

`net set` 从 stdin 读取配置 JSON，只保存不启动，不通过命令行参数传密码。字段包括 account、operator、password、portalUrl、intervalSeconds、autoStart。服务未运行、请求失败或检测结果含错误时，CLI 返回非零退出码。

## 数据与密码

唯一配置文件是用户数据目录中的 `config.json`：

| 系统 | 默认目录 | 密码存储 |
| --- | --- | --- |
| Windows | `%LOCALAPPDATA%\HTUConnect` | 当前用户 DPAPI |
| Linux | `$XDG_DATA_HOME/HTUConnect`，未设置时 `~/.local/share/HTUConnect` | Fernet；密钥与文件权限 0600 |
| macOS | `~/Library/Application Support/HTUConnect` | Fernet；密钥与文件权限 0600 |

可设置绝对路径 `HTU_RUNTIME_DIR`；应使用当前用户私有目录。安装系统服务时会保存该目录。服务及 CLI 也可使用 `--runtime-dir` 指定同一目录。

目录还包含 `credential.key`（Unix）、运行日志、`service.lock` 和仅在服务运行期间存在的 `session.json`。网页不返回密码。日志最多轮转两个 5 MiB 备份，网页最多读取 1000 行；导出的是当前显示内容。

## 从 1.x 迁移

2.0 更换了接口与配置，需在网页重新输入账号与密码，不自动导入旧密文或 Rust TOML。原 `restart`、`force-login` 和单独的日志下载接口已移除；使用 start/stop、login 及统一日志读取接口。

Windows 更新前停止并移除旧版的两个任务，避免旧进程继续运行：

```powershell
Stop-ScheduledTask -TaskName 'HTU-CampusNet-AutoLogin'
Unregister-ScheduledTask -TaskName 'HTU-CampusNet-AutoLogin' -Confirm:$false
Stop-ScheduledTask -TaskName 'HTU-CampusNet-Dashboard'
Unregister-ScheduledTask -TaskName 'HTU-CampusNet-Dashboard' -Confirm:$false
```

Linux/macOS 先停止旧用户服务，再安装 2.0 服务。旧 `runtime/`、其配置备份及 Rust `config.toml` 不再使用；确认新配置可用后自行删除旧数据。

## 开发与构建

源码构建需要 Rust 1.90.0、Python 3.10+、C 编译工具和 OpenSSL 开发依赖（Linux）。Rust 工具链及组件在 `rust-toolchain.toml` 固定，依赖由 Cargo.lock 锁定。

```bash
python3 scripts/build-core.py
python3 scripts/setup.py --install-only
bash scripts/start.sh
```

构建脚本原子替换 `native/` 中的动态库和 CLI，同时记录源码提交与文件校验值。服务只加载这个目录，不自动编译或寻找其它实现。修改核心后先停止服务，重新构建后再启动服务。

```bash
cargo test --workspace --locked --jobs 2
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo fmt --all --check
python -m unittest discover -s tests -v
node --check web/static/app.js
```

发布包由同一个脚本生成，要求源码干净、原生文件由当前提交构建：

```bash
python scripts/package-release.py
```

CI 在三个桌面系统调用相同的构建与验证工作流；标签发布复用该工作流，上传同一次构建的 ZIP 与 SHA-256 文件，不使用资产分支或备用发布触发方式。

组件测试和模拟协议测试不等于真实校园网认证验证。系统登录自启也需要在相应设备上验证。
