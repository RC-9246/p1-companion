# P1 实时资源面板

在 P1 上自托管的只读页面：CPU 与各核心、可用内存、磁盘、温度、ZRAM、网络速率、容器运行状态、模块启动报告和维护巡检。每 5 秒采样，保留最近 30 分钟内存内趋势。无需 Node、数据库、Prometheus、Grafana 或额外 Docker 镜像。

## 访问

P1 服务器只监听 `127.0.0.1:6190`。在自己的电脑建立 SSH 转发后打开 `http://127.0.0.1:6190/`。例如：

```sh
ssh -N -L 127.0.0.1:6190:127.0.0.1:6190 p1admin@P1地址
```

Mac 可运行 `zsh services/monitor/connect-macos.command`；需要双击时，先为该文件加执行权限。它不保存密码；使用已配置的 SSH 密钥或交互式登录，并保留严格主机密钥校验。可用 `P1_MONITOR_HOST` 设置 SSH 目标。只有自己已有的主机密钥别名需要兼容时才设置 `P1_MONITOR_HOSTKEY_ALIAS`，不要跳过指纹检查。Mac 睡眠或网络变化可能断开转发，重新运行连接脚本即可。

默认没有新增 LAN 或公网监听，也没有独立账号密码；访问边界是已认证的 SSH 连接与两端回环地址。本机其他用户仍可能访问同一回环端口。需要手机、外网或多人访问时，应另行设计认证和加密入口，不能直接把此端口绑定到公网。

## 安装与管理

先完成主项目部署，确保固定的 P1 根目录和既有健康巡检脚本存在。面板使用系统 Python 3 标准库及 systemd，Docker Engine 本机 socket 提供容器指标。默认路径 `/home/p1admin/p1-agent`，迁移到其他部署目录时需调整采集器参数、unit 与安装器根路径。

在仓库根目录执行：

```sh
sudo python3 scripts/install_monitor.py
```

源码安装到 `/opt/p1-monitor`，启动并设置开机运行的服务为 `p1-resource-collector.service` 与 `p1-resource-panel.service`。安装前创建私有恢复点，独立回滚进程在 150 秒内未收到提交标记时恢复之前的文件与服务状态。通过 unit 验证、面板健康和原项目健康检查后才提交。本模块不重启 AstrBot、SnowLuma 或其他既有容器，不改插件、QQ 权限或记忆数据。

重新安装只重启这两个新服务。查看状态可用：

```sh
systemctl status p1-resource-collector.service p1-resource-panel.service
```

安装器输出实际恢复点。需要回滚时，在确认该恢复点对应当前安装后执行：

```sh
sudo python3 scripts/install_monitor.py --rollback /home/p1admin/p1-agent/backups/resource-panel-时间
```

这将恢复该次安装前的面板源码、unit 和启用状态，不恢复或覆盖聊天数据库。

## 进程边界与自恢复

采集器是独立的本机进程，只请求 Docker 的版本、容器列表与一次性统计 GET 接口。它读取 `/proc`、温度传感器和现有维护报告，向 `/run/p1-monitor/snapshot.json` 发布白名单字段。不请求容器环境变量、完整 inspect、容器日志、聊天正文或账号配置；容器列表响应里未纳入白名单的字段（包括命令行与标签）会丢弃，不发布到网页。运行历史也在此 tmpfs 文件及内存中，不写入聊天数据库或持久保存到 SSD。

网页服务使用 systemd DynamicUser，无法访问 Docker socket 和用户 home，仅服务固定静态资源及状态 API。它没有重启、删除、执行命令或任意文件读取接口。回环 Host 校验、无跨域授权、CSP 与防嵌入响应头限制浏览器访问。网页没有外部脚本、字体、图片或分析服务。

Docker socket 本身不具备只读权限模型：采集器仍拥有高权限本机 socket 访问，因此源码需要保持 root 所有、不可由网页进程或模型写入。GET 路径白名单不等于把 Docker 权限降为只读；这里的关键边界是采集与网页进程分离，网页从不代理 Docker API。

采集器每次成功发布后通知原生 systemd watchdog；45 秒无成功采样时由 systemd 处理故障并按既定重启策略恢复。网页进程异常退出也会重启。两者设有启动频率限制、低优先级、CPU 限额，内存上限分别 64 MiB 与 32 MiB；这些上限不是平时占用。不让面板失败触发机器人重启，也不声称能自动修复系统内核或硬件故障。

## 指标的含义

- 主机与容器 CPU 均按整机 CPU 时间归一化：六核机器的一核满载约为 16.7%。与 Docker CLI 的“100%代表一核”口径不同。
- 主机内存使用率按 `MemAvailable` 计算可用余量；容器占用扣除可回收文件缓存。两者统计范围不同，不应强求容器合计等于主机占用。
- 容器任务数来自 cgroup PIDs 统计，包含线程，不应理解为同样数量的独立应用进程。
- ZRAM 同时展示换出页的逻辑大小和压缩后的物理内存占用，不把它当额外物理内存。
- 首次或计数器重置时 CPU 显示待采样，不把缺失指标伪装成零。容器无法读取时显式提示；超过 15 秒没有新采样时标记采集中断。历史缺口不连成虚假的连续曲线。
- 运行中的 QQ 容器不等于 QQ 账号在线。面板没有额外登录或消息发送测试。
- 模块就绪是启动报告，数据库与修复来自既有的定期巡检，页面会显示报告时间；不是每 5 秒重新扫描数据库。
- 当前趋势保留 30 分钟且重启后清空；不提供长期审计、完整日志或长期峰值保证。

## 验证与开销

完整离线测试 365 项，中性核心测试 198 项；其中 13 项面板专项覆盖统计口径、不可用/过期数据、敏感字段过滤、Host 防护、任意文件拒绝和写接口拒绝。浏览器核验真实 P1 指标、8 个容器、手动刷新和趋势切换。

一次约 20 秒真实采样中，两个新服务 cgroup 内存合计约 22.2 MiB，进程 RSS 合计约 38.2 MiB，CPU 约占整机 0.175%，状态 API 响应中位数约 11.7 ms。RSS 包含共享页，与实际分组记账不同。此短样本不能代表所有峰值或长期运行；性能证据只记录面板本身的开销，不上传主机实时历史、聊天或登录数据。

指标算法依据 [Docker Engine 统计文档](https://docs.docker.com/reference/api/engine/version/v1.51/)，隔离与资源限制依据 [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)。部署证据见 `evidence/resource-panel-postflight.json`。
