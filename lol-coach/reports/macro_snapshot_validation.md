# SNAP-001 实施与检查

日期 2026-10-19；目标版本 macro-snapshot/v1；实施和自检执行者 Codex。source=target_claim，evidence_level=REPRODUCED；不是独立复核或人工签署。

| 验收 | 结果 | 证据 / 范围 | 缺口 / 下一项 |
| --- | --- | --- | --- |
| SNAP-01 | PASS | 真实 400 秒/100 队 CLI 输出十名英雄、77 条证据；四类数据统一，双方关系和行动比较契约齐备 | 部分输入结构，不是完整战术结论 |
| SNAP-02 | PASS | 21 项新增 synthetic 软件检查；真实 7 次查询删除未来事件、污染结算后输出保持一致；212 个观测采样核对时刻/视野 | 沿用原解码语义，无独立 UI 认证 |
| SNAP-03 | PASS | 隐藏/未知当前值置空；背包保持 unknown；只开放本人私有经济，路径仅首点候选；训练未知阵营不升级为队友 | 未知内容仍需后续真实证据 |
| SNAP-04 | PASS | 全套 222 passed in 1.18s；不同源/构建/不足前缀/非法 t 负例通过；四份真实源 SHA256 前后不变；实际 CLI 成功 | 无新的客户端/版本通用性声明 |
| SNAP-WORLD | INSUFFICIENT_EVIDENCE | world/composition/skill 字段明确未知 | 地图/目标/兵线/完整视野、技能、背包、机制和经验继续接入；不要求补录 |

证据 ID：软件=`reports/pytest-macro-snapshot.xml`；真实=`reports/macro_snapshot_real_validation.json`；样例=`data/private/macro_snapshots/HN1-11360086609-team100-at400.json`；版本与文件哈希=`reports/macro_snapshot_run.json`。各验收 signer=null。

## 真实执行

```powershell
.venv/Scripts/python.exe -m pytest tests/test_macro_snapshot.py -q -p no:cacheprovider --basetemp=data/tmp/pytest-macro-20261019-a
# 21 passed in 0.06s
.venv/Scripts/python.exe scripts/verify_macro_snapshot.py
# 7 queries, 212 observed samples, PASS; 4 sources unchanged
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=data/tmp/pytest-macro-full-20261019-a --junitxml=reports/pytest-macro-snapshot.xml
# 222 passed in 1.18s
.venv/Scripts/python.exe scripts/export_macro_snapshot.py --replay-id HN1-11360086609 --at 400 --team 100 --player 0x40000034 --output data/private/macro_snapshots/HN1-11360086609-team100-at400.json
# 10 actors, 77 evidence references
```

上述临时目录已经使用，复跑 pytest 应换一个不存在的目录；CLI 也会拒绝覆盖已有产物。文档提供的新示例文件名可直接使用。

## 取舍与实际发现

保留原解码层，新增一个确定性聚合入口。单纯把四份全量导出直接拼接会带入隐藏敌方经济、结算装备和未来区间结束；因此选择按包顺序做知识过滤，只把最终使用的观测登记到 evidence。来源文件哈希留在旁路 manifest。

队伍公开信息与本人私有信息分开。未建立敌方装备观察语义时不以“英雄可见”自动允许读取全知背包操作。背包无法完整恢复时只列近期本人操作及断点，不猜一套槽位。

400 秒样例揭示可见通道不等于可参战：Fizz 最近生命样本为 12.17 秒前的零。结构保留时间、公共死亡和原通道，禁止由可见人数直接推导兵力优势；技能/特殊死亡机制尚未接入。

环境记录：首次读取宪法误用了项目根路径，实际文件在 docs/PROJECT_CONSTITUTION.md，已纠正阅读；首次普通沙箱创建恢复目录被 Windows 拒绝，随后同一项目内备份以工具审批运行成功。没有自动审批拒绝，无数据/测试失败被改称通过。

恢复点 reports/macro_snapshot_baseline/manifest.json 保存 README/CURRENT_TASK/STATUS 原文；新增文件按 run 清单逐项核对恢复，不能整目录覆盖。未修改原回放、客户端或原四类解码器。没有调用模型、上传或产生已知费用；费用/Token unknown。人工预测、人工验收签署、独立复核未提供/未执行。
