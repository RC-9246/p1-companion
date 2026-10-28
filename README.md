<a id="english"></a>

**English** · [简体中文](#chinese)

<div align="center">

# P1 Companion

### From your first QR scan to conversations that carry on

**Remember each other. Keep a rhythm of your own. Make every action traceable.**

AstrBot · QQ / OneBot · DeepSeek · MCP · Docker

**[Download the project](https://github.com/RC-9246/p1-companion/archive/refs/heads/main.zip)** · **[Get started](#quick-start)** · [Why P1 Companion](#why-p1-companion) · [Operational safeguards](#making-long-term-operation-more-manageable) · [Bring your AI assistant](#easy-handoff-to-ai-engineering-assistants)

[![Installation and resource checks](https://github.com/RC-9246/p1-companion/actions/workflows/installation-wizard.yml/badge.svg?branch=main)](https://github.com/RC-9246/p1-companion/actions/workflows/installation-wizard.yml)

</div>

P1 Companion is a self-hosted digital companion project for small deployments. It connects simulated affect, scoped memory, expression learning, group conversation context and tools in one system. The model runs in the cloud; a small host stores state, schedules activities and verifies results. The project has been deployed and checked on **RK3399 / ARM64 / 4GB RAM / Armbian**.

> **Most new engineering was completed by GPT.** Humans set goals, supplied hardware and authorization, and provided feedback. GPT, through ChatGPT / Codex, led the new design, coding, integration, troubleshooting, test orchestration and documentation. Everyday conversations use the configured DeepSeek service. Third-party frameworks and code remain the work of their respective authors. [Development attribution](AI_DEVELOPMENT.md)

The installer, QQ commands and most linked guides are currently in Chinese. This English section covers the project, setup, controls and limits; the [complete Chinese README](#chinese) follows below.

## Why P1 Companion

| Advantage | What it means in practice |
| :--- | :--- |
| **Start from a fresh machine with a guided interface** | No existing AstrBot installation required. A Chinese-language wizard prepares the environment, connects QQ and installs the components; enter your API details, scan the QR code and complete a test conversation |
| **Choose the modules you need** | 15 declared units, four profiles and dependency handling. Start, stop or remove optional service containers while retaining memory and login data; adapted maintenance recognizes intentional shutdowns |
| **Continuity in affect and expression** | A bounded, 21-dimensional simulated state, current concerns and recent conversation inform replies. Stable persona and learnable expression are separate, with room for disagreement and silence |
| **Context that outlasts a single model window** | Recent conversation, rolling group notes and relevant long-term memories are assembled for each request, supporting ongoing conversations without replaying the entire archive |
| **Separate memory for each relationship** | Spaces are derived from platform, bot, private contact, group and group member. New scopes create state on demand; access changes retain the existing memory |
| **Proactive, with room to stay quiet** | Interest-based interjections, public research, note organization and private Bilibili activities share budgets. The companion can explore, organize, rest or choose not to send a message |
| **Easy handoff between AI assistants** | Engineering guides, a machine-readable project map, a standard-library JSON CLI, an optional read-only MCP bridge and handoff templates |
| **Safeguards for ongoing operation** | Recovery for known faults, an independent repair-chain watchdog, memory-pressure load shedding, verified idle-browser cleanup and a read-only resource panel |
| **An upgrade path with a way back** | Explicit AstrBot / SnowLuma versions, network-isolated copy checks, bounded repairs and a 15-minute observation window. Failed upgrades roll back only after compatibility checks, retaining current conversation data |

The public package includes a **neutral persona and an empty sticker library**. Character-specific settings, relationship stages, real conversations, accounts, keys, login sessions and artwork from the original work are excluded. Supply your own persona and assets you have permission to use. [Persona and asset setup](docs/deployment.md#图片与人格)

## Quick start

**Download → extract → open the wizard → enter API and account details → scan → test the conversation.** The program prepares the system and connects AstrBot, SnowLuma / OneBot and Companion.

### Windows 10 / 11 x64

1. [Download the complete ZIP](https://github.com/RC-9246/p1-companion/archive/refs/heads/main.zip) and **extract it first**
2. Double-click **`开始安装.cmd`**. If a restart is requested, save your work, restart manually, then use the desktop shortcut “继续安装 P1 Companion” to resume
3. In the Chinese-language web wizard, enter your QQ number, DeepSeek API key and management password, then follow the QR login and test-chat steps

The launcher prepares a dedicated **P1Companion / Ubuntu / WSL2** environment; Docker Desktop is not required. Minimum: Windows 10 Build 19041, 8GB RAM, 20GB free on the system drive and CPU virtualization enabled. 16GB RAM is recommended. [Windows setup details](docs/installation-wizard.md#windows-10--11-x64)

### Linux / Station P1

Download and extract the complete project, then run from its directory:

```sh
sudo bash install.sh
```

Open the local URL printed by the program. Supported targets: **Ubuntu 24.04, Debian 12/13 and corresponding Armbian systems, ARM64 / x86_64**. Use a 4GB-class host with at least 1GiB available RAM and 10GiB free disk during installation. Headless hosts use an SSH tunnel. [Linux connection guide](docs/installation-wizard.md#linux--station-p1)

**After acceptance, memory protection is enabled by default and the temporary installation wizard is cleaned up.** The bot, memory, login sessions, management interfaces and recovery points remain. Windows uses a separate background entry without the wizard UI. Proactive social activity starts disabled; automatic maintenance and the resource panel can be enabled after the test chat. [Installer cleanup](docs/installation-wizard.md#安装完成自动清理向导) · [Memory protection](docs/resource-guard.md)

The wizard currently configures the official DeepSeek API and asks before a synthetic connection test that incurs normal API usage. Account registration, funding, QR login, security verification and necessary system restarts are completed by the operator. Other model providers can be configured and checked separately in AstrBot.

**The installation wizard is currently in Beta.** Linux has undergone real Compose / AstrBot SDK isolated acceptance checks. Windows has passed PowerShell 5.1 / 7 checks; the complete fresh-Windows sequence covering WSL, reboot and real-account login still needs hardware acceptance. [Requirements and verification levels](docs/installation-wizard.md)

<details>
<summary><strong>Already running AstrBot or Companion?</strong></summary>

For an existing AstrBot + SnowLuma + model setup that already chats successfully, choose the existing-AstrBot mode in the wizard, or use the retained integration entry:

```sh
python3 scripts/verify_source.py
python3 scripts/selftest.py
sudo bash deploy.sh --check
sudo bash deploy.sh --apply
```

See [existing-AstrBot integration](docs/easy-deploy.md) for the standard layout, prerequisites and rollback. The first installer refuses to overwrite an existing Companion deployment; use the relevant upgrade or patch procedure instead.

</details>

## What everyday interaction can include

- **Pick up earlier topics:** combine confirmed memory, recent interactions and real task records, retaining dates, sources, resolution and expiry
- **Learn from explicit feedback:** adopt scoped preferences such as fewer follow-up questions, listening first or getting to the point, with verbatim evidence, expiry, inspection and reversal
- **Follow group conversation:** use speakers, quotes, mentions, timing and recent topics to decide whether to join; each group has its own context
- **Explore and organize:** read public sources within authorized boundaries, record provenance, create notes, CSV, JSON or static HTML, then decide whether to share
- **Understand intentionally referenced files:** bounded parsing and OCR for common documents, with provenance, inspection results and temporary retention limits
- **Use everyday QQ expression:** short message chunks, plain text, reviewed sticker labels and repetition suppression; reactions, recalls and forwarding depend on actual adapter receipts

Bilibili has a separate private browsing space for search, sampled viewing, observation notes, private favorites and Watch Later. Public comments and bullet comments remain disabled. Sampling video frames does not establish understanding of the full video or its audio. [Tool and account boundaries](docs/boundaries.md)

## Context that continues beyond one model window

**“Near-unlimited context” describes long-running conversational continuity through external memory.** The implemented layers combine recent conversation, rolling group notes and scoped memory retrieval, instead of repeatedly sending the entire chat archive to the model.

- **Keep the current flow:** recent group messages retain speaker identity, quotes, mentions and timing
- **Carry useful context forward:** rolling group notes combine new messages with previous notes and keep evidence references for topics, corrections, preferences and unfinished matters
- **Recall what is relevant:** long-term memory and event retrieval select relevant records using local matching, freshness, confidence or source weighting, depending on the layer; deduplication and expiry checks bound what enters a request
- **Preserve scope and continuity:** persisted memory and group notes survive service restarts; private contacts and groups use separate spaces, and revoked access or clearing a space is respected

Each request still has a finite model token window and retrieval budget. Retention periods, storage limits, lossy summaries and missed retrievals apply: this is not a promise to retain every message forever or recall it verbatim. The implementation uses lightweight local retrieval, not an unlimited context-window model. [How it works and current bounds](docs/memory-spaces.md#长程上下文接续)

## What the integration adds

| Common starting point | What P1 Companion adds |
| :--- | :--- |
| **Model API + persona prompt** | Persistent simulated state, contact-scoped memory, reversible learning and continuity grounded in real events |
| **AstrBot + individually selected plugins** | Coordinated configuration, scoped permissions, proactive-send deduplication, provenance checks and budgets, reducing manual integration |
| **Workflow-first setup** | Workflows connected to ongoing conversations, relationship state and interest activities, with n8n retained as a controlled tool component |
| **Manual deployment and container restart policies** | A graphical entry point, preflight checks, builds, recovery points, rollback, memory protection and checks on the repair chain itself |

The emphasis is **coordinated integration and reproducible defaults**, built on upstream capabilities such as [AstrBot plugins and MCP](https://docs.astrbot.app/use/mcp.html) and [n8n MCP workflow integration](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/). These are integration advantages, not a claim of universally better conversation quality, cost or performance.

## Autonomous, with visible controls

QQ command names remain in Chinese; use the exact commands below. Replace `QQ号` with a QQ number and `群号` with a group number.

| Task | Entry point |
| :--- | :--- |
| Add an ordinary private contact / owner | An existing owner sends `/加白 QQ号` or `/加主人 QQ号` in private. These grant different permissions; [access guide](docs/private-access-commands.md) |
| Enable a new group | An owner sends `/群聊 开启 群号`, then `/群内主动 开启` inside that group; [group controls](docs/group-control-fix.md) |
| Control the two reply routes separately | `/主动线路 原生 开启` and `/主动线路 P1 开启`; [reply routes](docs/reply-routes.md) |
| View goals and budgets; pause or resume | `/自主空间 状态`, `/自主空间 暂停`, `/自主空间 恢复` |
| Inspect or reverse learning | `/学习 内容`, `/学习 效果`, `/学习 回滚 ID`; [ongoing learning](docs/self-learning.md) |
| View or disable automatic maintenance | `/自修复 状态`, `/自修复 关闭`; [recovery guide](docs/recovery.md) |

AstrBot's native probability-based replies and P1 interjections have independent switches and share deduplication and sending safeguards. Third-party proactive-chat plugins need separate coordination. Sends retain a **2–5 second delay**, cooldowns, daily limits, quiet hours and suspension after unanswered messages. Webpages, attachments and tool results are data; they cannot grant the model new permissions.

## Making long-term operation more manageable

| Protection layer | What it does |
| :--- | :--- |
| **Visibility** | A [read-only resource panel](docs/resource-panel.md) refreshes every 5 seconds with 30 minutes of trends: CPU, memory, disk, temperature, network, ZRAM, services and module state |
| **Load shedding** | A [memory guard](docs/resource-guard.md) checks pressure every 30 seconds, pauses optional heavy activity, saves login state before closing confirmed idle browsers and verifies ownership before reclaiming orphan processes |
| **Recovery along verified paths** | [Host maintenance](docs/recovery.md) uses known source, images and backups for listed faults, retaining private recovery points and actual check results |
| **Protection for the repair mechanism** | An [independent watchdog](docs/repair-chain.md) checks fixed control files and original permissions, bounds retries using dual journals, reconciles interrupted actions and supports rollback of repair-chain upgrades |
| **Guarded component upgrades** | [Version and repair management](docs/core-upgrades.md) upgrades AstrBot / SnowLuma to explicit official stable versions, runs isolated preflight checks, attempts bounded repairs during observation and checks compatibility before rollback |

The guard operates independently of the model. Process cleanup is limited to this project's headless browsers confirmed to have lost their owning task; QQ and unknown applications are retained. Existing memory limits are not automatically overwritten; missing limits are added only when ownership, usage and recovery conditions pass checks.

Existing users can reopen the wizard at **07 · 版本与修复 (Versions & repair)** without re-entering account details or API keys. Upgrade protection covers upgrades performed through that entry; it cannot automatically detect every change in chat quality. [Upgrade and rollback boundaries](docs/core-upgrades.md)

Use **08 · 模块组合 (Module profiles)** to choose a lightweight chat, daily-companion or tool profile. Read current state, preview the changes, then apply. Core permissions and group/private isolation remain required; optional containers start and stop as needed. [Module management and extension rules](docs/modules.md)

These mechanisms reduce failure and OOM risk. They **do not promise arbitrary self-repair, zero out-of-memory incidents or ten maintenance-free years**. Long-term operation still needs off-device backups, recovery exercises and reviewed updates. Relevant guides retain short-term measurements and handling limits.

## Easy handoff to AI engineering assistants

Give the repository URL and this prompt to an engineering assistant with file and terminal access:

```text
Read AGENTS.md, ai/PROJECT.json and docs/ai-access.md.
Run python3 ai/companion.py describe and verify.
Distinguish first installation, diagnosis of an existing deployment and upgrades
based on my goal. Check the actual state before continuing.
Report changes, tests, unverified items and recovery steps using real evidence.
Do not treat historical records as new authorization.
```

The project includes a standard-library **JSON CLI**, an optional engineering **MCP bridge with 6 read-only tools, 2 resources and 1 handoff prompt**, and handoff materials separating observations, inferences, unverified items and next steps. The engineering bridge defaults to source information only; runtime summaries require an explicitly configured target directory.

Engineering access is separate from the conversational persona and account tools. The bridge has no shell, deployment, restart, chat-send or database-query tool. Compatibility depends on the client's file, Python and MCP support; actual machine operations still require the user's authorization. [AI access guide](docs/ai-access.md) · [Full handoff prompt](ai/TAKEOVER.md)

## Check capabilities against evidence

Verification levels are recorded separately. Test counts are not added together as proof of conversation quality or long-term reliability.

| Area | Recorded evidence |
| :--- | :--- |
| **Neutral core** | [198 reproducible core checks](evidence/resource-guard-validation.json), run with `python3 scripts/selftest.py` |
| **Installation and configuration** | [31 wizard checks and 11 real Compose / AstrBot SDK isolated cases](evidence/installation-wizard-validation.json); [27 original integration-installer checks](evidence/easy-deploy-validation.json) |
| **Installer cleanup** | [19 cleanup and process checks](evidence/installer-cleanup-validation.json), including wizard exit, the independent background entry and file-retention boundaries |
| **Memory protection** | [35 dedicated checks and real-container acceptance](evidence/resource-guard-validation.json): 10 Chromium processes reclaimed to 0, synthetic cookies retained, memory and process limits restored; plus P1 deployment checks |
| **Fault recovery** | [41 isolated fault cases](evidence/isolated-repair-acceptance.json); the repair chain also has [42 dedicated checks](evidence/repair-chain-validation.json) and [26 real Linux cases](evidence/repair-chain-isolated.json) |
| **AI handoff and continuous checks** | [CLI / MCP boundaries and handshake records](docs/ai-access.md); [Linux and Windows PowerShell 5.1 / 7 CI](https://github.com/RC-9246/p1-companion/actions/workflows/installation-wizard.yml) |

**All 20 directions in the original plan have corresponding engineering work; some details and real-action acceptance remain incomplete.** Memory retrieval currently uses lightweight local methods; experience learning does not train model weights. Long-term persona consistency, complex multi-speaker groups and autonomous repair of unknown logic faults still need further validation. [Item-by-item audit and known gaps](docs/twenty-item-audit.md) · [Acceptance report](docs/release-report.md)

## Documentation

Most detailed guides linked below are currently in Chinese.

| Topic | Start here |
| :--- | :--- |
| Installation and customization | [Graphical installation](docs/installation-wizard.md) · [Existing AstrBot integration](docs/easy-deploy.md) · [Deployment, persona and assets](docs/deployment.md) |
| Affect, memory and learning | [Affect design](docs/emotion-design.md) · [Independent memory spaces](docs/memory-spaces.md) · [Ongoing learning](docs/self-learning.md) · [Conversational continuity](docs/self-response.md) |
| Groups and QQ controls | [Controls](docs/controls.md) · [Group controls](docs/group-control-fix.md) · [Proactive reply routes](docs/reply-routes.md) · [Latency](docs/group-latency.md) · [Image input](docs/group-image-fix.md) |
| Operations and recovery | [Memory protection](docs/resource-guard.md) · [Resource panel](docs/resource-panel.md) · [Recovery](docs/recovery.md) · [Repair chain](docs/repair-chain.md) |
| AI handoff and engineering | [AI access](docs/ai-access.md) · [Engineering guide](AGENTS.md) · [Implementation history](docs/development-history.md) · [Development attribution](AI_DEVELOPMENT.md) |
| Progress and future directions | [Feature matrix](docs/feature-matrix.md) · [Item-by-item audit](docs/twenty-item-audit.md) · [Further capabilities](docs/further-capabilities.md) |

<details>
<summary><strong>Project layout</strong></summary>

```text
开始安装.cmd / install.sh   Graphical installer for a fresh host
deploy.sh                  Integration entry for an existing AstrBot setup
release/                   Eight plugins: affect, memory, learning, groups, expression
browser/                   Public-source browser and access policies
services/                  Bilibili, workbench, MCP, maintenance, memory guard, monitor
AGENTS.md / ai/             Engineering guide, project map, read-only APIs, handoff
deploy/ / scripts/         Install coordination, source verification, recovery, upgrades
tests/ / evidence/         Layered acceptance code and redacted results
docs/                      Design, deployment, controls, troubleshooting and limits
```

</details>

## Scope and attribution

Designed for small allowlisted private-chat deployments, a few groups and low-frequency research activities. Heavy browsing, parsing and experiments have concurrency limits. Splitting cloud inference from local state does not mean a 4GB host can run every task at full load simultaneously. “Emotion,” “autonomy” and “learning” describe software mechanisms; they are not evidence of subjective experience. [Full boundaries](docs/boundaries.md)

Operators remain responsible for model usage, account risks, participant privacy, backups and third-party permissions. This is an independent community project, with no official endorsement from OpenAI, DeepSeek, Tencent, Bilibili or the original work's rights holders. Third-party licenses are listed individually in the provenance guide. Memoria's upstream license has not yet been confirmed; obtain appropriate permission or exclude that code before redistribution. A disclaimer does not supply missing permission.

**[Full disclaimer and terms of use](DISCLAIMER.md)** · [Development attribution](AI_DEVELOPMENT.md) · [Third-party provenance and licenses](PROVENANCE.md)

---

<a id="chinese"></a>

[English](#english) · **简体中文**

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
| **长程上下文，跨窗口接续** | 近期对话、滚动群笔记与相关长期记忆按需组装；不必每轮重放全部历史，也能接续先前话题与共同经历 |
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

## 把上下文延续到单次窗口之外

**这里的“近乎无限上下文”，指通过外部记忆实现可持续的长程对话接续。** 已实现的近期对话、滚动群笔记和分范围记忆检索共同参与每轮生成，不要求把全部聊天历史反复塞进模型。

- **接住眼前节奏**：近期群消息保留发言人、引用、@ 与时间关系，知道当前在接谁的话
- **把有用内容带到后面**：滚动群笔记结合新消息与旧笔记，保留话题、纠正、偏好和未完成事项，并绑定来源证据
- **需要时再想起**：长期记忆和事件检索按各层的本地匹配、新近度、置信度或来源权重筛选，结合去重与有效期控制注入体积
- **重启后接续、不同对象分开**：已落盘的记忆和群笔记可跨服务重启保留；私聊与各群独立检索，撤销授权和清空仍然有效

每次请求仍受模型 token 窗口、检索预算、保存期限和存储容量约束；摘要可能遗漏、检索可能漏召回，**不保证全部历史逐字永久记住**。当前使用本地轻量检索，不能把长程接续写成模型本身拥有无限上下文窗口。[实现方式与当前边界](docs/memory-spaces.md#长程上下文接续)

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
