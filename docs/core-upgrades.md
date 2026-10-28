# AstrBot / SnowLuma 组件升级、修复与回滚

[← 项目首页](../README.md) · [安装向导](installation-wizard.md) · [现有故障恢复](recovery.md)

在安装向导左侧打开 **07 · 版本与修复**，选择组件，查询官方稳定版，然后选择具体版本执行升级。已有 Companion 可以直接使用该页，不必重新填写 QQ 号和 API Key。一次只升级一个组件；在观察结束前不会开始另一项升级。

这是管理员发起的受控升级。程序不会每天自行安装 latest，也不把该能力授予普通聊天模型。只保护通过本程序执行的升级；AstrBot 自带更新按钮、手动拉取镜像及外部脚本不自动纳入本事务。

## 如何打开

Windows 10/11 x64：重新运行完整项目中的 `开始安装.cmd`，进入“版本与修复”；操作仍在原 WSL/Linux 环境执行。请核对第一步里的安装位置，避免选择新安装。Windows 原生程序、手工解压版和非 Docker 版不在本升级器支持范围。

Linux / WSL：在完整源码目录运行：

```sh
sudo python3 deploy/wizard.py --manage-root /srv/p1-agent
```

程序给出带一次性会话信息的本机地址。远程 P1 可用 SSH 将本机 6191 转发到 P1 的 `127.0.0.1:6191`，然后打开地址。向导仅监听 loopback，沿用安装器的会话、Origin、Host 和请求体校验。请勿把向导端口直接暴露到公网。

安装器清理后，可以从保留的原下载目录或重新下载的完整源码再次打开。升级进入观察期后关闭网页，不影响独立 systemd 任务继续观察和处理故障。

## 升级流程

1. **选择明确版本。** 查询两个固定官方仓库近期稳定发布，排除 draft、预发布和任意镜像地址。发布存在不等于 Docker 镜像已经可用；先拉取并记录实际本地 image ID。
2. **先准备程序。** AstrBot 使用项目锁定的依赖重新构建扩展镜像，避免重建容器后丢失依赖。构建上下文只有经过源码清单核对的 Dockerfile 和依赖文件，不发送整个用户目录。
3. **保存旧程序与数据。** 暂停已有维护定时器，等待巡检结束并取得共享锁；停止所选组件，冻结其旧程序可写层，保存私有元数据和全部受支持数据挂载的副本。原始 Compose 不改，镜像、内存限制、端口与网络均有记录。
4. **无外网预检。** 新版本在复制的数据上启动，不发布端口、不连接 QQ 或模型。AstrBot 核对管理入口及新的 Companion 模块就绪记录；SnowLuma 此阶段核对 WebUI 启动，不能把它当作已登录 QQ。随后让旧程序读取新程序处理后的副本，检查退回能力。
5. **数据库迁移门槛。** 检查 SQLite 完整性和结构。发现结构变化或新旧版本兼容性失败时拦截，不在生产数据上尝试不可逆迁移。这类版本需要单独适配，不能用“强制升级”绕过。
6. **切换并检查。** 保留停止的旧容器，使用原数据和网络启动新镜像。AstrBot 核对真实服务及新鲜的模块就绪状态；SnowLuma 还通过本机 OneBot `get_status` 确认在线。要求连续健康采样，并保留容器资源限制。
7. **有限修复。** 未通过检查时，最多尝试一次重启、一次按原配置重建。尝试先写持久账本再执行，程序中断不会重置次数；修复不包含模型生成的任意 shell、放宽权限或在线乱改依赖。
8. **观察 15 分钟。** 独立 systemd 任务约每 30 秒核对状态。修复成功或整机重新启动后重新计算完整观察窗口，不用系统时间跳变提前宣布成功。通过后将已验证镜像写入原恢复基线，恢复维护定时器。
9. **失败回退。** 严重故障或修复耗尽时，先停止候选版本，再用当前数据的隔离副本验证旧程序，成功后回退程序。**不把升级前数据库覆盖回当前数据**，不重放送达状态不明的 QQ 消息。

## 修复与回滚能做什么

| 情况 | 行为 |
| --- | --- |
| 镜像不存在、拉取或依赖构建失败 | 保持旧服务，返回封闭错误码；不会停机后才发现拉不下来 |
| 隔离副本无法启动、模块不就绪或结构发生迁移 | 拒绝切换，重新启动原版本 |
| 观察期内进程退出、健康接口失败、OOM 或模块启动失败 | 有限重启/重建；仍失败则尝试回滚 |
| 升级进程被强制结束、网页关闭或宿主重新启动 | 已落盘的守护入口接续；未完成切换尝试恢复旧服务，观察期重算 |
| 新版本已有新聊天 | 保留当前数据库，退回程序前验证数据兼容性 |
| 当前数据不能通过旧版检查、恢复元数据被改、发现外来容器/后续版本 | 停止自动覆盖，标记 `rollback_blocked`，保留数据和私有恢复点 |
| 观察通过以后才出现问题 | 常规维护按原规则继续；管理员可以发起最近一次升级的手动回滚。15 分钟后的任意新缺陷不承诺自动降级 |
| 回复质量、人格变化、第三方 API 语义变化、账号安全验证 | 不能仅凭服务健康自动识别或修复；需要额外行为验收或本人处理 |

本机 OneBot 在线只证明当次接口报告在线，不等于做过真实 QQ 收发。升级器不主动向好友/群发送测试消息；可由管理员在观察期间真实试聊，发现行为问题时手动回滚。

## 命令行

```sh
# 默认仅展示计划：不拉取、不停机、不写入
python3 services/updater/manager.py --root /srv/p1-agent plan

# 查询官方近期稳定发布；不代表镜像已构建
python3 services/updater/manager.py check --component astrbot
python3 services/updater/manager.py check --component snowluma

# 在完整项目目录执行。版本仅为示例，请先查询
sudo python3 services/updater/manager.py --root /srv/p1-agent \
  --source "$PWD" apply --component astrbot --version v4.29.3

sudo python3 services/updater/manager.py --root /srv/p1-agent \
  apply --component snowluma --version v2.2.1

sudo python3 services/updater/manager.py --root /srv/p1-agent status

# 最近一次组件升级；保留当前数据，重新验证旧版兼容性
sudo python3 services/updater/manager.py --root /srv/p1-agent rollback
```

输出中的 `ok` 表示命令读取/处理成功；**升级结果必须看 `state`**：

- `observing`：已切换，尚未完成观察
- `succeeded`：观察通过，恢复基线更新
- `rolled_back`：已回到旧程序并通过基础检查，升级本身未成功
- `rollback_blocked`：自动恢复未通过，需要管理员处理；不能删除账本来重新获得次数
- `already_current`：解析得到的镜像与现用镜像一致

## 支持的部署与数据保护

当前支持 Linux / WSL systemd + Docker，容器名与 Compose service 分别为 `astrbot`、`snowluma`，原始文件位于 `<root>/astrbot/compose.yaml` 和 `<root>/snowluma/compose.yaml`。拒绝 host 网络、额外未知挂载、远程数据卷、特殊共享命名空间、特权容器和静态 IP 布局；这些部署需要单独适配。

AstrBot 识别 `/AstrBot/data`；SnowLuma 保留 `/app/data`、`/app/.config`、`/app/.local/share`，支持本项目目录内的 bind mount 或对应 Compose 管理的本地命名卷。不会运行 `docker compose down -v`、删除账号卷或覆盖原 Compose。原文件本身可能仍引用旧镜像；后续升级继续通过本页管理，原维护器从已更新的封存镜像恢复。手动运行原 Compose 可能改变已接受版本，应重新核对。

恢复点位于目标设备的 `backups/core-upgrade-*`；旧程序冻结镜像仅保存在该设备 Docker 中。**恢复点、程序镜像层和私有检查记录都可能包含凭据或账号信息，不能上传公开仓库或推送镜像。** 公共状态只展示版本、阶段、有限动作与错误码，不返回环境变量、原始日志、聊天或 Cookie。

磁盘预检为数据副本预留空间；磁盘不足时停止。恢复点不自动当作垃圾删除，请结合离机备份管理容量。一次升级会有快照和预检造成的停机，数据较多时可能较长；不是零停机蓝绿发布。容器硬限制保留，但不保证所有新版本都适合 4GB 设备。

涉及新 EULA、隐私条款、扫码或验证码时，不替用户接受或绕过；未就绪会被检查拦截。Docker 网络、代理和官方镜像源不可用时，不改变现用服务。

## 验收与边界

```sh
python3 -m unittest discover -s tests -p test_core_updater.py
python3 -m unittest discover -s tests -p test_installation_wizard.py

# 可选：真实 Linux root + Docker + systemd + 本地工作台镜像
# 仅使用合成数据库、唯一前缀容器与临时网络
sudo python3 tests/core_upgrade_acceptance.py --run --output /root/core-upgrade-lab.json
```

隔离验收使用本地 Python 测试镜像模拟正常版本、启动失败和结构迁移，实际执行 Docker 创建/冻结/替换/回退及 SIGKILL；原生产 AstrBot / SnowLuma 的容器 ID、启动时间和重启次数前后对比。它与真实上游版本升级、真实账号收发、整机断电测试是不同证据，不能互相替代。具体结果与限制见 [组件升级验收](../evidence/core-upgrade-validation.json)。

官方升级方式参考：[AstrBot Docker 部署](https://docs.astrbot.app/en/deploy/astrbot/docker.html)、[SnowLuma 更新](https://snowluma.github.io/en/docs/guide/deploy/update)。本升级器在保留数据的基础上增加隔离预检和恢复流程，不代表上游保证所有版本可以安全降级。
