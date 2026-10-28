# ROUND-004-SIM 验证与迭代记录

公开阅读说明：文内标为“本地证据”的完整JSON、决策卡及私人派生文件不随GitHub分发；下文保留可公开阅读的结论、命令与限制。

2026-10-26。用户要求模拟场景测试并迭代。[简版结果](../docs/回合复盘方案_v0.1/SIMULATION_RESULTS.md)、[任务与有限扩展](../docs/回合复盘方案_v0.1/SIMULATION_TASK.md)。目标为`decision-frame/v1`、`round-decision/v1`、`simulation-cases/v1`；实现哈希见本地`reasoning_simulation_execution_20261026.json`。人工签署未提供。

## 实际结果

| 阶段 | 完整契约 | 关键事实显式引用 | 说明 |
| --- | ---: | ---: | --- |
| 冻结旧提示/契约，首轮12份模型答案 | 0/12 | 12/12 | 多数候选保留前提却标supported；4份还遇到旧检查器不认识行动观测的问题 |
| 同一批原始答案换修订后检查器，尚未改答案 | 0/12 | 12/12 | 没有放宽标准换取通过，仍需模型修订 |
| 新提示/契约＋确定性错误反馈，一次修订 | 12/12 | 12/12 | 原事实、候选ID、成立前提与假设逐项比对保持；改标签、动作绑定与解释 |
| 新增C7两题迁移作答 | 2/2 | 2/2 | 能独立完成有限目标则立即执行并退出；必须承接且队友未到则等待，排除当前独自尝试 |

共14个场景ID、26份模型答案文件（12首轮＋12修订＋2新增），**不等于26次API请求**。同一对照只改变一项语义变量；C4只改变审计侧隐藏信息，模型消息完全相同。C7在发现初始题设普遍保留配合缺口后加入，用于排除“任何情况都等队友”的捷径；不称独立统计保留集。

Codex开发侧按冻结的条件标准阅读原始/修订答案，最终14题符合本轮限定语义要求。它不是独立教练评分、真实国服正确率或最优行动证明；程序的`tactical_quality`始终保留`not_evaluated`。首轮语义方向大体符合条件，但标签冲突使全部答案不能作为合格输出展示，不能将0/12→12/12解释成战术能力从零提升到满分。

## 三个确定问题及修复

1. **生命值证明已跟进：旧版错误放行。** 旧合成输入仅引用队友生命值0，却把“跟进”标为observed，检查返回PASS。现在要求可选扩展字段`action_key`在observed时必填，并匹配同actor、同动作键、`action_observation/observed_action`以及`in_progress/completed`。相同错误答案返回FAIL，合法动作观测返回PASS。真实适配器尚未产出此行动字段，不能据此宣称新增解码成果。
2. **提示没有解释标签的严格含义。** 模型把“建议合理”理解为supported，同时填写未满足前提。提示补清候选/推荐的条件约束，保留已有检查强度。12份修订没有删掉事实、前提或假设；具体变化见`revision_diff.json`。
3. **排除候选的中文展示不明确。** 首轮C4B把盲目前压标为ruled_out，而旧渲染器不显示选项状态。修订后显示“已排除，不执行”，并分别标注“已具备条件”“待条件满足”。定向测试验证区别；C4B及C7B最终卡片可直接检查。

## 执行方法与证据边界

- 两个使用独立初始上下文的Codex分析员分别读取A/B侧的6份`messages.json`，未提供rubric或另一侧答案。每批内部多题共享上下文，文件系统也并非强制隔离；不称严格统计盲评。
- 分析员通过文件保存原始JSON，未自行运行检查器。修订时收到自己的旧答案、更新后的消息/契约及确定性错误反馈；没有提供战术评分答案。新增C7在其后各自作答。
- 本次是实际会话模型作答，经文件交接后执行检查CLI；没有接入供应商API，也没有声称通过`run_reasoning`完成实时模型回调。费用、Token和调用延迟统计未知。
- 角色和能力均明确为`synthetic_stipulated`。未新增真实游戏测试、解码、导航实测、训练或前端。原回放283秒人工示例仅做兼容重检，仍PASS，不计作新的模型测试。

## 软件测试和失败记录

最终实际完整回归：**587 passed in 6.57s**，无失败、无跳过；较上一轮554新增33项（契约/渲染14，模拟工具19）。

```powershell
Set-Location D:/1/yxlm/lol-coach
.venv/Scripts/python.exe -m pytest -q --basetemp data/private/test_tmp_round004_final_20261026
```

该临时目录已使用；复跑请换一个新的工作区临时目录，勿把业务数据目录用作pytest临时目录。原始输出保留在`reports/reasoning_simulation_pytest_final_20261026.txt/.json`；先前584项的中间回归亦保留，没有覆盖。

专题测试首次16通过1失败：fixture中多个候选共享同一引用列表，第二次remove失败；改为各自独立列表后通过，最终扩展为19项。契约修复首次定向68通过；增加排除项渲染测试后最终契约集69项。首轮模型答案的失败完整保留，未代改后冒充原始输出。

## 修改和运行

- 修改`lol_coach/reasoning_frame.py`：行动证据和supported/conditional的提示定义。
- 修改`lol_coach/decision_contract.py`及其测试：动作键绑定、观测范围、排除项展示。
- 新增`lol_coach/reasoning_simulation.py`、`scripts/simulate_reasoning.py`、`tests/test_reasoning_simulation.py`：七对合成题、冻结清单校验、缺答案/错误答案报告、关键引用覆盖及中文卡。
- 独立文件夹新增任务卡、结果简稿、`SIMULATION_RUBRIC.json`；更新导航、框架说明、CURRENT_TASK和STATUS。
- 未修改既有解码器、原始素材与其他未提交变更；未提交或推送GitHub。

已实际执行的最终场景检查命令：

```powershell
.venv/Scripts/python.exe scripts/simulate_reasoning.py check --cases data/private/reasoning_simulation/round004-transfer --answers data/private/reasoning_simulation/round004-answers-v2 --output data/private/reasoning_simulation/round004-check-final
```

该输出目录已存在，复跑请更换末尾目录。prepare/check的日常使用见简稿。CLI只准备和检查答案，不会自动请求外部模型；缺答案明确FAIL，失败退出码2。输入文件或rubric不匹配冻结哈希时，拒绝执行且不创建检查目录。

## 证据索引

以下产物均在本地`data/private/reasoning_simulation/`，不默认公开上传：

- `round004-v1/`：原12题、旧提示/schema哈希、冻结评分表。
- `round004-v2/`：第一次行动证据提示修订的中间输入；未向模型运行。
- `round004-v3/`：补清标签定义后的12题中间输入；最终使用的14题输入为`round004-transfer/`，其前12题局势与原版相同。
- `round004-answers-v1/`、`round004-feedback/`、`round004-answers-v2/`：原始答案、错误反馈、12修订＋2新增答案。
- `round004-check-baseline/`：恢复点中的旧校验器实际检查；`round004-check-original-with-new-validator/`：同答案用新校验器；最终检查（本地证据：`../data/private/reasoning_simulation/round004-check-final/summary.json`）记录14题结果、答案与实际校验源码哈希。
- `baseline_semantic_review.json`、`final_semantic_review.json`：Codex开发侧逐题理由、原文证据、答案哈希和评阅范围。
- `revision_diff.json`：实际改动路径及事实/前提/假设保留核对。
- `round004-probes/`：生命值冒充行动的前后反例、合法行动正例、旧排除项渲染、旧真实样例兼容记录。
- 可独立完成的答案（本地证据：`../data/private/reasoning_simulation/round004-check-final/C7A/answer.md`）、必须承接的答案（本地证据：`../data/private/reasoning_simulation/round004-check-final/C7B/answer.md`）。

S1—S5均在任务卡限定范围内PASS：单变量/隐藏输入测试、实际答案文件、反例修订、开发侧分层评阅、完整回归。source为fixture_demo＋Codex执行记录，evidence_level为synthetic_stipulated；不是peer_runner或独立人工签署。

## 剩余缺口

真实国服回合及独立战术评分尚未执行，尚无真实模型供应商的费用/延迟/稳定性结果。现有单决策点框架仍缺整局回合切分与计划记忆；基础数据原有缺口保持。

数值耗时工具尚未接入：当前计算接口只对登记区间作值匹配，仍需绑定动作、执行者和计算可用时刻，接入前不能把其当完整时序验证。本轮所有场景计算表为空、耗时为null，不使用这个接口制造精确结论。

恢复点`data/private/document_backups/ROUND-004-SIM/manifest.json`。下一步可用冻结真实局势接选定模型回调，单独检验数据缺口与战术质量；本轮无需用户补录或重开游戏。
