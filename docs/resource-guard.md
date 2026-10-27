# 内存保护与确认空闲后的进程回收

资源面板负责观察；新资源守护负责有边界的处理。它是独立的 Linux / WSL systemd 程序，不依赖模型判断“哪个进程没用”，不消耗模型 API，也没有新增网络监听端口。首次安装向导默认在“完成安装”时开启，最后一步也可单独点击“开启内存保护”。安装向导清理退出后，它继续运行。

## 实际处理范围

- 每 30 秒读取 `MemAvailable` 与内存 PSI，采用连续采样与恢复滞后，避免瞬间波动造成反复暂停
- 4GB 档默认可用内存低于 768 MiB 时暂停新自主重型活动；低于 384 MiB 且连续两次，或低于 128 MiB 时立即进入紧急模式。更大设备按比例提高阈值
- B站浏览器在压力下保存登录状态，再关闭确认空闲的 Chromium；保存失败时保留活会话。进行中的扫码和私密操作不强行中断。持续紧急压力下可取消可选视频观看，使用原取消与计费路径，不伪造已观看记录
- 只回收 `p1-browser` / `p1-leisure` 中被容器 init 收养、失去 Playwright 父进程的无头 Chromium 主进程。绑定镜像及 Compose 归属，复查 UID、路径、父进程、PID 命名空间、cgroup、启动时间和完整参数，并用 Linux pidfd 发送 SIGTERM。至少持续观察 90 秒；最多每轮 2 个、每小时 4 次。PID 被复用或 pidfd 不可用时跳过
- 既有明确限额不覆盖。对已验证归属、尚无限额的核心容器，只有当前 cgroup 用量低于目标上限 70% 时，才设置并回读验证内存 / 交换 / 进程数限制；不在内存已接近上限时突然收紧

| 新安装默认核心保护 | AstrBot | SnowLuma |
| --- | --- | --- |
| 内存上限 | 1536 MiB | 1792 MiB |
| 内存软预留 | 768 MiB | 1024 MiB |
| 内存与 swap 合计上限 | 2048 MiB | 2304 MiB |
| 进程及线程数上限 | 256 | 1536 |

新设备的核心 Compose 从创建时带上限。已有设备保留原软预留值（Docker 更新为 0 不会清除旧软预留），不覆盖原 Compose：守护按镜像与 Compose 归属核对后补上缺失限额，已知镜像重建后可再次核验；镜像或归属改变则停止接管并报告。cgroup v1 不能可靠测出当前用量时跳过自动补限额。`memory + swap` 的含义遵循 [Docker 官方说明](https://docs.docker.com/engine/containers/resource_constraints/#--memory-swap-details)。

恢复至少需要可用内存回到 1024 MiB（大设备按比例提高），且连续三次压力较低。活动暂停租约 90 秒过期；守护停止后不会留下永久暂停。用户手动的暂停、免打扰、权限与活动额度不变。

## 保留与限制

不运行 `drop_caches`、`killall`、按进程名称批量 kill、全机内存清空、数据库清理或 swap 重置。不会结束未知进程、QQ、SSH 或其他应用，也不把缓存占用当作内存泄漏。正常公开浏览器已有单请求并发与请求结束关闭机制；工作台 / n8n 继续使用原有容器限额与任务超时。

这些措施降低失控组件拖垮主机的风险，不能保证绝不 OOM。瞬时峰值、内核 / 驱动泄漏、非本项目进程和硬件问题仍可能超出处理范围。容器触及硬限额时，内核仍可能终止该容器内进程；不会禁用内核 OOM 保护。限额应根据实际长期负载调整，不把四个上限相加当作可同时使用的物理内存。[Docker 资源约束](https://docs.docker.com/engine/containers/resource_constraints/) · [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)

## 现有部署安装与控制

在已部署且健康的目标 Linux 上，从本版本完整源码运行（需要 root；不向普通模型开放）：

```sh
python3 scripts/install_resource_guard.py                     # 只显示计划
sudo python3 scripts/install_resource_guard.py --root /srv/p1-agent --apply
sudo /usr/local/sbin/p1-resource-guard.py --status
sudo /usr/local/sbin/p1-resource-guard.py --pause
sudo /usr/local/sbin/p1-resource-guard.py --resume
```

`--no-core-limits` 可在安装时仅启用压力与空闲回收。暂停守护不会撤销已经应用的内核限额。只认可公开旧版本或当前版本的两个协作模块；发生自定义修改时停止并要求人工检查，避免覆盖。更新这两个旧模块时会重启 AstrBot 与空闲的 B站服务；不修改记忆数据库，不重建账号。B站仍有浏览器会话时暂缓安装，先正常结束活动 / 扫码后重试。

根私有配置、动作账本和状态在 `/var/lib/p1-companion-resource`；可读摘要在目标目录 `astrbot/data/plugin_data/affect/resource_guard_health.json`。状态包含实际回收动作、限制核验、绑定失败、可用内存与近期浏览器清理回执，不包含聊天、Cookie、账号或完整进程参数。损坏账本不会自动清空来绕过重试上限。

安装前保存私有恢复点、原权限、源码、恢复清单和容器限额；失败或四分钟未提交时尝试自动恢复。原有修复源同时更新，避免巡检恢复旧协作代码。手动回滚使用安装输出的真实恢复点：

```sh
sudo python3 scripts/install_resource_guard.py --rollback /srv/p1-agent/backups/resource-guard-真实编号
```

回滚不还原数据库，不删除较新的聊天。若安装之后文件又被修改，停止自动覆盖；原配置中 `swap=0` 的默认无限额会按 Docker 更新接口恢复为等价的不限值。程序、定时器与回滚记录只在目标 Linux 中创建；不会清理 Mac / Windows 的其他应用。

## 验证层次

`tests/test_resource_guard.py` 覆盖压力、滞后、绑定、PID 复用、限额回读、会话保存失败、扫码 / 视频 / 操作保护与租约过期。可选 `tests/resource_guard_acceptance.py --run` 在无网络、无生产挂载的临时容器中实际启动 Chromium，核验压力回收后进程消失及合成 Cookie 保存，并实际更改再恢复容器限额。它不代表已经验证十年寿命或所有 OOM 场景。
