# 从空白设备开始：图形安装向导

[← 项目首页](../README.md)

不需要先安装 AstrBot，也不需要手写 Compose、OneBot 或模型 JSON。一个入口准备运行环境，在中文网页里填写账号与 API Key、扫码并完成安装。此入口为新安装向导 Beta；既有 `deploy.sh` 继续作为已有 AstrBot 的集成入口。

## Windows 10 / 11 x64

1. [下载完整 ZIP](https://github.com/RC-9246/p1-companion/archive/refs/heads/main.zip)，**先解压**到本机目录
2. 双击项目里的 **`开始安装.cmd`**，按 Windows 提示批准管理员权限
3. 若程序提示需要重启，先保存工作、手动重启，再双击桌面上的 **“继续安装 P1 Companion”**。不要删除解压目录
4. 浏览器打开后，按向导填写两个 QQ 号、DeepSeek API Key 和管理密码。其余配置自动生成

Windows 至少为 10 2004 / Build 19041，或 Windows 11；仅 x64，至少 8GB 内存、系统盘 20GB 可用空间，推荐 16GB 内存。CPU 虚拟化需要开启；BIOS / UEFI 设置不能由本程序代替。旧 Windows、Windows ARM、32 位和 Windows Server 不在本入口支持范围内。

程序启用 WSL / Virtual Machine Platform、更新 WSL，并从 Ubuntu 官方下载带 SHA-256 校验的 Ubuntu 24.04 rootfs，创建独立的 **`P1Companion`** WSL2 发行版。它不接管原有 Ubuntu，不改默认发行版，不关闭其他 WSL 发行版，不安装 Docker Desktop，不改全局 `.wslconfig`，不自动重启电脑。

Ubuntu 与安装源码分别存放在 Windows 用户目录 `%LOCALAPPDATA%\P1Companion`、该发行版的 `/opt/p1-companion-installer`。用该发行版的 Linux Docker 运行服务。Windows 通过独立的无界面 `wsl.exe` 客户端维持运行，完成安装后不依赖安装网页。关闭、休眠、重启 Windows 会影响服务在线；之后双击桌面的“打开 P1 Companion”恢复后台并打开管理页。这里没有承诺 Windows 启动后无人值守自动运行。需要长期在线时，推荐独立 Linux 主机。

程序保留重启后的继续入口，不设置自动登录、不绕过 Windows 登录、不自动修改 BIOS。Microsoft / Ubuntu 下载不可达时会停在对应阶段，重试不会删除既有发行版或账号数据。WSL 默认的 localhost 转发需要保持可用；管理员自定义网络配置可能需要额外适配。

## Linux / Station P1

下载并解压完整源码，在项目目录执行：

```sh
sudo bash install.sh
```

缺少 Python 时，入口从系统包源准备 Python；然后显示本机浏览器链接。支持 Ubuntu 24.04、Debian 12/13 以及基于这些版本的 Armbian，ARM64 / x86_64，systemd，Python 3.11+。至少 4GB 档内存、安装时 1GiB 可用内存与 10GiB 可用磁盘；慢构建和上游镜像可能需要更多空间。

在有桌面的 Linux 上直接打开显示的链接。通过 SSH 安装无桌面的 P1 时，在你使用浏览器的电脑另开一个终端，建立本机隧道：

```sh
ssh -N -L 6191:127.0.0.1:6191 -L 6185:127.0.0.1:6185 -L 6190:127.0.0.1:6190 用户名@设备地址
```

再打开程序显示的完整链接。最后的 `#…` 是本次安装会话凭据，仅用于自己的浏览器，不发给其他人。所有网页默认仅监听回环地址，不要为了省去隧道而暴露到公网。

## 六步做什么

| 页面 | 你做什么 | 程序做什么 |
| --- | --- | --- |
| 准备见面 | 选择新设备或已有 AstrBot；可保留默认位置 | 检查系统、内存、磁盘、端口、原有容器与源码 |
| 认识彼此 | 填机器人和主人 QQ、API Key、管理密码 | 自动选择正确配置结构；默认 `deepseek-flash`，准备识图和快 / 慢思考入口 |
| 安一个家 | 阅读范围，点击一键准备 | 用合成短句检查 API，然后安装缺失的 Docker、下载固定镜像、生成配置并启动 AstrBot / SnowLuma |
| 连接 QQ | 在页面里的 QQ 登录画面扫码，完成本人安全验证 | 自动接通带令牌的反向 WebSocket；核验实际 QQ 登录号与所填账号一致 |
| 成为伙伴 | 点击安装；选择是否开启白名单自主社交 | 调用原受检安装器构建依赖、安装八插件及六个辅助容器、配置工作流、检查就绪与保存恢复点 |
| 开始相处 | 添加机器人为好友，私聊确认收到回复；按需扫码登录 B站 | 提供模型测试、B站二维码、自动维护与资源面板安装、撤回入口 |

管理用户名是 `astrbot`，密码是你填写的管理密码。密码按 AstrBot 4.29.1 的 PBKDF2 格式保存，不把明文写入配置。已有 AstrBot 模式不重设原管理密码。

API Key 保存在目标设备受保护的 AstrBot 配置中；不会写入浏览器持久存储、进度记录或公开报告。初次准备环境的按钮会向 **`https://api.deepseek.com`** 发送一条合成连接测试短句，产生少量正常用量，不含聊天历史。最后的重复测试由你点击触发。当前自动配置 DeepSeek 官方接口；其他提供方仍可在 AstrBot 管理页配置，不会把同一 Key 自动发送到其他服务。

使用默认 Flash 时，自动生成普通、高强度、快速三个模型入口以及识图配置。快 / 深两种入口与现有路由 ID 对应；深度思考不意味着输出长文。自定义模型名称时不臆造 Flash 的识图或思考能力。模型是否能正常服务由真实 API 测试判断，模型效果和长期聊天质量还需试聊。

B站二维码在页面直接显示，扫码会登录本机的独立私人浏览空间；登录态不发给外部工程助手，公开评论和弹幕仍禁用。验证码、安全挑战、QQ / B站扫码、账号开户与充值需要本人完成，程序不绕过。

## 安装完成，自动清理向导

第六步默认勾选 **“完成后自动清理安装向导”**。真实试聊确认后点击 **“完成安装”**：程序重新检查 8 个服务与 5 个模块就绪标记，通过后结束安装会话，数秒后关闭 `6191` 向导服务，并将当前页面转到 AstrBot 管理页。你可以取消勾选保留向导排查；未完成或失败的安装不会触发清理。

清理只处理本程序的临时内容：会话链接、浏览器中三个安装专用会话项，以及 Windows 下 `/opt/p1-companion-installer` 内经过清单哈希核对的复制文件。发现改动、额外文件或符号链接时保留对应内容，不递归删除未知目录。原下载 / 解压目录不自动删除。安装记录与日志归档到最近的私有恢复点；恢复点中的源码副本保留，供回滚与审计使用。

AstrBot、SnowLuma 所需的 QQ 桌面、浏览器与工作流服务、记忆、账号登录、配置、管理页和已安装资源面板全部保留。清理向导不卸载 Docker / WSL，不清空镜像、数据库或备份。

Windows 会保留 `%LOCALAPPDATA%\P1Companion\Start-P1Companion.ps1` 和发行版内 `/usr/local/lib/p1-companion/wsl-runtime.sh` 两个小型运行入口。它们没有常驻 GUI；原生 `wsl.exe` 配合持锁的 `sleep` 保持专用发行版在线。程序核对 Windows PID / 启动时间 / 命令和 Linux PID / 启动时间 / 启动标识 / 锁后，才允许结束向导；验证失败就保留向导。这个独立入口是必要的，因为 [Microsoft 明确说明 systemd 服务本身不会让 WSL 持续运行](https://learn.microsoft.com/windows/wsl/systemd#how-does-enabling-systemd-affect-wsl-architecture)。

导入成功后，仅删除与本机创建记录 SHA-256 相符的 Ubuntu rootfs 下载缓存。完成后移除匹配本程序的“继续安装”快捷方式，保留“打开 P1 Companion”。不卸载发行版或删除 Windows 原始源码。需要再次打开安装工具时，从保留的完整源码运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\windows-setup.ps1 -SetupAgain`；Linux 仍可运行原 `sudo bash install.sh`。完成记录保留在私有状态目录 `completed.json`。

## 出错、刷新或撤回

- **API 错误先拦住**：尚未改系统就提示核对 Key、余额、模型与网络
- **下载失败可重试**：Docker 和已下载镜像保留。继续使用同一解压目录、账号与安装位置；未知或发生变化的目录不会被强行接管
- **刷新页面**：阶段记录在本机私有目录；QQ 号和安装位置可续接，API Key / 密码不会进网页存储。浏览器刷新不等于回滚，设备重启也不能仅凭旧记录判定完成
- **中断**：网页标记未完成任务。原 Companion 安装器的监护与失败回滚继续有效；基础部署保留带归属记录的配置与登录数据。部分写入或后续人工修改不符合预期时停止，避免覆盖
- **撤回 Companion**：自动暂停维护并等待巡检结束，调用原安装器核对最近恢复点及后续源码 / 配置 / 镜像变化。成功恢复原核心，保留数据库，维护定时器保持禁用；重新验收后才能封存开启
- **停止基础服务**：只移除本向导标记的 AstrBot / SnowLuma 容器，保留配置、QQ 登录目录和 Docker。已安装 Companion 时要求先撤回它，不提供“一键清空数据”

系统软件、Docker 软件源、镜像缓存、Windows 组件与 WSL 发行版不在代码回滚时卸载。私有日志位于 Linux `/var/lib/p1-companion-installer`，安装器的恢复点位于目标目录 `backups/`；里面可能包含凭据，不上传 GitHub，不作为模型输入。

## 实现边界

网页只绑定 `127.0.0.1:6191`，使用每次启动生成的会话令牌、Host / Origin 校验和 HttpOnly / SameSite Cookie。API 不提供任意 Shell、URL、恢复点或文件路径读写接口；安装根目录有固定格式与原有目录检查。QQ 桌面仅代理固定本机 noVNC，WebSocket 同样校验会话与 Origin；用户通过官方 noVNC 客户端接口操作画面。B站仅提供两个固定登录操作，原令牌不返回网页。

基础镜像固定为 AstrBot 4.29.1、SnowLuma 1.10.0 并封存多架构 digest；不会自动追随 latest。SnowLuma 按其上游要求使用 SYS_PTRACE / seccomp 例外，不修改宿主机 ptrace sysctl。首次 Docker 安装使用官方 Apt 源；已有可用 Docker 直接复用，冲突软件包不会自动卸载。

自动维护和面板仍是试聊后的可选安装，由程序调用已完成路径适配的脚本。它们属于独立运维安装；撤回时的定时器处理不等于卸载整个维护系统。初次向导不负责账号封禁、硬件故障、未知上游变化或无限期稳定性保证。

## 验证与来源

```sh
python3 -m unittest discover -s tests -p test_installation_wizard.py
python3 -m unittest discover -s tests -p test_easy_deploy.py
python3 -m unittest discover -s tests -p test_installer_cleanup.py
python3 scripts/selftest.py
```

Windows 检查使用 `tests/windows_installer_checks.ps1`，核对真实 PowerShell 语法、只读计划及含空格 / 中文的参数转发。GitHub Actions 已在 Linux 和 Windows 的 PowerShell 5.1 / 7 通过相应检查。**PowerShell 解析 / 计划通过不等于已经在全新 Windows 机器上完成 WSL、重启与 QQ 实号全流程。** 本次未在生产 P1 重装基础环境，也不为做演示覆盖正在使用的 QQ 账号；实际记录见 [验证结果](../evidence/installation-wizard-validation.json)。

上游配置依据：[AstrBot Docker 部署](https://docs.astrbot.app/deploy/astrbot/docker.html)、[AstrBot 4.29.1 配置源码](https://github.com/AstrBotDevs/AstrBot/blob/v4.29.1/astrbot/core/config/default.py)、[SnowLuma Docker](https://snowluma.github.io/en/docs/guide/deploy/docker)、[SnowLuma 配置](https://snowluma.github.io/en/docs/guide/configuration)、[Docker Debian](https://docs.docker.com/engine/install/debian/)、[Docker Ubuntu](https://docs.docker.com/engine/install/ubuntu/)、[Microsoft WSL 安装](https://learn.microsoft.com/windows/wsl/install)、[WSL 命令](https://learn.microsoft.com/windows/wsl/basic-commands)、[Ubuntu 官方 rootfs 与校验](https://cloud-images.ubuntu.com/wsl/releases/noble/current/)、[DeepSeek 模型](https://api-docs.deepseek.com/quick_start/pricing/)、[思考参数](https://api-docs.deepseek.com/guides/thinking_mode/)。
