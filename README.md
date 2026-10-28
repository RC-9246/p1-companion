<div align="center">

<picture>
  <source media="(max-width: 640px)" srcset="assets/readme-cover-mobile.svg">
  <img src="assets/readme-cover.svg" alt="P1 Companion：从零安装，让对话有延续，让自主有边界" width="100%">
</picture>

### 从第一次扫码，到有延续的相处

**记住彼此，保留自己的节奏，也让每一次行动有据可查**

AstrBot · QQ / OneBot · DeepSeek · MCP · Docker

**[下载完整项目](https://github.com/RC-9246/p1-companion/archive/refs/heads/main.zip)** · **[开始安装](#快速开始)** · [项目优势](#为什么选择-p1-companion) · [运行保护](#让长期运行更可控) · [交给你的 AI](#方便-ai-接手与协作)

[![安装与资源检查](https://github.com/RC-9246/p1-companion/actions/workflows/installation-wizard.yml/badge.svg?branch=main)](https://github.com/RC-9246/p1-companion/actions/workflows/installation-wizard.yml)

</div>

P1 Companion 是一套面向小规模自托管的数字伙伴工程：把模拟情绪、独立记忆、表达学习、群聊节奏和工具执行接到同一条链路。模型在云端推理，小主机保存状态、调度活动并核验结果；已在 **RK3399 / ARM64 / 4GB / Armbian** 上部署验证。

> **新增工程主要由 GPT 完成。** 人类提出目标、提供设备与授权、反馈体验；GPT 通过 ChatGPT / Codex 主导新增设计、编码、集成、排障、测试编排与文档。日常对话使用已配置的 DeepSeek，第三方框架与代码归相应作者。[开发来源](AI_DEVELOPMENT.md)

## 为什么选择 P1 Companion

| 优势 | 在项目里意味着什么 |
| :--- | :--- |
| **从零开始，跟着界面安装** | 不必预装 AstrBot。中文向导准备环境、连接 QQ、安装组件；填写 API、扫码、试聊后完成 |
| **功能模块，按需组合** | 15 个声明单元、四种模板、依赖联动；可选服务启停或移除，保留记忆与登录数据，已适配巡检不会把停用当故障 |
| **情绪与表达有延续** | 21 维有界模拟状态、当前关切和近期对话共同参与生成；稳定人格与可学习表达分开，允许不同意见与留白 |
| **每段关系，独立保存** | 按平台、机器人、私聊对象、群及群成员派生空间；新增范围按需建状态，权限变化沿用原记忆 |
| **能主动，也懂得停下** | 兴趣插话、公开研究、资料整理和私人 B站活动接入预算；可以选择探索、整理、休息或不发消息 |
| **方便不同 AI 接手** | 工程指南、机器清单、标准库 JSON CLI、可选只读 MCP 桥和交接模板一起提供 |
| **给持续运行补上保护** | 已知故障恢复、修复链看门狗、内存压力降载、确认空闲后的浏览器回收，以及只读资源面板 |
| **升级也留好退路** | AstrBot / SnowLuma 具体版本升级、无外网副本预检、有限修复与 15 分钟观察；失败验证后退回旧程序，保留当前聊天数据 |

公开包包含 **中性人格与空图库**。角色设定、关系阶段、真实聊天、账号、密钥、登录状态和原作图片不随源码分发；你可以加入自己的角色配置及有权使用的素材。[人格与素材配置](docs/deployment.md#图片与人格)

## 快速开始

**下载 → 解压 → 打开向导 → 填写 API 与账号 → 扫码 → 试聊验收。** 系统准备、AstrBot、SnowLuma / OneBot 和 Companion 的接线由程序完成。

### Windows 10 / 11 x64

1. [下载完整 ZIP](https://github.com/RC-9246/p1-companion/archive/refs/heads/main.zip)，**先解压**
2. 双击 **`开始安装.cmd`**；若提示重启，保存工作后手动重启，再点桌面上的“继续安装 P1 Companion”
3. 在自动打开的中文网页里填写 QQ 号、DeepSeek API Key、管理密码，再按步骤扫码与试聊

程序准备独立的 **P1Companion / Ubuntu / WSL2** 环境，无需 Docker Desktop。最低 Windows 10 Build 19041，8GB 内存、系统盘 20GB 可用空间；推荐 16GB，CPU 虚拟化需开启。[Windows 安装详情](docs/installation-wizard.md#windows-10--11-x64)

### Linux / Station P1

下载并解压完整项目，在项目目录执行：

```sh
sudo bash install.sh
```

打开程序给出的本机链接。支持 **Ubuntu 24.04、Debian 12/13 及对应 Armbian，ARM64 / x86_64**；4GB 档内存，安装时至少 1GiB 可用内存与 10GiB 可用磁盘。无桌面设备通过 SSH 隧道访问。[Linux 连接方法](docs/installation-wizard.md#linux--station-p1)

**完成后默认开启内存保护、清理临时安装向导。** 机器人、记忆、登录状态、管理页和恢复点保留；Windows 使用独立的无界面后台入口。主动社交默认关闭，自动维护和资源面板可在试聊后按需启用。[安装收尾](docs/installation-wizard.md#安装完成自动清理向导) · [内存保护](docs/resource-guard.md)

向导当前自动配置 DeepSeek 官方接口，并提示合成连接测试及其正常用量。账号注册、充值、扫码、安全验证与必要的系统重启由本人完成；其他模型供应商可在 AstrBot 中另行配置和验收。

**当前为安装向导 Beta。** Linux 已做真实 Compose / AstrBot SDK 隔离验收，Windows 已通过 PowerShell 5.1 / 7 检查；全新 Windows 的 WSL、重启与实号登录全流程仍待实机验收。[支持条件与验证层次](docs/installation-wizard.md)

<details>
<summary><strong>已经有 AstrBot，或已经安装过 Companion？</strong></summary>

已有能正常聊天的 AstrBot + SnowLuma + 模型，可在向导选择“已有 AstrBot”，或使用保留的集成入口：

```sh
python3 scripts/verify_source.py
python3 scripts/selftest.py
sudo bash deploy.sh --check
sudo bash deploy.sh --apply
```

标准布局、先决条件与回滚见 [已有 AstrBot 集成](docs/easy-deploy.md)。已有 Companion 会拒绝被首次安装器覆盖；继续使用对应的升级或补丁流程。

</details>

## 日常相处，可以有哪些变化

- **接续旧话题**：结合经确认的记忆、近期互动和真实任务记录，保留日期、来源、解决与过期状态
- **从明确反馈调整表达**：学会限定范围的“少追问、先听、讲重点”等偏好，保留逐字证据、有效期、查看与撤销入口
- **理解群聊节奏**：结合发言人、引用、@、间隔与近期话题选择是否接话；各群使用独立上下文
- **自己探索与整理**：在获准范围内读公开资料、记录来源，生成笔记、CSV、JSON 或静态 HTML，再决定是否分享
- **理解有意提及的文件**：有界解析常见文档与 OCR，保留来源、检查结果与临时期限
- **使用日常 QQ 的表达方式**：短句分段、纯文本输出、审核表情标签与重复抑制；表态、撤回和转发依据适配器真实回执

B站使用独立私人浏览空间，可搜索、采样观看、整理观察笔记、私密收藏及稍后再看；公开评论、弹幕等仍禁用。视频画面采样不等于理解完整视频或音频。[工具与账号边界](docs/boundaries.md)

## 相比常见方案，整合在哪里

| 常见起点 | P1 Companion 补上的部分 |
| :--- | :--- |
| **模型 API + 人格提示词** | 持久模拟状态、按对象隔离的记忆、可撤销学习，以及依据真实事件接续的互动 |
| **AstrBot + 自选插件** | 配套配置、范围权限、主动发送去重、来源校验和预算保护，减少逐个接线的工作 |
| **工作流优先的搭建** | 将工作流接入持续的对话、关系状态与兴趣活动，保留 n8n 作为受控工具组件 |
| **手工部署与容器 restart** | 图形入口、预检、构建、恢复点、失败回滚、内存保护，以及对修复链本身的检查 |

优势集中在 **配套整合与可复现默认值**，建立在 [AstrBot 的插件与 MCP](https://docs.astrbot.app/use/mcp.html)、[n8n 的 MCP 工作流接入](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/) 等上游能力之上。这里描述整合重点，不代表聊天效果、成本或性能全面优于其他方案。

## 自主，但始终可控

| 要做什么 | 入口 |
| :--- | :--- |
| 添加普通私聊 / 主人 | 现有主人私聊 `/加白 QQ号` 或 `/加主人 QQ号`；权限不同，[接入说明](docs/private-access-commands.md) |
| 启用一个新群 | 主人 `/群聊 开启 群号`；再在本群 `/群内主动 开启`，[群控制](docs/group-control-fix.md) |
| 分开两种接话方式 | `/主动线路 原生 开启`、`/主动线路 P1 开启`，[线路说明](docs/reply-routes.md) |
| 看目标与额度，暂停或恢复活动 | `/自主空间 状态`、`/自主空间 暂停`、`/自主空间 恢复` |
| 查看或撤销学习 | `/学习 内容`、`/学习 效果`、`/学习 回滚 ID`，[持续学习](docs/self-learning.md) |
| 查看或关闭自动维护 | `/自修复 状态`、`/自修复 关闭`，[恢复手册](docs/recovery.md) |

原生概率接话与 P1 插话可分别开关，共用发送去重和保护；第三方主动聊天插件需另行协调。发送保留 **2–5 秒延迟**、冷却、每日额度、免打扰和无人回复暂停。网页、附件与工具结果作为资料处理，不能赋予模型新权限。

## 让长期运行更可控

| 保护层 | 实际做什么 |
| :--- | :--- |
| **看得见** | [只读资源面板](docs/resource-panel.md) 每 5 秒更新，保留 30 分钟趋势；查看 CPU、内存、磁盘、温度、网络、ZRAM、服务与模块状态 |
| **及时降载** | [内存守护](docs/resource-guard.md) 每 30 秒检查压力；暂停可选重型活动，保存登录后关闭确认空闲的浏览器，严格核验后回收孤儿进程 |
| **按验证过的路径恢复** | [宿主维护](docs/recovery.md) 从已知源码、镜像和备份恢复列举的故障，保留私有恢复点与真实检查结果 |
| **保护修复机制本身** | [独立看门狗](docs/repair-chain.md) 检查固定控制文件及原权限；双份账本限制重试，中断后核对回执，升级失败可回滚 |
| **保护组件升级** | [版本与修复](docs/core-upgrades.md) 从官方具体稳定版升级 AstrBot / SnowLuma；隔离预检、观察期修复、严重失败回滚，迁移或兼容性未通过时拦截 |

守护独立于模型，回收范围限于确认失去所属任务的本项目无头浏览器，保留 QQ 和未知应用。已有内存限额不会被自动覆盖；缺失限额仅在归属、用量与恢复条件符合时补上。

已安装用户重新打开向导，选择 **07 · 版本与修复**，无需重填账号与 Key。升级保护只覆盖通过该入口执行的升级，不自动识别所有聊天质量变化；[操作与回滚边界](docs/core-upgrades.md)。

选择 **08 · 模块组合**，可切换轻量聊天、日常陪伴或工具组合；先读现状，再预览并应用。核心权限与群私隔离必需，可选容器按需启停；[模块管理与扩展规范](docs/modules.md)。

这些机制降低故障和 OOM 风险，**不承诺任意错误自愈、零内存溢出或十年免维护**。长期运行仍需要离机备份、恢复演练与受审更新。短期性能样本及处理边界在对应文档中保留。

## 方便 AI 接手与协作

可以把仓库地址和下面这段话直接交给有文件、终端能力的工程助手：

```text
阅读 AGENTS.md、ai/PROJECT.json 和 docs/ai-access.md。
运行 python3 ai/companion.py describe 与 verify。
根据我的目标区分首次安装、现有部署诊断或升级，先核对实际状态，再继续工作。
用真实证据说明改动、测试、未验证项与恢复方法，不把历史记录当作新授权。
```

提供标准库 **JSON CLI**、可选工程 **MCP 桥（6 个只读工具、2 个 resource、1 个接手 prompt）**，以及区分观察、推断、未验证和下一步的交接资料。工程桥默认仅源码信息，运行摘要需显式配置目标目录。

工程接入与日常聊天人格、账号工具分开，没有 Shell、部署、重启、聊天发送或数据库查询工具。兼容性取决于客户端的文件、Python 和 MCP 支持；实际机器操作仍依据用户授权。[AI 接入指南](docs/ai-access.md) · [完整交接提示](ai/TAKEOVER.md)

## 用实际证据核对能力

不同层次分别记录，不将测试总数相加当作效果或长期稳定性的保证。

| 验证项目 | 已有记录 |
| :--- | :--- |
| **中性核心** | [198 项可复现核心检查](evidence/resource-guard-validation.json)，入口 `python3 scripts/selftest.py` |
| **安装与配置** | [31 项向导检查、11 项真实 Compose / AstrBot SDK 隔离验收](evidence/installation-wizard-validation.json)；[27 项原集成安装器专项](evidence/easy-deploy-validation.json) |
| **安装收尾** | [19 项清理与进程检查](evidence/installer-cleanup-validation.json)，包含向导退出、独立后台与文件保留边界 |
| **内存保护** | [35 项专项及真实容器验收](evidence/resource-guard-validation.json)：10 个 Chromium 进程回收到 0、合成 Cookie 保留、内存及进程数限额恢复；另有 P1 部署核验 |
| **故障恢复** | [41 项隔离故障验收](evidence/isolated-repair-acceptance.json)；恢复链另有 [42 项专项](evidence/repair-chain-validation.json) 与 [26 项真实 Linux 验收](evidence/repair-chain-isolated.json) |
| **AI 协作与持续检查** | [CLI / MCP 边界与握手记录](docs/ai-access.md)；[Linux 与 Windows PowerShell 5.1 / 7 CI](https://github.com/RC-9246/p1-companion/actions/workflows/installation-wizard.yml) |

**原计划 20 个方向均有工程对应，部分细节和真实动作验收仍待补齐。** 当前记忆检索使用本地轻量方法；经验学习不训练模型权重；长期角色一致性、复杂多人群表现与未知逻辑错误的自主修复仍需持续验证。[逐项审计与已知缺口](docs/twenty-item-audit.md) · [验收报告](docs/release-report.md)

## 文档导航

| 想了解 | 从这里开始 |
| :--- | :--- |
| 安装与定制 | [图形安装](docs/installation-wizard.md) · [已有 AstrBot 集成](docs/easy-deploy.md) · [部署与人格素材](docs/deployment.md) |
| 情绪、记忆与学习 | [情绪设计](docs/emotion-design.md) · [独立记忆空间](docs/memory-spaces.md) · [持续学习](docs/self-learning.md) · [连续表达](docs/self-response.md) |
| 群聊与 QQ 控制 | [控制总览](docs/controls.md) · [群控制](docs/group-control-fix.md) · [主动线路](docs/reply-routes.md) · [延迟优化](docs/group-latency.md) · [图片输入](docs/group-image-fix.md) |
| 运行与恢复 | [内存保护](docs/resource-guard.md) · [实时面板](docs/resource-panel.md) · [恢复手册](docs/recovery.md) · [修复链](docs/repair-chain.md) |
| AI 协作与工程过程 | [AI 接入](docs/ai-access.md) · [工程指南](AGENTS.md) · [实施过程](docs/development-history.md) · [开发来源](AI_DEVELOPMENT.md) |
| 功能进度与后续方向 | [功能矩阵](docs/feature-matrix.md) · [逐项审计](docs/twenty-item-audit.md) · [后续能力](docs/further-capabilities.md) |

<details>
<summary><strong>项目结构</strong></summary>

```text
开始安装.cmd / install.sh   从空白设备打开图形安装向导
部署入口 deploy.sh         已有 AstrBot 的集成入口
release/                   八个插件：情绪、记忆、学习、群聊与表达
browser/                   公开资料浏览器与访问策略
services/                  B站、工作台、MCP、维护、内存守护与资源面板
AGENTS.md / ai/            工程指南、机器清单、只读接口与交接资料
deploy/ / scripts/         安装协调、源码核验、检查点与升级恢复
tests/ / evidence/         分层验收代码与去敏结果
docs/                      设计、部署、控制、排障与适用边界
```

</details>

## 适用范围与来源

适合小规模白名单私聊、少量群聊和低频资料活动。重浏览、解析与实验限制并发；云端推理与本地状态分工，不代表 4GB 设备能同时满载所有任务。这里的“情绪”“自主”“学习”指软件机制，不代表已证实的主观情感。[完整适用边界](docs/boundaries.md)

部署者需要管理模型用量、账号风险、参与者隐私、备份与第三方授权。本项目是独立社区工程，无 OpenAI、DeepSeek、腾讯、哔哩哔哩或作品权利人的官方背书。第三方许可逐项列于来源文档；Memoria 上游许可尚未确认，再分发前应取得适当许可或排除相关代码。免责声明不能补足缺失授权。

**[完整免责声明与使用条款](DISCLAIMER.md)** · [开发来源](AI_DEVELOPMENT.md) · [第三方归属与许可](PROVENANCE.md)
