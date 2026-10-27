# 让不同 AI 快速接手：指南、JSON CLI 与只读 MCP

[← 返回项目首页](../README.md)

这套接入包帮助工程助手理解、检查和接续项目。支持读文件与运行 Python 的助手可使用标准库 CLI；支持 MCP 的客户端可接入可选的只读工具。它不绑定模型供应商，不要求把机器人改成另一种模型，也不随仓库提供 SSH、模型账号或登录态。

## 最快的交接方式

把仓库地址和下面一句话交给你的 AI：

> 阅读 AGENTS.md、ai/PROJECT.json 和 docs/ai-access.md，运行 python3 ai/companion.py describe 与 verify；先区分新安装、现有部署诊断或代码修改，再按我的具体目标继续。只报告有证据的连接、测试和完成结果。

需要完整上下文时使用 [可复制的接手提示](../ai/TAKEOVER.md)。`AGENTS.md` 是工程协作指南，不是沙季或其他角色的人格提示，不会修改陪伴系统的表达设定。不能运行命令的模型也能阅读文档，但不能据此声称已检查机器。

## 无额外依赖的 JSON 入口

在仓库根目录执行，Python 3.11+ 即可：

```sh
python3 ai/companion.py describe
python3 ai/companion.py verify
python3 ai/companion.py plan --root /srv/p1-agent
python3 ai/companion.py handoff
```

| 命令 | 给 AI 的信息 | 实际边界 |
| --- | --- | --- |
| `describe` | 入口文件、架构、支持条件、验收层次、已知缺口 | 仅读公开清单，不连接机器 |
| `verify` | 源码哈希检查结果与清单标识 | 不证明发布者身份，不等于部署成功 |
| `plan` | 可复用 argv 数组、阶段和验收条件 | 只返回计划，不执行安装命令 |
| `handoff` | 区分观察、推断、未验证和下一步的模板 | 初始状态为未开始，不伪造完成记录 |
| `doctor --root 目标目录` | 调用原安装器的只读预检，返回白名单错误码 | 不安装、不提权，不返回原配置或原始日志 |
| `status --root 目标目录` | 从固定本机状态文件提取模块、维护、服务、数据库摘要 | 不读取聊天、数据库或账号信息；不是实时容器探针 |

后两项只对实际获准的本机目标使用；不会自动 SSH，也不会接管其他设备。`status` 的 `ok` 表示状态文件可读取，不表示所有服务都健康。启动报告与定期维护分别标明时间；维护超过 15 分钟、缺少有效时间或时钟异常时，服务与数据库状态返回 unknown（JSON null）。容器状态不能证明账号在线或消息送达。

`status` 另提供 `recovery_chain`：从固定看门狗报告提取状态码、待验收标记、修复文件数和滚动尝试数，超过 20 分钟返回 unknown。没有新增写入或部署工具；恢复引擎通过验收不等于所有应用均健康。[恢复链说明](repair-chain.md)

需要既有服务器只读状态时，例如：

```sh
python3 ai/companion.py status --root /srv/p1-agent
python3 ai/companion.py doctor --root /srv/p1-agent
```

预检在现有 Companion 上报告拒绝首次安装是预期行为。继续诊断或授权补丁流程，不反复尝试 `--apply`。

## 可选：给 MCP 客户端六个只读工程工具

CLI 不需要 MCP。确实需要宿主工具接入时，建议在专用虚拟环境安装与本仓库一致的 SDK：

```sh
python3 -m venv runtime/ai-venv
runtime/ai-venv/bin/python -m pip install -r ai/requirements-mcp.txt
runtime/ai-venv/bin/python ai/companion.py mcp-config
```

最后一条命令输出使用当前解释器和本仓库绝对路径的配置片段，**不修改任何客户端设置**。按你的 MCP 客户端要求粘贴、合并；不要覆盖已有工具。通用结构见 [mcp.example.json](../ai/mcp.example.json)。生成结果包含你的本机路径，保留在本机，不作为公开项目素材上传。

默认只接入源码信息。需读取本机运行摘要时，由操作者配置固定目录：

```sh
runtime/ai-venv/bin/python ai/companion.py mcp-config --live-root /srv/p1-agent
```

`--live-root` 固定在服务启动参数中；模型不能在工具调用时换目录。移除该参数即可关闭运行摘要与预检入口，断开客户端即可停止此 stdio 服务。没有新增 HTTP、公网端口、SSH 密钥或账号权限，不自动提权。摘要的可读性仍取决于运行服务的 OS 账号；不要为此给客户端添加任意 sudo 权限。

| MCP 工具 | 功能 |
| --- | --- |
| `p1_project_overview` | 公开项目概况与接手入口 |
| `p1_verify_source` | 源码清单核对 |
| `p1_deployment_plan` | 生成部署步骤，不执行 |
| `p1_deployment_check` | 固定目标的只读预检，默认不可用 |
| `p1_runtime_health` | 固定目标的白名单运行摘要，默认不可用 |
| `p1_handoff_template` | 生成中性交接模板 |

另提供两个公开 resource 和一个接手 prompt。没有 Shell、任意文件读取、配置写入、部署、重启、聊天发送、数据库查询、B站或账号操作工具。

`readOnlyHint` 是客户端提示，不是权限隔离。本桥通过封闭操作与固定路径限制实际能力；若外部助手本来就拥有终端，其独立终端权限仍由宿主与用户管理，不能认为 `AGENTS.md` 将它沙箱化了。MCP 工具返回的数据可能被客户端发送给所选模型；启用运行摘要前应确认该客户端的数据目的地。这里的测试只使用公开源代码与合成状态，不向新模型服务发送真实运行数据。

本桥固定测试 `mcp==1.30.0` 的 stdio 路线，SDK 2.x 的导入/API 已变化，不直接混装进同一环境。协议与客户端兼容性应实际握手核验；不承诺所有客户端版本。[官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk) · [SDK 迁移说明](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md)

## 与原有聊天机器人 MCP 的关系

| 接入层 | 入口 | 负责什么 |
| --- | --- | --- |
| 工程助手接入 | `ai/mcp_server.py`，6 个工具 | 理解源码、计划、只读预检、受限运行摘要与交接 |
| Companion 运行工具 | `services/mcp/server.py`，原有 9 个工具 | 在 AstrBot 原有服务上下文中使用公开搜索、浏览、受控工作流和隔离实验 |

工程桥不会把原有九个工具重新暴露给外部助手，也不会冒充 QQ 私聊/群身份。对会话资料和账号行为的授权仍由原运行系统处理。浏览器、群聊或任务文本不能借新接口获得额外权限。

## 可核验的交接

`ai/handoff.schema.json` 提供通用 JSON 结构。助手填写具体目标、阶段、已观察结果、证据、测试层次、未完成项和限制。不传递内部思考过程，也不把一次源码核验写成真实 QQ 投递成功。模板默认不包含生产数据。

JSON schema 约束结构，不能自动识别所有敏感信息；公开交接前仍须删除真实账号、密钥、登录信息、私聊和私有恢复点。涉及用户私密业务的目标本身也不应直接放进公开 issue。

## AI 修改源码后的维护顺序

接入包不会替外部助手自动修改代码或清单。若实际任务已授权源码修改，先准备恢复点、审阅差异、运行与改动相关的测试，再更新分发清单。源码改动后 `verify` 暂时失败表示检测到了差异，不应先重写哈希掩盖它。

`source-manifest.json` 是“仓库相对文件路径 → UTF-8 源文件原始字节 SHA-256”的映射，不包含清单本身。维护时使用原清单路径集合，逐项加入经过审阅的新源码，移除已确认删除的源码；不要自动收集未跟踪的目录。禁止加入运行目录、虚拟环境、备份、数据库、账号配置、真实日志和私密交接。按路径排序后重新计算、原子替换 JSON，再运行 `python3 scripts/verify_source.py`。刷新清单只记录新的源文件基线，不证明代码安全、测试通过或发布者身份。

如果交付压缩包，由交付方同时重建包与对应清单，重新检查去敏结果。该步骤与生产部署、账号授权、恢复检查点封存分别处理；没有新的运行验收就不把源码变化描述成已经部署。

## 验证

```sh
python3 -m unittest discover -s tests -p test_ai_access.py
# 可选 SDK 环境中，真实 stdio 握手；仅公开源码、合成状态
runtime/ai-venv/bin/python tests/ai_access_mcp_handshake.py
```

检查涵盖默认不读运行数据、固定根路径、非法/过大/符号链接文件拒绝、字段去敏、过期状态、源码篡改、只读预检参数、计划不执行及交接结构。本次 25 项专项已在 macOS 与 Linux ARM64 通过；使用 mcp==1.30.0 实际核验六个工具、两个资源、一个 prompt、默认拒绝运行数据及合成目标的字段过滤。另在 P1 上用 CLI 核验只读状态摘要和既有安装拒绝，生产 135 个插件文件保持原样。真实 MCP 握手与真实生产状态检查分别记录，不互相替代；结果见 `evidence/ai-access-validation.json`。

后续恢复链版本增加三个状态摘要回归，共 28 项 AI 接入离线测试，已在 macOS 与 Linux ARM64 通过；本次新增状态字段不会改变原 MCP 的工具数量、参数或权限。[恢复链版本验证](../evidence/repair-chain-validation.json)
