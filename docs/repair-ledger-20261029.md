# v0.21 修复对照与未证实项

这份清单对照 2026-10-28 的交接审计。部分项目是此前尚未触发的代码风险；“修复”不表示正式账号曾发生过相应事故。部署状态与五轮结果见 [验收报告](verification-results-20261029.md)，功能边界见 [设计对照](design-verification-20261029.md)。

## 42 项原审计

| 编号 | 修复内容 | 主要复现与回归入口 |
|---|---|---|
| L1 | 恢复文件使用持有目录描述符和不可跟随链接的随机临时文件 | test_audit_lifecycle.py / test_resilience.py |
| L2 | 确认容器身份和确实停止后才允许数据库恢复 | test_audit_lifecycle.py |
| L3 | 回滚先写持久阶段，中断后继续；不残留成功状态 | test_audit_lifecycle.py / test_core_updater.py |
| L4 | 健康探针接纳本实例新鲜 ready/serving 报告 | test_audit_lifecycle.py |
| L5 | 升级/模块工具识别已提交且形状受限的安装 Compose 覆盖层 | test_audit_installation.py；未做 Windows 空系统完整实装 |
| L6 | 升级、模块和维护共用生命周期锁 | test_audit_lifecycle.py / test_audit_installation.py |
| L7 | 旧进程或过期健康文件不能作为恢复成功证明 | test_audit_lifecycle.py |
| L8 | 模块失败回滚保留原来的停止状态 | test_audit_lifecycle.py |
| L9 | 安装恢复保存逐文件阶段；中断后重入；文件所有权与权限保留 | test_rollout.py |
| M1 | 后台记忆提炼前后都重查活跃绑定和授权 | integration_memoria.py / test_audit_scopes.py |
| M2 | 私聊清空覆盖三个历史 owner；独立清空水位在旧备份恢复后重放 | test_audit_scopes.py / integration_audit_contracts.py |
| M3 | 在途记忆写入在事务中核对清空代次 | test_audit_scopes.py / integration_memoria.py |
| M4 | 群清空使 QQ 缓存和派生摘要失效 | test_audit_scopes.py |
| M5 | 群历史导入和缓存写入绑定开始时的代次 | test_audit_scopes.py / integration_group_images.py |
| M6 | 候选记忆查看/确认/拒绝覆盖当前范围的 session 与用户空间 | integration_memoria.py |
| M7 | 转发与引用保留来源；他人的话不能成为当前用户经历 | integration_media_grounding.py / integration_scope_matrix.py |
| M8 | 表情关闭在选择及发送时都生效 | test_reactions.py / test_audit_scopes.py |
| M9 | 先检索全范围再取最高分结果，取消300条预截断盲区 | test_audit_scopes.py |
| M10 | 普通与主动读取共用日期、衰减和更正规则 | test_audit_scopes.py |
| U1 | 独立监控面板缺少可选维护助手时给出未知状态 | test_installation_edges.py（独立缺少可选助手；已有项目备份目录） |
| U2 | GUI 清理有剩余文件时保留管理标记 | test_installer_cleanup.py |
| U3 | Docker 公钥完整验证后原子落盘，中断可重试 | test_installation_edges.py（中断与截断重试） |
| U4 | 已有部署界面不再暴露仅首次安装支持的配置步骤 | wizard_state_checks.js / test_installation_wizard.py |
| U5 | 模块计划不能冒充已载入的实际开关状态 | wizard_state_checks.js |
| U6 | 切换升级组件后忽略过时轮询结果 | wizard_state_checks.js |
| B1 | 提醒最终投递再次核对范围、清空、来源和任务状态 | integration_agency_failure.py / test_audit_workflows.py |
| B2 | 自主写入在同一个事务中核对代次 | test_audit_scopes.py / test_audit_workflows.py |
| B3 | 清空/撤权期间的产物读取与写入不能复活旧内容 | test_goal_planner.py / test_audit_workflows.py |
| B4 | 自主等级0和暂停阻止在途后续请求、写入及发送 | test_audit_workflows.py / integration_agency_failure.py |
| B5 | 发送延迟和来源检查之后再次执行最终权限门控 | integration_audit_contracts.py / test_qq_actions.py |
| B6 | 确认未传输的提醒取消能释放状态，未知传输不重放 | integration_agency_failure.py |
| B7 | 二级提醒保留等待投递权限；三级恢复后可以继续 | integration_agency_failure.py |
| B8 | 清空保留不含正文的额度结算账本 | test_audit_scopes.py |
| T1 | 共享公开读取统一240；停止、查询等免费控制不被拦截 | test_leisure_policy.py / test_audit_workflows.py |
| T2 | 附件删除按来源依赖图撤销，保留无关提醒和笔记 | test_audit_workflows.py / integration_agency.py |
| T3 | 原生历史中的附件派生回答按同一来源和TTL退役 | test_audit_workflows.py |
| T4 | 解析结果明确标记字符截断、片段和未知覆盖 | test_audit_workflows.py；真实工作台协议验证 |
| T5 | 移除不存在的B站收藏夹条目不再创建新收藏夹 | test_leisure_policy.py |
| T6 | 同轮并行公开研究先加锁预留次数 | test_audit_workflows.py |
| E1 | 经人工审核的私人素材包能登记、安装、重启后读取 | test_audit_installation.py；公开发行无角色原画 |
| E2 | CI 覆盖完整源树和清单，包含完整回归与向导状态测试 | installation-wizard.yml；平台实装仍单独验收 |
| E3 | AI 计划区分空白主机、已有核心和已有 Companion | test_ai_access.py / test_easy_deploy.py |

## 七项现场重点

| 编号 | 实现与实际限制 |
|---|---|
| R1 | 实时兴趣/原生逻辑回复与后台4/16额度分池；每群实时上限999，仍保留短时节奏与安静时间 |
| R2 | 原生、P1、兴趣、后台四个开关分别显示；`/群主动诊断` 解释当前阻断；保留管理员原有选择 |
| R3 | 语义候选入口覆盖隐含兴趣，不再要求固定兴趣关键词先命中；普通被点名路线仍独立 |
| R4 | 准入只探测，实际传输才结算；确认未传输可释放，未知回执不重试 |
| R5 | 后台最多40/Agency总200；耗尽转本地活动或等待；公开读取240单独计算；失败任务退避 |
| R6 | 情境、纠错和近期对话可以升级 max；记录准备/完成/失败及实际 SDK 用量，默认配置不伪称已改为 high |
| R7 | 对确切的已有外部浏览器 Compose 绑定显式登记，不搬动私人登录目录，不改变网络或容器 |

## 情感与自修复的结论怎样阅读

Concern、Stance、Episode、混合情绪和可撤销表达学习均有持久化、来源和隔离测试。评测交换顺序并保留平局、分歧与失败；本轮没有足够证据证明新策略的聊天自然程度显著优于旧策略。不要把模块更多、max更多或通过用例更多写成情感质量结论。

已知源码/配置/服务/数据库故障的恢复覆盖八类插件和六种数据库角色。模型提出的新补丁仅可修改三个已封存的纯格式函数，并受固定测试、资源、重试、观察与回滚限制。其余未知业务缺陷需要经审查的版本更新。代码回滚保留当前聊天数据；十年免维护和任意新缺陷自动修复均未获证明。
