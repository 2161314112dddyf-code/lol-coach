# INT-001 连续整合交付与真实执行记录

2026-10-21；目标回放构建 16.20.824.8524，静态来源 16.20.1。执行者 Codex，自检；人工签署、独立游戏语义复核、战术质量评价均未执行。任务卡：[INT-001](../docs/ANALYSIS_INTEGRATION_TASK.md)。

## 完成的可用结果

统一入口 `scripts/analysis.py` 提供 context、timeline、travel。context 沿用 macro-snapshot/v1，新增来源参考和覆盖情况，不把静态冷却当当前技能状态。

- 两队 400 秒局势输出均包含本局十名英雄、50 个被动/技能来源、双方关系、两张历史真人经验卡；每份静态 JSON 的 URL、HTTP 状态、响应版本和内容哈希实际检查。
- 三条本阵容条件交互：瑞兹强化 W 配合烬 W；小法笼边控制配合婕拉 E；婕拉植物减速面对开大剑圣。所需标记、命中、可用性、免控状态仍是未知，不自动输出成立。原潘森两条规则保留，合计五条。
- 已命名敌塔的可见期间生命接入 world.enemy_towers。排除未来身份、同时间戳身份获知前的采样、关键帧生命、隐藏期间生命；隐藏历史不回填当前；输出只保留白名单字段和源包定位。此视野语义仍是限定构建的交叉推断，不是独立 UI 确认。
- 行动时间线含 9 条既有计划/单点候选，明确计划替换；另列已有视频末段 2.3–2.6 秒观察。未新增录像测量，未把单点当抵达。
- 条件路线查询实际运行：输入折线长度 1365.6969 游戏单位、恒速 575 时算术耗时约 2.375125 秒，同时查询真实 Map11 基础网格。此输入不是对完整样本地图的确认，也不是实际到场预测。
- 已生成“能否依靠婕拉减速或控制衔接限制剑圣”的具体例子：3 组有时间/证据的事实、2 个条件候选行动，列出队友、对手、改计划条件；耗时、收益、风险、机会成本和优选行动均不伪造。

## 真实检查结果

| 验收 | 结果 | 执行证据与范围 |
| --- | --- | --- |
| INT-01 | PASS | 新合成用例检验身份时间、隐藏/重入、字段白名单、错来源；真实查询检查塔可知前缀 |
| INT-02 | PASS | 本局十人静态缓存读取；机制库 7 份固定哈希来源、20 处 JSON 指针检查；三项新增规则的合成满足/缺失/不满足情形 |
| INT-03 | PASS | 真实 replay/video 原文件哈希复查，时间线与 Map11 查询实际 CLI 运行；数学结果不当实测 |
| INT-04 | PASS（实验执行） | 四回放、五种偏移、同分母前后分段；全部反例留存；完整库存语义仍 INSUFFICIENT_EVIDENCE |
| INT-05 | PASS（限定整合） | 四回放共 9 个时刻/队伍查询，删掉未来事件后结果不变；21 份输入哈希未变；完整回归 336 passed in 1.65s |

软件测试新增 25 项，完整测试从 311 增至 336。第一次完整测试为 336 passed in 1.64s；修复真实整合中发现的两类短回放问题后，最终为 **336 passed in 1.65s**。原始结果 `reports/pytest-analysis-integration-final.xml`；真实整合记录 `reports/analysis_integration_validation.json`。测试数量不证明未知游戏字段已破解。

实现中发现并修复：① 初版实验 glob 误纳入 spell-survey 文件，缩小为数字回放 ID；② 短回放只有塔状态、没有配套塔视野时，改为保留其他输出并明确塔视野缺项；③ 短回放英雄身份未知时，不再尝试查找不存在的英雄缓存，改为 unknown_identity。失败输出未被记为通过。

## 新的背包时间实验

不再只比较同一个包时间：测试关键帧相对操作流 0、30、60、90、120 秒偏移，同时保留槽位身份一致的时间区间。只比较 0–5 槽中两侧都知道的身份；不比较数量/消耗，也不把操作重建当独立真值。

完整样本分别有 666/644/616/593/558 个可比槽位，冲突 241/181/85/79/96。分母不同，不能仅用冲突数选偏移。进一步限制到五个方案都知道、每关键帧至少三个槽位的共同集合：

| 偏移（秒） | ≤420 秒：110 个槽位中的冲突 | >420 秒：428 个槽位中的冲突 |
| --- | --- | --- |
| 0 | 44 | 124 |
| 30 | 34 | 100 |
| 60 | 18 | 55 |
| 90 | 20 | 49 |
| 120 | 28 | 64 |

有滞后相关迹象，但前后段最优不同，仍存在大量反例；不能宣称“统一减 60 秒就解出了背包”。三份短回放没有可比槽位，不记为匹配成功。全部逐包、逐槽反例和相容时间区间在 `data/private/integration/inventory_time-v2.json`，未修改任何原始时间。

## 刷野来源尝试及实际缺口

已通过网页检索读取 [历史剑圣作者攻略](https://www.mobafire.com/league-of-legends/build/12-9-complete-guide-to-yi-pathing-builds-runes-etc-602700)：其红开全刷路线标注 3:15，并指向演示视频；这不是已经观察到的经过时长，正文也不能绑定视频的完整条件与结束生命/资源。项目 HTTP 抓取返回 403，离线重读为 cache_miss，这两次状态分别保留。

[潘森演示入口](https://www.youtube.com/watch?v=we4j2iJe9HM) 的 web.open 返回 Cache miss；浏览器控制工具因本地运行环境失败未能展示。随后只抓取公开 HTML 成功（HTTP 200），但播放器元数据为 LOGIN_REQUIRED，videoDetails 为空。没有观看、没有下载视频、没有记录其结束状态。网页可访问不等于实测已完成。

因此本轮条件完整刷野记录新增 **0**。新候选文件 `data/knowledge/clear_candidates_int001-v2.json`，首次访问失败保留于同目录无 v2 文件及来源尝试缓存。仍缺：实测绑定的符文/装备/加点/惩戒/操作条件、起止定义、结束位置/等级/生命/资源。旧版本指南不直接套用于当前版本。

## 尚未解决与交接边界

地图/模式的运行时身份，小兵/营地/水晶等对象的完整身份与状态，实际施法/取消/冷却，库存撤销与消耗，眼及区域视野，条件完整动作记录与广泛阵容规则仍不足。原 RPL-005 的创建字段、技能族和旧眼位协议失败保持有效，没有因本次整合而变成已解。

F06 所需统一入口已经有可运行实现；F04 的完整刷野记录和一般动作模型仍缺，因此整个基础阶段与完整自动复盘不能判通过。没有需要用户重录移动、开游戏或提供密钥的当前动作；未解协议项保留具体反例供后续研究，不把重复运行当破解。

## 输出与复现

工作目录 `D:/1/yxlm/lol-coach`。输出必须选新文件名；示例中的 review-* 若已存在请换名。

```powershell
.venv/Scripts/python.exe scripts/analysis.py context --replay-id HN1-11360086609 --at 400 --team 100 --player 0x40000034 --output data/private/analysis/review-400.json
.venv/Scripts/python.exe scripts/analysis.py timeline --output data/private/analysis/review-timeline.json
.venv/Scripts/python.exe scripts/analysis.py travel --points '[[1636,3068],[2898,3590]]' --speed 575 --audit-map11 --output data/private/analysis/review-travel.json
.venv/Scripts/python.exe scripts/build_analysis_example.py --snapshot data/private/analysis/review-400.json --output data/private/analysis/review-comparison.json
.venv/Scripts/python.exe scripts/research_inventory_time.py --output data/private/integration/review-inventory-time.json
.venv/Scripts/python.exe scripts/collect_clear_candidates.py --offline --output data/knowledge/review-clear-candidates.json
```

最终实际输出：`data/private/analysis/final-400-team100.json`、`final-400-team200.json`、`final-short-30.json`、`movement-timeline.json`、`travel-map11.json`、`conditional-comparison-400.json`，均附同名 Markdown；统一入口另附 manifest。原材料和旧验收文件未覆盖。恢复点 `reports/analysis_integration_baseline/manifest.json`。
