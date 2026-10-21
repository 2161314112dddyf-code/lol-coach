# 一个时刻的大局观输入

入口：`scripts/export_macro_snapshot.py`。结构版本 `macro-snapshot/v1`，当前精确回放版本 16.20.824.8524。读取既有四类完整导出，只查询本地文件，不启动游戏或调用模型。

```text
既有回放解析
  replay_ten        阵容、位置候选、死亡/击杀
  replay_state      生命、资源、等级、本人经济
  replay_inventory  本人装备操作与同步断点
  replay_vision     对观察队伍的英雄可见性
       ↓ 同源/版本检查 → 按 t 截断 → 按队伍/本人权限过滤
macro-snapshot/v1
  context          时刻、观察阵营、本人、地图身份、信息口径
  summary          双方实体、可见/隐藏/未知敌人
  heroes           当前可见期间采样、历史观测、位置候选、本人经济
  recent_public_combat  最近一段时间的公共击杀/死亡
  composition      每个英雄的队友、对手、待接入的机制能力
  world            地图路网、兵线、目标、区域视野、耗时、真人经验
  analysis_contract  如何比较行动、什么不能作为已知事实
  evidence         采样到源包位置的证据表
  provenance       解码 profile 与身份关联范围
```

## 查询口径

`--team` 采用队伍共享公开信息，不模拟某个玩家是否注意到屏幕/小地图；杀人公告作为公共信息假设，助攻和隐藏复活不输出。`--player` 可选且必须是已核验的本队实体，只为本人开放金币、经验和近期装备操作。队友的精确金币也不会默认当成本人已知。

`observed_now` 表示**本次可见期间最新收到的采样**，不是对查询时刻精确数值的保证。`last_observed` 为历史观测，隐藏后停止更新；再次出现时需要新的包，不拿隐藏期数值填入。所有采样有 `observed_at_seconds`、`age_seconds`、`unit` 和 `evidence_id`。缺少字典键表示没有符合口径的采样；`null` / `status: unknown` 不等于 0。

位置只取移动包的起点候选，使用 decoded_relative_xy 坐标系，尚未绑定本局地图。计划中的后续点不进入快照；不会推断已经抵达终点、隐藏位置、路线长度或 ETA。地图确认后再绑定路网和行动耗时。

装备只有本人近期操作和最近同步断点；`current_slots` 始终未知，因为撤销/消耗仍未完整恢复。敌方装备的观察语义尚未建立，暂不从全知操作流推成已知背包。不会使用结算装备、经济、伤害、补刀或未来区间结束时间。

## 从事实到行动比较

先读 context、world 和 analysis_contract 中的缺口，再看 summary / heroes / recent_public_combat。结合 composition 中**双方**阵容，接入有来源的机制和真人经验；最后按 analysis_contract 比较行动，而不是仅从英雄标签给建议。

可见对象数不等于存活人数或能参战人数。真实 400 秒样例中，Fizz 的可见通道仍为 true，但最近生命采样为 12.17 秒前的 0；必须结合死亡事件和采样时间，不能把四个可见对象直接推成四个可参战敌人。技能与特殊死亡机制未接入时，不能仅靠零生命推断所有行动均不可能。

每个候选行动必须说明：目的、队友如何跟进、对手可能反应、依赖哪些事实、移动与执行耗时、完成后的状态、收益、风险、机会成本、不确定性、证据 ID、何时撤销或改变计划。模型推测单列。未接入的机制/地图/耗时不允许由模型记忆变成“已核验基础”。

当前 `complete_macro_analysis_ready: false` 表示世界与机制覆盖不足；已经可用的阵容、可见性、采样时效、近期死亡事件仍可用来做有边界的观察分析。本切片交付分析输入与输出契约，不声称已生成最优战术。

## 运行

在项目根目录执行（输出文件名须尚不存在）：

```powershell
.venv/Scripts/python.exe scripts/export_macro_snapshot.py --replay-id HN1-11360086609 --at 400 --team 100 --player 0x40000034 --output data/private/macro_snapshots/example-team100-at400.json
```

生成 JSON、同名中文 `.md` 和 `.manifest.json`。省略 `--player` 即纯队伍公开信息；`--window 30` 控制近期事件窗口，默认 30 秒。原始输入哈希存旁路 manifest，不将整局统计塞给分析模型。无密钥、无网络依赖；输入不足或混用回放会报错，不能静默拼接。

复核：`scripts/verify_macro_snapshot.py` 使用已有四份回放输出，核对未来追加不变性和可见性采样；软件检查 `tests/test_macro_snapshot.py` 使用 synthetic 数据，不冒充真实游戏校验。
