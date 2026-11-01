# 兵线理解与相邻回合链路：本轮结果

2026-10-28，ROUND-007-CHAIN。

**已确认模型能理解现有回放时刻的队伍可知兵线，并已把它接入相邻回合决策链路。** 包括兵数、兵种、最新复制生命、估计位置、前后兵团和近期损失。这里的“实时”指时刻t的可知状态，不是已经接上在线游戏，也不补全隐藏单位；位置仍是估计。

链路现在是：回放可知状态 → 英雄/塔/兵线局势板 → 上一计划与新变化 → 资料查询和模型比较 → 校验 → 保存下一张卡。历史计划单独保存，不冒充当前事实或已经执行的动作；前卡不合格时仍能独立分析当前帧。

## 三个真实时刻实际跑出的结果

| 时刻 | 新信息 | 模型回答 |
| --- | --- | --- |
| 4:43 | 己方6兵仍在后方，敌外塔仅有较旧血量记录 | 先接兵、保持队友保护；兵未到、塔状态与退路未确认时不直接上塔前 |
| 4:53 | 6兵位置前移；外塔新采样1825.6血；剑圣失去视野 | **改选**旧计划的执行方式，条件满足才随兵点塔，排除按剑圣旧位置盲追 |
| 5:00 | 外塔0血；前方3远程兵，后方6兵含1炮车；剑圣、瑞兹重新可见 | **改选**：结束旧外塔目标，先整队接续兵线；打下一塔须重新确认目标、到兵和保护条件 |

后两帧都明确：**上一建议是否被玩家执行未知，不能把塔血变化归因于执行了建议。** 三帧当前事实没有被承接层改写，后一帧只显式接收上一张卡与历史引用，使用新模型上下文分析。

实际完成3张新卡、7次模型响应、16次资料查询，3/3结构与引用通过，0次答案修订。首个会话有一次资料请求超额失败，补充调用协议后重跑，失败原样保留。最终代码回归**958项通过**。这是开发侧事实与链路验证，不是独立教练认定的战术准确率。

## 文件与使用

核心改动：新增`lol_coach/round_chain.py`；扩展`decision_contract.py`、`reasoning_frame.py`、`reasoning_runner.py`及两个CLI；新增两份承接测试。任务、验证与状态也已更新。

在`lol-coach/`运行下列命令；示例使用本机已存在的冻结包和实际答案，输出目录须尚不存在：

```powershell
.venv/Scripts/python.exe scripts/reasoning.py chain --bundle data/private/reasoning/rpl011-t293/bundle.json --previous-bundle data/private/reasoning/rpl011-t283/bundle.json --previous-answer data/private/reasoning_sessions/round007-t283-retry/answer.json --output data/private/reasoning/my-chain-293
.venv/Scripts/python.exe scripts/run_reasoning_session.py --bundle data/private/reasoning/my-chain-293/bundle.json --output data/private/reasoning_sessions/my-chain-293
.venv/Scripts/python.exe -m pytest -q --basetemp data/private/test_tmp_my_chain
```

第二条沿用文件模型回调：宿主读取`exchange/requests`，按请求里的协议返回`responses`；它不会自行调用付费API。没有前卡时省略两个`--previous-*`参数；损坏或错局前卡会显式退回独立分析。公开仓库不含私人实局包，可运行合成离线测试。

本机实际卡片：[4:43](../data/private/reasoning_sessions/round007-t283-retry/answer.md)、[4:53](../data/private/reasoning_sessions/round007-t293/answer.md)、[5:00](../data/private/reasoning_sessions/round007-t300/answer.md)。[完整检查、失败及版本说明](../reports/round_chain_validation_20261028.md)。

下一项是ROUND-008-TIME：接入证据充分的一类行动耗时。整局自动分段、精确ETA和独立国服战术盲评仍未完成；完整施法/背包/区域视野保持原缺口。本轮无需重开游戏或补录，未做训练、前端或Git推送。
