# 受检一键集成：少接线，先检查，可恢复

[← 返回项目首页](../README.md)

**什么也没安装的新用户，请使用 [Windows / Linux 图形安装向导](installation-wizard.md)**。它会安装 Docker、AstrBot 与 QQ 接入并生成配置；本文保留给已有 AstrBot 的原集成入口。

新增的 `deploy.sh` / `deploy/install.py` 把现有脚本串成一个入口。适用场景是**已有 AstrBot + SnowLuma / OneBot + 模型，QQ 已能正常聊天**的新 Companion 安装；不会替代 QQ 扫码、B站登录、验证码、模型开户或 Docker 安装。旧的脚本与 Compose 模板保留，仍可按[手动指南](deployment.md)部署。

## 一条命令开始

在目标 Linux 主机克隆仓库后执行：

```sh
sudo bash deploy.sh --apply
```

默认根目录 `/srv/p1-agent`。交互终端会询问机器人和主人的 QQ 号；不询问或保存账号密码。需要其他目录或无交互运行时：

```sh
sudo bash deploy.sh --root /srv/my-agent --apply --bot-id 10001 --owner-id 20002
```

先做只读诊断也可以，不会构建镜像、写配置或停止服务：

```sh
sudo bash deploy.sh --root /srv/my-agent --check
```

所有命令使用本地已下载源码，不把远程脚本直接管道送入 sudo。首次安装默认不启用自主社交；确有需要可显式加 `--enable-social`，或在真实聊天验收后用主人命令开放。

## 当前支持的部署形态

- Linux，Python 3.11+，Docker Engine、Docker Compose v2 可用；至少为 4GB 档主机（系统可见总内存 ≥3 GiB），安装时可用内存 ≥1 GiB，并预留 8 GiB 可用磁盘用于构建。ARM64 与 x86_64 允许进入检查；现有持续运行环境为 RK3399 / ARM64 / 4GB，不能把这一点当成所有 x86 或 ARM 设备都已实机验收
- 核心容器名为 `astrbot`、`snowluma`，均已运行且健康。AstrBot 是 root 容器，Compose 服务名为 `astrbot`，使用单个 `根目录/astrbot/compose.yaml`；SnowLuma 的 Compose 位于 `根目录/snowluma/compose.yaml`
- `根目录/astrbot/data` 必须是 AstrBot `/AstrBot/data` 的实际 bind mount。原生 `cmd_config.json` 已有可用模型和 ID 为 `qq_snowluma` 的平台
- 无现有 Companion 数据、同名工具容器、同名网络或已启用的旧维护 timer。首次版本主动拒绝覆盖这些对象；现有生产升级继续走备份、补丁与验收流程
- 首次构建需要能够访问已列明的上游镜像仓库和软件包源。不会擅自替换镜像源、关闭证书校验或自动安装 Docker

不符合标准布局时，诊断会给出代码而不修改配置。多 Compose 文件、`network_mode`、自定义非 root AstrBot、多实例与已安装 Companion 请使用手动方案。

## 自动完成的步骤

1. 校验源码清单，检查系统、模型配置存在性、核心容器、挂载、Compose、命名冲突与磁盘
2. 将公开源码复制到本机私有安装目录，仅在副本里替换部署根路径，原仓库脚本不改
3. 以当前 AstrBot 的镜像 ID建立本地基线，构建固定依赖扩展镜像，再构建浏览器和解析器。依赖保存在镜像中，重建容器后仍在；镜像使用本次任务专属标签
4. 运行中性离线检查，备份配置和将要替换的源码；慢构建完成后才暂停 AstrBot
5. 调用原 `bootstrap.py` 安装八个插件、MCP 配置与独立内部令牌；启动公开浏览、解析、B站和工作流共六个辅助容器
6. 初始化受控 n8n 工作流并关闭首次 owner 设置页；凭据留在服务器私有目录，不打印到终端
7. 使用本机生成的 Compose override 为 AstrBot 接入依赖镜像与内部网络；不修改原核心 Compose
8. 等待八个容器及五项插件就绪标志，核对容器内依赖，保存成功回执

成功回执包含恢复点和仍需人工验收的事项。容器与就绪标志不能证明 QQ 在线、真实消息已送达、B站已登录、模型效果合格或所有后台活动长期可靠。

## 失败时发生什么

每次运行在 `根目录/backups/oneclick-时间-PID/` 保存私有日志、源码副本、前态、阶段状态与回滚所需的原始镜像 ID。目录 0700，状态和日志 0600；配置备份含密钥，不能上传 GitHub 或发给模型。

命令经一个启动门执行：先记录子进程 PID 与 Linux 启动标识，再允许子进程执行；阶段超时会终止其进程组。父进程异常退出时，独立监护进程在取得同一部署锁后清理正在运行的子进程并尝试回滚。正常失败也走相同恢复路径。

回滚只删除本次管理项目下的工具容器，拒绝操作项目标签不符的容器；恢复原插件、原配置和原始 AstrBot 镜像，保留被替换文件。已有数据库不回滚，新写入历史不会被旧快照静默覆盖。新生成的 Companion 状态保存到恢复点 `replaced/`，不直接删除。构建出的镜像仍保留，磁盘清理应另行核对。

Docker、磁盘或主机本身失效时，自动回滚也可能失败；状态会记为 `rollback_failed`，不声称已经恢复。断电后的服务恢复依赖 Docker 原有策略；该安装器不是开机级灾难恢复系统。

## 查看和撤回最近一次安装

```sh
sudo bash deploy.sh --root /srv/my-agent --status
sudo bash deploy.sh --root /srv/my-agent --rollback /srv/my-agent/backups/oneclick-实际恢复点
```

已成功安装的撤回仅允许最近一次任务，并核对安装后的插件、配置及核心镜像。若已有人继续改了配置或源码则拒绝自动覆盖，改用按差异恢复。普通重复安装会被诊断拦住，不会自动重写白名单、关系记忆或权限。

## 以后重建 AstrBot 时

原核心 Compose 保留意味着重建时也要带上生成的 override，否则仅执行旧的 `docker compose up` 会失去新增依赖镜像或内部网络。`恢复点/state.json` 的 `core_project` 保存原项目名，使用相应的根目录与恢复点：

```sh
sudo docker compose -p 原项目名 \
  -f /srv/my-agent/astrbot/compose.yaml \
  -f /实际恢复点/companion-override.json \
  up -d --no-deps --no-build --pull never astrbot
```

该命令复用本次构建，不自动升级上游。更新 AstrBot 版本时先做兼容测试与新恢复点，不把重复运行首次安装器当作升级。可选的旧宿主维护脚本还要求其文档中的标准核心 Compose 项目名；自定义项目名应先人工适配再封存。

## 一次安装后，接下来做什么

1. 私聊机器人，验证真实 QQ 收发、图片、独立记忆和权限命令；再按实际需要开放群与主动行为
2. 使用 B站时，由主人 `/B站 登录` 扫码、`/B站 状态` 核验；安装器不替你登录
3. 如需 max / quick 模型别名，按[原指南](deployment.md)和[延迟说明](group-latency.md)配置与核验，不自动改变模型账号或目的地
4. 自动宿主维护和资源面板保留为**验收后的可选步骤**，不在新机器未验收前启用。使用本次恢复点 `source/` 中已完成根路径适配的脚本：

```sh
sudo python3 /实际恢复点/source/scripts/install_maintenance.py --root /srv/my-agent --apply
sudo python3 /实际恢复点/source/scripts/install_monitor.py
```

先满足原[维护前提](recovery.md)再执行。这里会写 systemd 单元和封存恢复检查点；属于独立运维安装，不由前面的一键任务回滚。面板仍仅回环监听，经 SSH 访问。

## 验证范围

- `python3 -m unittest discover -s tests -p test_easy_deploy.py`：27 项安装器专项（含十个阶段的模拟 Docker 故障注入），覆盖路径/输入检查、只读诊断、旧安装拒绝、源码校验、隔离副本、权限、部署互斥、子进程启动门、超时与回滚
- `sudo python3 tests/portable_easy_deploy.py`：在 Linux 的临时目录隔离运行真实 bootstrap、校验插件文件与 UID/GID/权限、验证根路径映射和恢复，检查原数据库的新记录保留。不创建账号，不修改 Docker 容器
- 本次 Linux 文件验收核对了 89 个中性插件文件、令牌 UID/权限、源码组读权限与根路径适配，回滚后新数据库记录保留；生产 135 个插件文件及八个容器启动时间、重启次数未变。27 项专项也已在 Linux 运行通过，见 [去敏结果](../evidence/easy-deploy-validation.json)。
- 当前工具服务的历史镜像和单模块验收见 `tests/portable_images_live.py`、`tests/portable_leisure_install.py` 及各专项证据。它们与新协调器的文件级验收分别说明

尚不把“所有上游镜像从空缓存构建、全新账号首次登录、真实 QQ 投递、全部模块行为”合称一次已完成的冷部署验收。依赖源可达性和第三方版本变化应在目标机器实际检查。
