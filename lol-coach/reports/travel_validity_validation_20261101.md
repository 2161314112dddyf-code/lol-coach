# ROUND-008-VALIDITY执行记录

目标构建16.20.824.8524；执行日期2026-11-01；开发侧检查，非玩家/教练签署。任务与预定边界见[任务卡](../docs/TRAVEL_VALIDITY_TASK.md)，简版见[结果](../docs/TRAVEL_VALIDITY_RESULTS.md)。证据目录`data/private/time_validity_20261101`；恢复点`data/private/document_backups/ROUND-008-VALIDITY-20261101`保留前轮未提交修改。

## 实现与权限

`lol_coach/travel_validity.py`提供因果feed/snapshot/query；`travel_validity_inputs.py`复用已解码的英雄状态/视野/移动/生命周期、独立移速属性候选及小兵动态。原路线算术、解码器、原回放、前轮冻结预测与模型契约没有改动。

新计划替换旧计划；速度变化只使旧计划失效，不从陈旧位置重算；死亡后路径不复活，英雄需正生命与新路径，复活候选不等于存活。小兵零血/清理候选后不能因迟到样本恢复；规范化事件持续携带`entity_kind`。清理候选不是确切死亡时刻。视野重入不恢复旧计划。单点或终点附近位置只记录报告，精确实际到达始终null。

默认`max_path_age_seconds=1.0`，到龄或预计到期后剩余时间null。历史计划可在审计输出中保留，并不仍有效。`arrival_observation.continuous_fresh_observation`只计算报告间隔是否在该工程策略内，不证明连续观测、恒速或精确到达。时间计算仅针对已收到路线，不能回答任意导航/清兵/团战/退出耗时。

已核验英雄本队阵营沿用现有`team_shared_information`政策，从首个实时证据开始；这不是伪造可见进入包，也不是玩家看见队友完整意图的证明。短回放英雄阵营未知，不赋予本队路径权限。小兵必须先有实时身份、再有该观察方显式进入；敌/未知路线转为起点候选，终点和速度不透出。死亡公共性注明`public_kill_feed_assumption`，不升级为独立UI证明。所有产物仍`decision_input_eligible=false`。

## 实际运行

输入盘点`input_inventory.json`，适配器执行`adapter_checks.json`：四回放×两队，97,802事件，原ROFL SHA与导出版本/来源/小兵receipt核验通过。独立属性候选为`0x3df/group32/bit25`，共1,659条；1,611条被允许作保守失效依据，48条短回放因阵营未知隔离。动态值尚未独立证明为连续真实速度。

`freeze_execution.json`：16个冻结查询文件，343,014行=24,501旧预测×2观察方×7时距。所有旧预测保留，记录超出回放/不可见/未知存活/过期，未按未来结果删样本；48项真实前缀、未来载荷和关键帧污染检查PASS。冻结阶段没有读取后续到达标签。源码与源数据哈希绑定在`frozen/manifest.json`。

`evaluate_execution.json`：冻结后读取前轮`evaluation_v3`，核对每个标签的回放、类别、原预测内容digest及完整ID集合，评价不改预测。新汇总`evaluation/summary.json`。两次实际query CLI出口成功，输出`speed_before/query.json`、`speed_after/query.json`，精选实体及命令见`sample_queries.json`。

| 固定查询时距 | 英雄原预测仍可返回条件剩余秒数 | 小兵原预测仍可返回条件剩余秒数 |
| --- | ---: | ---: |
| 0秒 | 16,353 | 7,323 |
| 0.25秒 | 4,824 | 5,925 |
| 0.5秒 | 1,477 | 4,922 |
| 1 / 2 / 5 / 10秒 | 0 | 0 |

只统计同一旧预测仍活动；后来建立的新计划不算旧预测继续有效。1秒后为0是预设有效期造成，不能当成精度或效果提升。双方查询共覆盖32,880个英雄、16,122个小兵的起始时刻；这些包含同一预测在两队的重复视角，不是独立预测数。

| 计划撤销原因 | 英雄 | 小兵 |
| --- | ---: | ---: |
| 新路径替换 | 13,640 | 6,647 |
| 单点报告撤销旧路径 | 2,005 | 1,288 |
| 独立移速候选变化 | 697 | 0 |
| 死亡事件 / 零生命 | 54 | 34 |
| 零速新路径 | 1 | 2 |

这些是有存档计划被替换/清空的次数，包含此前已到龄计划，不称为全部“活动ETA纠正”。没有活动计划的终态/视野转移不计入此表；软件反例仍覆盖它们。

主回放`0x40000034`：36.216780路径速度325、名义耗时1.264791秒；36.27查询剩余1.211572秒；36.283780独立速度候选406.25导致失效，36.29查询plan/null、remaining/null、reason=`speed_changed_requires_new_path`。这证明程序确实处理了独立属性消息，不证明新速度的物理正确性。

## 测试、纠错与复核

新增`tests/test_travel_validity.py`88项、`tests/test_travel_validity_audit.py`12项。覆盖时间前缀、他队/隐藏/关键帧隔离、源序与冲突、死亡/重入/终态、计划权限、速度/到期、非法数值、跨源标签与篡改拒绝。合成检查与真实回放检查分开。

真实运行历史：71过→74过/1失败→83过→88过→100过；唯一失败是他方同包visibility在过滤前占用源序冲突键，已改为先过滤，再做本方冲突检查。`tests_review_first.*`保留失败，`tests_all_final.*`为新增100项最终结果。不是删除失败断言来通过。

`full_tests.json` / JUnit：**1119 passed in 14.75s**，运行前后目标源码哈希一致。独立AI子代理检查记录于`independent_review.json`、`independent_artifact_checks.json`；它不是独立人类、教练或另一场实局。人工验收/签署、费用与token数未提供；本轮模型决策调用0。

## 验收及剩余缺口

| ID | 结果 | 范围/证据 |
| --- | --- | --- |
| V1 | PASS | 规范化适配器权限，48真实前缀检查与软件污染反例 |
| V2 | PASS | 改令/候选变速/死亡等失效，真实例子及反例；非精确物理状态证明 |
| V3 | PASS | 到期不造到达，剩余时间及时置null |
| V4 | PASS | 新增100项、全套1119项真实运行；原失败保留 |
| V5 | PASS | 16份343,014固定时距因果查询与独立阶段评价；同批回放复验 |
| V6 | INSUFFICIENT_EVIDENCE | 原T5/T6实际到达精度证据仍不足，未放行数值ETA接入 |

时距0活动子集与旧标签相交后，有91条英雄、7条小兵的短程实时终点报告；英雄81条、小兵1条宽度≤1秒的观察区间都集中主回放。英雄104条终点报告是所有预测时长口径，不能和91混用。这些只是历史报告对照，不证明预测到终点时仍有效，也没有增加新的独立到达证据。前轮95条英雄报告、单视频2.3—2.6秒与全部失败仍留原报告，不被新筛选覆盖。

下一推进点是补齐能改变T5/T6结论的第二局独立到达区间与可知身份绑定；若现有素材没有，就明确缺证据。不要再把本轮有效期列为待实现，不重复跑同批数据来增加“样本数”，不要求重做已通过的兵线或相邻帧。无需用户现在重开或补录；没有训练、前端、游戏操作或Git推送。

## 复现命令

在项目根目录；输出必须是新目录，不覆盖本次证据。

```powershell
.venv/Scripts/python.exe scripts/audit_travel_validity.py freeze --forecasts data/private/time_audit_20261101/frozen --output data/private/travel_validity_repeat/frozen
.venv/Scripts/python.exe scripts/audit_travel_validity.py evaluate --frozen data/private/travel_validity_repeat/frozen --labels data/private/time_audit_20261101/evaluation_v3 --output data/private/travel_validity_repeat/evaluation
.venv/Scripts/python.exe scripts/audit_travel_validity.py query --replay HN1-11360086609 --team 100 --at 36.29 --output data/private/travel_validity_repeat/example
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=data/private/travel_validity_repeat/pytest
```
