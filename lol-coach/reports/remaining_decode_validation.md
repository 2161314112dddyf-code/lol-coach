# RPL-005 集中解码与未解项报告

2026-10-20；目标 16.20.824.8524；执行主体 Codex。用户要求集中处理全部剩余项，范围与验收见 docs/REMAINING_DECODE_TASK.md。完整剩余结果见 remaining_decode_matrix.md；整体 INSUFFICIENT_EVIDENCE，不声明完整游戏理解。恢复点 reports/remaining_decode_baseline/manifest.json。

## 已落地

1. 背包族解析新增固定封装的省略记录、16种已观察外层封装、扩展前后缀和一个短局扩展头。只剥离有真实样例支持的边界，不解释扩展值。138项有限物品表完全由原有65个物品标签确立的69个字节对应导出，没有新增猜测字节；回城2001和禁用回城2007在其内。
2. 英雄 group 4：bits 0–2为变长整数，其余为压缩float；group 8：bits 0–28为float、29–31为整数。仅在既有英雄目录中的对象使用，不能套到非英雄。所有数据严格消费至组末，字段偏移/原字节保留。六个候选标签：基础攻击力bit3、护甲7、魔抗8、攻击距离11、额外攻击力12、法强14；这些是候选字段语义，不是完整属性公式。
3. 已命名敌塔视野：136条真实消息（70进入、66离开），所有已观察的单对象/观察队伍通道严格交替，观察队伍与解码塔名所属队伍相反。复用既有观察码映射，提供 enemy_tower_view；不在名称首次解出前输出身份，只接实时流生命采样，隐藏后清当前值、重见不挪用历史样本。查询0/119/120.1/300/400/753/841秒、两队，共14个前缀检查。可见标志不代表塔未被摧毁或仍可战斗；本函数没有由可见性推断存活。

|回放|背包族包|槽位记录（含空）|省略记录|属性组|数值字段|
|---|---:|---:|---:|---:|---:|
|11360086609|156|1505|33|5249|23112|
|11363048522|1|9|1|40|183|
|11363093470|2|18|2|7|151|
|11372643015|1|9|1|5|87|
|合计|160|1541|37|5301|23533|

以上1,541条包括38条旧实时记录，新读取1,503条关键帧槽位。160包中154关键帧、6实时。字段与记录重复采样不能当作不同物品或不同属性数量。

## 关键反例与更正

- 背包族 **不是已证实的当前库存**：预测与载荷1,088项相同、299项不同。例如Aphelios在60.029秒的槽位记录仍含空槽，而已解实时购买记录显示此前已买装备；120秒又出现旧装备状态。缓存/撤销语义尚未确认，不能简单平移60秒，也不能把差异都称为消耗。effective_inventory_time=null、decision_input_eligible=false。此前RPL-004对38条记录的读取正确，但其当前库存含义未获证实；旧产物保留，统一索引已加入更正。没有借助这一批数据“修补”macro_snapshot当前背包。
- 初始静态属性36/40相同。Aphelios攻击距离650对官方基础550；MasterYi/Kayle/Fizz魔抗分别47/37/47对32/22/32。保留差异，不自动解释成模式、武器或符文。
- 孤立基础物品购买（±0.3秒无其他同英雄操作）38项属性增量对照：36 PASS、2 FAIL；2次爆裂魔杖静态+45而观察+54。反例和前后源包保留，未在缺少证据时填入20%加成解释。
- 出生ID新尝试：38组既有暂定关联，u32LE/LEB128按原样与已有replication字节表共152次搜索，0命中；spell-hash表不能编码所需字节的76次明确未执行。没有训练一张新表来迎合预设ID。
- 技能0x360邻接：1,062条对应唯一活动名字、1,419无名、251多名，因此不能当作新施法计数。0x2b6的12槽候选族1,800条仅关键帧，未观察实时更新，不能声称实时冷却。具体包与反例在数据目录和gap_analysis中。
- 全局非英雄通道有大量重复进入；将已知塔独立检查才获得严格交替。未将塔结果外推给眼/区域。旧16.15眼位profile只用于版本和前缀比对，本局前缀0命中，没有执行旧客户端或声称兼容。
- 初次背包扩展扫描只覆盖e8边界，会错误包含e9的下一条记录；扩大边界后仍要求固定数量、封装白名单和槽位有序唯一，所有实际包满足。首次批量导出还拒绝短局60秒的扩展头，原错误在remaining_decode_attempts.json保留，新增限定格式后重跑通过。一次UTF-8源以GBK读取失败，修正显式编码，源文件未变。

## 检查与验收

- R5-01 PASS（集中尝试/清单范围）：各类实际尝试和剩余原因齐备，详见矩阵；不表示这些字段全部解出。
- R5-02 PASS（原包读取范围）：1,541条槽位与23,533个数值逐包、偏移和独立数值读取核对；既有38条实时槽位/编码一致，四份源哈希不变。语义对照含上述FAIL，整体语义目标INSUFFICIENT_EVIDENCE。
- R5-03 PASS（隔离/塔过滤范围）：所有新研究载荷不可直接作决策输入；塔过滤14个前缀检查，软件覆盖未来身份、同帧隐藏、重见清空、异源与版本边界。未将原始研究值接入macro_snapshot。
- R5-04 PASS（可复现交付范围）：统一离线入口、文件清单、恢复点、状态和报告已保存。

实际 `.venv/Scripts/python.exe -m pytest -q --basetemp=data/tmp/pytest-remaining-20261020a --junitxml=reports/pytest-remaining-decode.xml`：**284 passed in 1.55s**，新增18项synthetic边界测试。临时目录首次执行前确认不存在，重跑应选新目录名。原包核对JSON为remaining_decode_real_validation.json，敌塔另见tower_vision_validation.json。软件PASS不覆盖未解字段，未执行独立UI核验、人工签署或外部复核。

## 文件与复现

新增模块：lol_coach/replay_extensions.py、lol_coach/tower_vision.py；profile：lol_coach/profiles/inventory_checkpoint_items_16_20.json。新增脚本：collect_remaining_decode.py、analyze_remaining_gaps.py、verify_remaining_decode.py、export_tower_vision.py、run_remaining_decode.py。新增测试：test_replay_extensions.py、test_tower_vision.py。修改README、CURRENT_TASK、STATUS、信息索引生成器及其产物；任务卡和报告同列于remaining_decode_run.json。

```powershell
.venv/Scripts/python.exe scripts/run_remaining_decode.py
.venv/Scripts/python.exe scripts/build_information_catalog.py --catalog-only
```

统一入口四项已完整实际运行成功（收集、缺口分析、原包核对、敌塔视野），随后索引更新为15类。输出data/private/remaining_decode、data/private/tower_vision及reports下JSON；只读原始回放，不联网、不启动游戏。400秒敌塔样例已经生成，两个队伍各一份。无法确认的字段留空，当前无必须用户接手步骤；不索取新视频作为已完成移动的追加验收。费用与Token统计未取得。
