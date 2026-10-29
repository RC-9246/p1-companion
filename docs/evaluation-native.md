# 隔离的原生对话评测

`evaluation/native_dialogues.py` 需要实际安装的 AstrBot SDK 与 OpenAI 兼容客户端。它只在明确传入 `--run` 后调用 `https://api.deepseek.com`。需要操作者事先批准服务、人格提示和测试数据发送；脚本参数不能代替授权。

评测每组使用独立进程和临时存储。在导入插件前设定数据目录，随后核对实际加载模块的路径与指纹，防止旧版本误加载新代码。Linux可预热框架再创建独立子进程，其他环境使用新解释器进程；两者不共享会话数据库。

经过 Memoria、Affect、配图、复盘、表达学习、工具收束、群隔离、QQ文本及媒体来源等前景钩子，模型才收到请求。群路由未接纳的消息记为旁听，不强迫生成一条回复。复杂语境使用当前选择器的 max，普通消息采用 high；思考强度和最终回复长度分开。

只接通三个隔离工具：当前范围记忆搜索、候选记忆写入和已有知识摘要。它们使用真实 JSON 函数调用，每轮最多两次工具调用；候选成功仍不等于人工确认。其他浏览器、QQ、B站、外部发布和系统工具都不提供。假的投递回执只为触发本地提交路径，绝不记作实号送达。异步长期复盘、完整原生代理循环和全部工具由其他集成验收分别覆盖。

私有凭据文件的字段是 `key`、`model`、`base_url`，只放在受限目录；不要放进仓库。仅使用已经获准的现有账户。人格文件、原始回复、凭据、私有路径与隐藏推理不能公开。思考字段仅在子进程内为服务协议暂存，报告只含最终内容及用量。

在隔离、限资源的 AstrBot 环境内运行，例如：

```sh
python /source/evaluation/native_dialogues.py --run \
  --source /source/candidate \
  --cases /source/evaluation/native-holdout.json \
  --credentials /private/credentials.json \
  --persona /private/persona.txt \
  --group-persona /private/group-persona.txt \
  --output /private/candidate-result.json \
  --label candidate --workers 2 --max-calls 576
```

`--source` 指向包含 `release/` 的完整被测版本，旧版和新版应在独立容器或进程中运行。不要挂载生产数据、浏览器登录目录、Docker套接字或真实 QQ 传输。例中的576是48组双轮场景的最坏调用上限，并非正式机器人每日额度；脚本另有限制输出用量、每组超时与子进程数量。生产额度不由评测重置。

比较器 `evaluation/judge_dialogues.py` 对完整配对交换两次顺序，用同一场景整体重采样计算区间。只有两个顺序都选同一方才算胜；分歧不是胜出。评审能看到同一份合成活动来源，以及已实际执行的隔离工具状态，不将候选保存当成永久记忆生效。

`native-development.json` 有12组诊断样本；`native-holdout.json` 有48组原创双轮样本，首次比较后已作为回归集；第二轮另冻结 `native-fresh.json` 的16组新情境。指纹在 `native-scenario-manifest.json`。作者了解实现，它们不是独立人工盲测。后续调参不能继续把这些已用过的样本称为未知样本。

评测不自动判定“人格已达极限”。报告必须同时说明未完成场景、分类/审校降级、模型错误、真实工具覆盖、版本指纹与评审限制。失败结果保留，不通过重试筛选成漂亮的一次。

比较器新报告采用统计schema 2：`completed` 包含服务已返回但JSON无效的答复，`valid_judgements` 才是有效评分数；先记录用量再解析。旧schema 1在解析之后累计，发生解析错误时用量是下界。旧报告不按新口径重写，也不重试挑选评分。错误的最终输出仅限私有诊断，隐藏推理与凭据不写入报告。
