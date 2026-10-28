# ROUND-005-REAL 验证记录

公开阅读说明：文内标为“本地证据”的完整JSON及私人派生文件不随GitHub分发；下文保留公开结论、命令与限制。

2026-10-26。任务范围见[任务卡](../docs/回合复盘方案_v0.1/REAL_REPLAY_TASK.md)，短版见[真实回放结果](../docs/回合复盘方案_v0.1/REAL_REPLAY_RESULTS.md)。证据清单见执行记录（本地证据：`real_reasoning_execution_20261026.json`）。

## 实际完成

新增`lol_coach/file_model_bridge.py`、`scripts/run_reasoning_session.py`、`tests/test_file_model_bridge.py`，沿用已有编译器、资料查询和答案契约。文件桥只传递`messages/tools/response_schema`，通过请求ID匹配响应；不把bundle审计、原始回放或本地文件路径交给分析员。输出新建不覆盖，响应须完整原子发布，限制大小、有限数值、格式及等待时间。

本会话的三个独立上下文 Codex 分析员只读取各自会话请求并写响应。`run_reasoning`实际执行`get_reference`，将返回结果放进下一次请求，再检查最终答案。三个分析员分别对应三个时刻，没有互相投票；属于开发侧实际模型运行，不能冒充独立教练评阅。文件协议本身不认证写入者，也没有实现供应商SDK或自动调用外部模型。

| 冻结时刻 | frame_id | 首轮终态 | 最终检查 | 接受会话的回调/资料读取 |
| --- | --- | --- | --- | --- |
| 283 | frame_cfbb63cda5d41b0b78fb23c7 | completed | PASS，0次答案修订 | 4 / 10 |
| 293 | frame_50386228a1b992f8f754ffb2 | completed | PASS，0次答案修订 | 3 / 8 |
| 300 | frame_c7d7d1641a1cb6bd162824e3 | failed：响应4超时 | 新会话恢复PASS，0次答案修订 | 4 / 10，复用真实模型响应 |

这些是文件回调数，不是供应商API调用数。共3份不同的真实模型最终答案。包含失败与恢复的全部尝试为15次文件回调、38次资料读取；不把恢复重复读取当新增案例。费用、Token、正式性能指标和外部独立战术签署均未取得。

## 输入、版本与事实边界

真实本地回放`HN1-11360086609`，team100、self`0x40000034`。回放构建`16.20.824.8524`，静态英雄缓存`16.20.1`；静态版本到具体客户端构建的完整兼容性没有独立确认。地图/模式、地区、队列未绑定到帧，保持未知，不能用塔名线索替代。本轮不认定国服峡谷适用率。

三个冻结包位于`data/private/reasoning/round005-t{283,293,300}`，含100、100、99条事实。模型不读取其他时刻或审计材料。开发侧预先保存的核对依据为`data/private/reasoning_sessions/round005-review-basis.json`，标记`model_may_read:false`；它不是供模型照抄的标准答案。

| 核对点 | 实际结果与范围 |
| --- | --- |
| 283秒旧塔血 | `f_c8e1d0788c85f69305b7`来自254.604秒附近，只能用作最后采样；答案要求刷新当前塔状态 |
| 293秒新塔血 | `f_68f9ae3f2c5dede92974`对应292.989秒附近的新采样，约1825.614；答案未由此补出兵线和安全攻击条件 |
| 293秒隐藏剑圣 | 答案把失去视野后的生命/坐标留为历史信息，不提供当前隐藏位置或追击路线 |
| 300秒零塔血 | `f_a229df0296d55e7bccf4`对应299.602秒附近的零生命采样；答案更换目标。帧未接入独立摧毁事件，不把该事件写成模型已收到的证据 |
| 敌人重新出现/近期击杀 | 新非零采样与历史击杀分开；不推导确定4打1、复活秒数或确定击杀线 |
| 机制与队友承接 | 查询本局英雄资料后保留武器、弹药、冷却和动作前提；维迦放笼不等于命中，剑圣减速免疫不等于免疫所有控制 |
| 时间、装备、地图 | calculations为空，耗时保持null；现金不当装备，位置候选不当导航，不默认回城或死亡购买规则 |

开发侧逐份阅读了答案及引用，以上限定边界通过；未逐帧对照游戏画面，未取得独立战术评价。`tactical_quality`仍为`not_evaluated`。建议中的追击、撤离和推进都是待执行方案，不反推玩家已实施这些动作。数值摘要只用于说明输入变化，不是健康度或伤害模拟。

只读复核另提醒：300秒死歌职责中的“较早复活或生命采样不等于正在赶来”是在否定到场推断；输入的复活仍为`respawn_candidate`，不得汇总成已确认复活。产物汇总脚本首次误把facts字典当列表遍历而报TypeError；改为遍历values后重跑，未修改产品代码或模型证据，错误也保存在执行记录中。

## 真实失败、恢复与迭代

`round005-t300/result.json`保留`failed`：`No response for request 4 within 300 seconds`，answer与validation为空。真实模型稍后发布响应04，原失败没有改写；该迟到文件不在失败终态时生成的manifest输出清单中，单独由恢复记录绑定哈希。

新建`round005-t300-retry`，对每个新请求与旧请求做完整JSON相等检查，核对request_id后重投原始响应。编排器重新执行资料查询并接受原真实答案。四次请求一致、原响应哈希、恢复PASS见`data/private/reasoning_sessions/round005-recovery.json`。这是传输恢复，**不是第四份独立模型答案**。

原运行代码默认等待180秒，首轮显式配置300秒，恢复显式配置600秒。之后把默认值统一为600秒，保留可配置和有限等待；未据此宣称延迟优化或新模型运行速度。原版本已备份至`data/private/document_backups/ROUND-005-REAL-bridge-before-timeout`，历史运行manifest可解析到该版本。完整回归在改默认值后再执行。

## 实际检查与验收

| 检查 | 结果 | 证据/边界 |
| --- | --- | --- |
| 新适配器专题测试 | 12 passed in 0.62s | `data/private/reasoning_sessions/bridge_targeted_first_run.json`；脚本替身只用于单元测试 |
| 首次完整回归 | 599 passed in 7.83s | 原始记录（本地证据：`real_reasoning_pytest_20261026.json`） |
| 默认超时迭代后的完整回归 | 599 passed in 7.16s | 最终原始记录（本地证据：`real_reasoning_pytest_final_20261026.json`）；stderr为空、exit_code=0 |
| D1 冻结与来源 | PASS | 三个真实包及其manifest，事实时间不晚于决策点 |
| D2 实际模型/工具闭环 | PASS | 原请求、真实Codex响应、工具轨迹、接受的三份答案；恢复另记 |
| D3 有界错误/恢复 | PASS | 错ID、非法JSON/非有限数字、大小、超时、路径不覆盖测试；另有真实超时失败 |
| D4 限定事实边界评阅 | PASS | 开发侧评阅上述边界；不是战术最优验收 |
| D5 回归与交付 | PASS | 599项回归、结果文档、当前任务和状态更新 |
| 独立战术正确率、整局回合验收 | INSUFFICIENT_EVIDENCE | 非随机保留集，无独立教练签署，不计算准确率 |

测试命令：

```powershell
Set-Location D:/1/yxlm/lol-coach
.venv/Scripts/python.exe -m pytest -q --basetemp data/private/test_tmp_round005_final_20261026
```

重跑请换一个新的`--basetemp`目录，保留已有执行证据。新增12项覆盖真实编排的文件往返、错误和失败产物；其余587项为已有回归。

## 如何运行文件会话

使用已有冻结包，输出必须是新目录：

```powershell
.venv/Scripts/python.exe scripts/run_reasoning_session.py --bundle data/private/reasoning/round005-t283/bundle.json --output data/private/reasoning_sessions/my-real-run --timeout-seconds 600 --max-calls 6
```

**该命令等待模型响应端，不会自己调用模型。** 宿主读取`exchange/requests/01.json`中的request，将内容交给模型，然后把下面外层结构原子写入同序号`exchange/responses/01.json`：

```json
{"request_id":"原请求中的ID","response":{"tool_requests":[{"id":"r1","name":"get_reference","arguments":{"reference_id":"champion:Aphelios"}}]}}
```

下一次请求包含工具结果。最终响应为`{"request_id":"原请求中的ID","response":{"answer":{}}}`，其中answer须填写请求附带的完整schema，不能是空对象。最多6次回调、最多1次答案修订；未作答则明确超时。宿主可用`atomic_json`发布完整响应。最终查看result、validation、answer.md和manifest。

本轮通过当前Codex会话完成上述响应端，既没有要求用户提供密钥，也没有引入新的付费模型。直接读取现成三份卡片无需再运行模型。

## 修改与恢复

新增3个代码/测试文件、真实任务卡和简版结果、此报告及执行记录；更新方案README、框架说明、CURRENT_TASK、STATUS。不改旧解码器。原有未提交文件保留。

恢复点`data/private/document_backups/ROUND-005-REAL/manifest.json`包含修改前文档与沿用代码哈希；状态和当前任务保留历史全文。执行记录同时绑定当前代码和历史运行代码。本轮无训练、前端、游戏操作或GitHub推送。

当前限制是具体信息尚未齐备，模型会给条件方向而不是精确路线和时间。下一项可直接利用已有兵线/单位身份导出增强决策帧，并接相邻回合的计划/失效记录；不以重新开游戏或额外补录作为前置要求。实际冷却、完整装备、区域视野和动作耗时的既有缺口仍按对应证据状态保留。
