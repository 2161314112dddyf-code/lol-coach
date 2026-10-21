# RPL-004 信息收集执行报告

目标回放构建 16.20.824.8524；官方基础数据 16.20.1；内部公共资料路径 16.20。这些版本分别记录，不把补丁目录当成精确构建兼容证明。开发自检 Codex；人工验收、独立复核未执行；费用和 Token 未取得。恢复点 world_collection_baseline/manifest.json。

## 实际新增

| 信息 | 产物与真实结果 | 边界 |
| --- | --- | --- |
| 全英雄基础 | data/normalized/16.20.1/en_US/catalog，173/173；173 被动、692 QWER；离线重建及内容哈希核对通过 | 原始机制描述，不是已验证的全英雄交互模型 |
| 静态技能参数 | ability_parameters.json；runtime_mechanics_reference.json，17 来源、357 内部对象 | 冷却/消耗/距离保留来源值和公式；不推算本局等级、急速或可用性 |
| 技能活动 | data/private/spell_activity，整局 2,296，训练 11；共 2,307，尚未解 475 包 | 95 名词表、116 字节关系；new_cast/目标/等级/冷却为空；阶段辅助效果分列 |
| 背包重同步 | data/private/inventory_sync，6 包、38 物品观察，32 能命名 | 六个特殊槽位物品未知；不能用没列出的槽位推断空位，不能声明完整背包 |
| 非英雄状态研究 | data/private/world_objects，保存出生结构、候选生命、路径起点、英雄移速候选 | 英雄与非英雄布局分开；未识别名字/阵营/建筑目标；不进入时刻可知状态 |
| 兵线参考匹配 | early_wave_reference_fit.json，前五波 32 对/64 个对象 | 数量、间隔、生命成长联合拟合；不是地图/模式 ID 解码，阵营未知 |
| 真人经验 | data/knowledge/human_decision_cases.json，两张条件经验卡，正文与哈希缓存，离线重建通过 | 历史作者主张；当前版本适用性待判断，没有实测耗时 |

技能的正向例子：死歌 Q 205 次活动与结算一致；婕拉 Q/W/E/R 为 89/92/45/8，剑圣为 28/27/23/6，逐项一致。烬 R 有启动名与逐发子弹名，瑞兹 Q 有 Wrapper 与后续名，小法 W 有 CastLockout 辅助名。保留这些差别，不机械求和为一次次施法。整局 40 个 QWER 汇总对照为 21 PASS / 19 INSUFFICIENT_EVIDENCE；没有把缺项抹成零。汇总只核对数量，不能单独证明每条活动成功完成。

婕拉 R 与 P 的部分哈希存在歧义，用 8 个候选时间中 7 次约 100 的资源扣减，对照静态 R=100/P=70，形成校准。另一条没有资源扣减，仍保留活动，不声明施法完成。训练潘森 3 次 Q 主活动另有 6 条跟随活动，同样不当作 9 次 Q。

瑞兹 430.608/430.809 秒附近的同步可看到成装与恢复的散件；430.642/430.842 秒当前金币增加 300/650。协议中的交易原因尚未解码，这组数据支持撤销/恢复解释，不把所有同步都称为购买。六次同步不能修复所有消耗或缺失槽位。

Map12 公共配置含首波 45 秒、波间隔 25 秒、同波单位间隔约 0.8 秒及生命成长；与早期候选相符。第五波附近另有两只 400 生命候选，未混入兵线匹配，单列 other_pair_candidates。Map12 仅用于识别对照，原已冻结 Map11 基础未替换，本局地图编号仍未知。

两张经验卡的原始依据：[Santorin 的阵容条件与发育/反蹲建议](https://dignitas.gg/articles/the-big-three-jungle-concepts-with-santorin)（2023-11-27），[Fordola 的兵线机会案例](https://dignitas.gg/articles/how-to-set-up-effective-jungle-ganks)（2021-11-17）。卡片明确区分作者条件与项目需要收集的局势字段，不冒称主播逐帧视频标注或当前版本定理。

## 真正运行的检查

- `scripts/collect_champion_catalog.py --offline`：173/173，0 失败；`build_ability_reference.py` 核对 173 份官方原始内容、173 份规范化结果与 17 份内部来源哈希。
- `scripts/verify_world_collection.py`：四份回放共 2,313 个新增事件原包重解码；198 条实际装备更新的新尾部读法与旧前向解析吻合；12 次活动前缀检查通过；10 人初始移速与官方基础值一致。四份源回放哈希前后不变。
- `scripts/crosscheck_wave_reference.py`：前五波数量/间隔/成长参考匹配 5/5；仅说明这个有限参考拟合成立，不代表世界对象验收完成。
- `scripts/collect_human_cases.py --offline`：两份正文片段存在，缓存哈希有效；完整刷野实测数量仍为 0。
- `.venv/Scripts/python.exe -m pytest -q --basetemp=data/tmp/pytest-world-20261019-a --junitxml=reports/pytest-world-collection.xml`：**240 passed in 1.30s**，18 项新增；测试包括真实包回归和合成边界，不能代替游戏语义证据。再次运行请使用尚不存在的新临时目录。

真实结果见 world_collection_real_validation.json、ability_reference_validation.json、wave_reference_validation.json、human_case_collection.json；源包与来源保存在对应产物。首次退款对照窗口失败、低频字节误配和来源 404 见 world_collection_attempt_failures.md；没有删除失败历史。

## 修改与复现

新增模块：lol_coach/spell_activity.py、lol_coach/inventory_sync.py；冻结技能 profile。新增导出/研究/构建/核验脚本：export_spell_activity.py、export_inventory_sync.py、research_spell_hashes.py、research_runtime_spells.py、research_world_objects.py、collect_champion_catalog.py、build_ability_reference.py、freeze_spell_activity_profile.py、crosscheck_wave_reference.py、collect_human_cases.py、verify_world_collection.py；新增 tests/test_world_collection.py。更新 README、CURRENT_TASK、STATUS。完整修改与产物哈希见 world_collection_run.json。

正常离线重跑命令见 README 顶部。不必重新拟合字节表；冻结 profile 即可导出。来源缓存缺失时明确失败；新来源收集才需联网。原回放、游戏客户端、父目录已审核解码器与既有快照模块未修改。

## 未完成项

W-01 对象身份与 W-02 完整兵线/建筑/目标状态仍不足。W-03 的有限具名活动和槽位观察已有正向成果，但完整施法、取消、冷却、重置、目标、装备消耗仍不足。W-04 保守隔离与时间截断通过；W-05 静态来源通过，条件完整动作耗时与经验在当前版本的应用尚不足。F-01 全目录资料已实际补齐，不能据此宣布 F-01–F-06 整体完成。

接续入口是已保存的非英雄创建族/分类复制布局及未解技能包，并把名字、阵营、状态和可见性连起来。区域迷雾/眼位仍缺，不能把英雄可见性扩写成全地图视野。当前没有需要用户启动游戏或重新补录的阻断。
