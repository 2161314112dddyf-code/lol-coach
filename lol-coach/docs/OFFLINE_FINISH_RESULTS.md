# 本次要求的交付与剩余阻断

2026-11-01，OFFLINE-003。先处理前序离线事项，再推进不依赖录像缺项的分析链路。本次没有停在工具清单：整段处理、资料接入、实际模型样例、评测入口和实验交接均已运行或写成可执行操作单。**完整字段逆向仍未全部解决，不能把下面的软件交付当作四项语义验收通过。**

## 对照要求逐项交付

| 要求 | 本次实际完成 | 未被冒充为完成的部分 |
| --- | --- | --- |
| 汇总所有录像实验 | [一次性操作单](RECORDING_HANDOFF.md)，覆盖E00/M/S/I/V/J，记录模板在本轮证据目录 | 未执行游戏实验；目前只需短预检，不批量录长实验 |
| 先检查前序离线工作 | 新版跨编号探测；技能自然对照/资源混杂检查；物品多解检查；实时创建对象覆盖检查 | 未确认字段继续隔离 |
| 处理密集边界候选 | 175时刻→34个复盘检查点，保留141个未选时刻；170个原始变化候选全部恰好覆盖一次，末尾无遗漏 | 调度策略不是正确回合标签，30秒合并间隔不是游戏回合定义 |
| 把结果接入分析链路 | 34份可运行bundle/messages；保持来源、时刻和视角约束；已有队友/对手机制现已作为可查询资料进入检查点 | 不给精确ETA/冷却/区域视野填值，不自动补玩家意图 |
| 基础资料支撑本局阵容 | 10名英雄、50个被动/技能入口、3条本局双英雄条件规则、4张有阅读依据的中文经验卡 | 这是本局基础覆盖，非所有交互穷尽；46项国服来源未冒充46段完整观看或46个战术标签 |
| 实际验证分析链路 | 300秒和320秒两次真实输入会话，共4次宿主响应、8次资料读取；前卡改选/取消连接通过 | 当前Codex产生的答案，不是独立模型盲评或人工金标；其余检查点只准备输入，没有虚构批量答案 |
| 完成评测入口 | 支持全部175时刻的外部标签，包括未触发时刻；检查重复/跨帧标签，计算已标注子集精确率和召回率 | 真实标签0，因此这次精确率、召回率、战术准确率均为空 |
| 真实测试及更新状态 | 新增13项；完整 **1223 passed in 9.34s**；来源/引用/时间/覆盖/旧decoder检查通过 | 自检不代替人工签署；未上传私人素材或推送Git |

## 前序未解项，这次具体查到了哪里

**新版16.21.829.9102。** 容器读取已在前轮完成，这次对stream1/2共763,797包作消息族检查，对尺寸16—65,536字节的148,373包跨opcode尝试旧路径语法和字节映射。旧版对照命中187包（stream1为186、stream2为1）；新版仅1个结构偶合：`0x28`、410.055569秒，实体`0x4f3d2dce`未在外层实体编号出现，速度约5.1e-30，22个点中20个超出宽松地图范围，因此未接受。不能只换opcode继续沿用旧解码。元数据可读10英雄/阵营，但没有同名明文token旁证来绑定运行实体；身份/移动的新编码仍需研究。没有宣称所有可能编码算法已穷尽。

**技能与冷却。** 检查80个自然活动对，5对间隔不足1秒；只有4对在限定邻域内仅含这两条命名活动，79对能找到资源变化样本。窗口不是全周期观测，资源还受回复/其他消耗影响；成功、失败、阶段和重置没有独立标签，不能将任意一对称为冷却测量。证据包列出具体活动ID和资源增量，不靠统计条数冒称成功施法已解。

**未知物品ec。** 已接受扩展槽消息里的`da→6`对照共8例；`ec`仅1例。令ec分别映射3、4、5都不与这些已接受样本矛盾，三种部分映射同时保留。这个结论只说明现有槽位标签约束不足，不声称三种中必有一个是实际协议，更不使用后来的背包倒填当时槽位。主动冷却和部分连续背包时间语义也仍未知。

**区域视野。** 四回放的实时创建记录共474条，没有明确命名的ward模型，也没有双视角单一来源开关的区域真值。已有对象可见性和创建/归属字段继续有效，但不足以唯一还原逐区域可见性、遮挡及来源消失的影响；不能用静态半径圆冒充答案。

## 这次真的产出的分析

- [300秒最终卡](../data/private/offline_finish_20261101/answers_final/t300/answer.md)：新零血塔观测使旧攻击目标失效；结合远近分组的兵线和敌人重新可见，先重整，继续推进只作条件分支。
- [320秒最终卡](../data/private/offline_finish_20261101/answers_final/t320/answer.md)：本人新的零血观测和历史击杀让现场输出前提失效，取消旧计划，转向确认恢复、补给和下一次集合；不猜复活倒计时，也不倒推之前建议导致了死亡。

两份卡都保留首选、不同条件下的行动、真正退路、双方角色、未知耗时和退出条件。初版虽然通过契约，却把更积极的B方案当成退路；自查后补上C退路，重绑320秒前卡并重新验证，原会话和失败解释保留。证明软件PASS不等于战术表述完备；没有为让答案通过而放松契约。

34个检查点的[时间索引](../data/private/offline_finish_20261101/sequence_v2/INDEX.md)和最终输入清单`ready_final/manifest.json`均已生成。初始、普通合并、紧急观测、扫描截止分别1/19/13/1个；未选时刻141个只供未来盲标，标签为空。

## 运行与修改文件

项目根目录`D:/1/yxlm/lol-coach`，所有输出使用新目录：

```powershell
.venv/Scripts/python.exe scripts/research_new_build_families.py --output data/private/new_family_repeat
.venv/Scripts/python.exe scripts/audit_experiment_identifiability.py --output data/private/identifiability_repeat
.venv/Scripts/python.exe scripts/build_review_sequence.py --scan data/private/offline_execution_20261101/boundaries_v2 --output data/private/review_sequence_repeat
.venv/Scripts/python.exe scripts/finalize_review_sequence.py --sequence data/private/review_sequence_repeat --output data/private/review_ready_repeat
.venv/Scripts/python.exe scripts/evaluate_review_sequence.py --sequence data/private/review_sequence_repeat/sequence.json --output data/private/review_eval_repeat
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=data/private/offline_finish_tests_repeat
```

评测CLI的`--labels`可读取外部标签JSON；模板由CLI输出，每条必须绑定`source_frame_id`并填写作者，`needs_reconsideration`可以true/false/null。部分标注只能报告标注子集，不冒充整局准确率。模型运行复用`scripts/run_reasoning_session.py --bundle <最终bundle路径> --output data/private/reasoning_sessions/<新目录>`，需要宿主提供真实响应；单独运行CLI不会自动获得模型答案。

新增模块：`review_checkpoints.py`、`lineup_references.py`、`review_evaluation.py`；新增上述5个脚本和3个测试文件。新增任务卡、本文、录制交接单；更新CURRENT_TASK、DEVELOPMENT_GUIDE、PROJECT_SUMMARY、VIDEO_AND_OFFLINE_BACKLOG及STATUS。历史未提交文件保留，不归为本次修改。

证据根`data/private/offline_finish_20261101`：`new_families`、`identifiability`、`item_nonuniqueness.json`、`sequence_v2`、`ready_final`、`evaluation_final`、`answers_final`、`artifact_checks.json`、`full_tests_execution.json`。`failures_and_revisions.json`记录source_url字段修正、尾部合并和答案退路修正。两次原始宿主会话在`data/private/reasoning_sessions/offline003-t300`及`offline003-t320`。费用/Token未采集，不填写虚假数值。

## 需要接手的实际边界

当前已把列明的离线审计、整段调度、资料接入、两例实际承接和标签工具做完；没有把新版本语义、完整施法/冷却、完整连续物品状态、区域视野或实际时间精度改成PASS。它们不是靠多跑一次同样测试就能完成的。

**最有用的下一份材料是E00短片及对应ROFL**，具体动作见[交接单](RECORDING_HANDOFF.md)。已有符合条件材料可直接给本地路径；暂时无法录制则保留这些缺口，不要求重开旧版录像。新构建的实体/动作锚点建立后才安排M/S/I长块，区域视野另需可控双视角。旧ec若无同构建新约束仍继续未知，不能让新版录制替它“通过”。人工判断哪些检查点值得改计划是另一类标签需求，不用模型自己的答案当金标。

更广的协议研究和案例覆盖仍有研究空间；本报告没有证明研究空间穷尽，也没有把所有剩余开发责任转成用户录制任务。进入新研究必须提出新的可检验约束，避免反复同一窗口或重新做已交付工具。

验收A/B为限定研究执行PASS、字段语义INSUFFICIENT_EVIDENCE；C/D为链路及契约PASS、回合/战术效果INSUFFICIENT_EVIDENCE；E为交接与需求对照完成。执行者Codex，独立人工复核未执行，signer=null。恢复点`data/private/offline_finish_20261101/backup/manifest.json`；[任务卡](OFFLINE_FINISH_TASK.md)。
