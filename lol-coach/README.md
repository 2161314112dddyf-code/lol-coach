# LoL Coach 赛后复盘数据基础

当前入口（2026-10-21，INT-001）：统一离线分析已经接通。本局十人、50 个被动/技能来源、3 条匹配阵容的条件交互、2 张历史经验卡，以及已命名敌塔的可知生命，进入原有时刻快照。另可导出既有行动时间线、查询条件耗时和真实地图网格。四回放 9 次真实查询通过前缀检查，最终 **336 项软件测试通过**。完整背包、技能冷却、区域视野及条件完整刷野记录仍缺；[交付和反例](reports/analysis_integration_validation.md)。

```powershell
.venv/Scripts/python.exe scripts/analysis.py context --replay-id HN1-11360086609 --at 400 --team 100 --player 0x40000034 --output data/private/analysis/review-400.json
.venv/Scripts/python.exe scripts/analysis.py timeline --output data/private/analysis/review-timeline.json
.venv/Scripts/python.exe scripts/analysis.py travel --points '[[1636,3068],[2898,3590]]' --speed 575 --audit-map11 --output data/private/analysis/review-travel.json
.venv/Scripts/python.exe scripts/build_analysis_example.py --snapshot data/private/analysis/review-400.json --output data/private/analysis/review-comparison.json
```

在本项目目录运行，输出需使用新文件名。需要本地已有回放导出与来源缓存；公开仓库不包含私人录像、回放或客户端资产。context 缺配套塔视野或短回放英雄身份未解时仍输出已知部分。历史验证与入口如下。

当前入口（2026-10-21，MECH-001）：新增潘森 P/Q/W/E/R 五张来源卡、潘森与烬的配合案例、潘森面对莫甘娜黑盾的限制案例及离线三值条件查询。三份官方 16.20.1 缓存、13 处来源指针已核对；6 种合成情景实际运行；全套 **311 项测试通过**。这是有来源的条件推论，不是回放中技能/黑盾状态已解。运行方式与范围见 [机制报告](reports/pantheon_mechanisms_validation.md)。

项目概览见 [阶段总结](docs/PROJECT_SUMMARY.md)，所需信息见 [分析清单](docs/ANALYSIS_INFORMATION_REQUIREMENTS.md)。以下保留历史入口与证据，不把历史缺口描述当作最新状态。

当前入口（2026-10-20，RPL-005）：集中处理剩余解码。新增 **1,541 条背包槽位载荷、23,533 个英雄属性数值字段，以及已命名敌塔的 136 条视野消息和过滤查询**。实际 284 项测试通过。全部未解项与原因统一列在 [剩余矩阵](reports/remaining_decode_matrix.md)，文件、验收和反例见 [报告](reports/remaining_decode_validation.md)。

```powershell
.venv/Scripts/python.exe scripts/run_remaining_decode.py
.venv/Scripts/python.exe scripts/build_information_catalog.py --catalog-only
```

以上仅使用已缓存素材。**槽位载荷不等于当前背包**：与装备操作对照发现 299 处冲突，缓存/撤销语义尚未解明，相关有效时间为 null。英雄属性六个标签仍为候选；敌塔视野是限定版本二进制推断，未代表完整地图视野。已有 [100 队在 400 秒看到的敌塔](data/private/tower_vision/HN1-11360086609-team100-at400.json) 和 [200 队样例](data/private/tower_vision/HN1-11360086609-team200-at400.json)。旧成果保留如下，若与新报告冲突，以新报告披露的限制为准。

当前入口（2026-10-19，RPL-004C）：新增结构对象研究导出，四份回放 **48 个候选对象、186 条生命采样、55 条状态观察**；一个水晶摧毁相关事件链与零血量及结算次数吻合。**266 项软件测试通过；小兵/水晶/基地完整身份仍未解出。** 阵营、路线、复活和非英雄可见性保持未知，研究产物不直接交给时刻决策。详见 [报告](reports/structure_evidence_validation.md)。

```powershell
.venv/Scripts/python.exe scripts/verify_structure_evidence.py
.venv/Scripts/python.exe scripts/export_structure_evidence.py --replay 'C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl' --at 833.45 --output data/private/structure_evidence/example-at833.45.json
.venv/Scripts/python.exe scripts/build_information_catalog.py --catalog-only
```

核对脚本重建四份导出与三个时刻样例，无需游戏运行。测试可用 `.venv/Scripts/python.exe -m pytest -q --basetemp=data/tmp/pytest-structure-fresh`，临时目录须为尚不存在的新目录。本轮使用的命令和失败过程见报告。

当前入口（2026-10-19，RPL-004B）：新增 **10 座防御塔身份/阵营/角色、508 条生命采样、4 次摧毁事件**。254 项软件测试通过，整体信息收集仍未完成。塔状态暂为事后前缀，非英雄视野未核验；完整范围见 [报告](reports/world_identity_validation.md) 和 [状态](reports/STATUS.md)。

```powershell
.venv/Scripts/python.exe scripts/export_turret_state.py --replay 'C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl' --output data/private/turret_state/HN1-11360086609.json
.venv/Scripts/python.exe scripts/verify_turret_state.py
.venv/Scripts/python.exe scripts/build_information_catalog.py --catalog-only
```

已有 [400 秒塔状态样例](data/private/turret_state/HN1-11360086609-at400.json)。Map12 静态对象关联不等于运行时地图/模式编号，地图参考坐标不自动接入 Map11 路网。以下保留此前入口及运行方法。

当前入口（2026-10-19，RPL-004）：继续收集大局观基础，已增加全英雄静态目录、技能名活动、背包同步、世界对象研究与真人经验卡。**240 项软件检查通过；整体信息尚未收齐。** 详细成果和缺口见 [本轮报告](reports/world_collection_validation.md) 与 [状态](reports/STATUS.md)。

在本项目目录运行；以下命令只读已有回放，重建本轮派生结果，无需启动游戏：

```powershell
.venv/Scripts/python.exe scripts/export_spell_activity.py
.venv/Scripts/python.exe scripts/export_inventory_sync.py
.venv/Scripts/python.exe scripts/research_world_objects.py
.venv/Scripts/python.exe scripts/crosscheck_wave_reference.py
.venv/Scripts/python.exe scripts/collect_champion_catalog.py --offline
.venv/Scripts/python.exe scripts/build_ability_reference.py
.venv/Scripts/python.exe scripts/collect_human_cases.py --offline
.venv/Scripts/python.exe scripts/verify_world_collection.py
.venv/Scripts/python.exe scripts/build_information_catalog.py
```

导出绑定现有四份文件和精确构建；技能活动不等于独立施法，静态冷却不等于实时可用，缺失背包槽位不等于空。world_objects 的类型推断及新活动尚未通过可知性接入，不能直接当作智能体当时知道的事实。以下为已实现快照入口。

统一收集索引：data/knowledge/macro_information_catalog.json，逐类列出文件哈希、证据等级、使用边界与未收齐项；不是把所有原始数据直接交给智能体的决策包。

当前入口（2026-10-19，SNAP-001）：将已有四类解码结果合并为指定时刻、指定队伍的 `macro-snapshot/v1`。包含双方阵容、可见期间采样、历史观测、位置候选、近期击杀、可选本人经济/装备操作、基础缺口和行动比较契约。详见 [结构说明](docs/MACRO_SNAPSHOT.md) 与 [真实 400 秒样例](data/private/macro_snapshots/HN1-11360086609-team100-at400.md)。

```powershell
.venv/Scripts/python.exe scripts/export_macro_snapshot.py --replay-id HN1-11360086609 --at 400 --team 100 --player 0x40000034 --output data/private/macro_snapshots/example-team100-at400.json
```

在项目根目录执行，输出文件名必须尚不存在；生成 JSON、中文摘要、输入哈希清单。省略 `--player` 不开放私有经济。无需游戏、网络或密钥。实际全套 **222 项测试通过**，四份真实回放 **7 次查询、212 个观测采样**通过集成检查；见 [本轮报告](reports/macro_snapshot_validation.md)。完整世界状态、背包与技能、机制/经验接入仍未完成。

## 历史增量：英雄视野

当前增量（2026-10-19，RPL-003D）：已实现指定英雄进出对方视野通道，整局 1209 条、四份共 1213 条；支持按队伍/时刻查询并过滤隐藏期间的状态值。方向与阵营为出生/复活/位置交叉对照的二进制推断，未做独立 UI 核对。区域迷雾、眼位、非英雄与隐身/真视仍缺。见 [视野报告](reports/replay_vision_validation.md)。

在 `D:/1/yxlm/lol-coach` 离线运行：

```powershell
.\.venv\Scripts\python.exe scripts\export_replay_vision.py --replay "C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl" --output data\private\replay_vision\HN1-11360086609.json
.\.venv\Scripts\python.exe scripts\export_replay_vision.py --replay "C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl" --output data\private\replay_vision\HN1-11360086609-team200-at41_1.json --at 41.1 --team 200 --state data\private\replay_state\HN1-11360086609.json
.\.venv\Scripts\python.exe scripts\verify_replay_vision.py
```

`--at` 与 `--team` 配对使用；`--state` 可选，须是同一回放的完整动态状态导出。初始视野 unknown；不可见时 current_observed=null，last_observed 仅是历史观测，不更新为隐藏后的数值。可见也不输出敌方金币、经验或计划路径。过滤支持是局部能力，完整战术输入仍未整体解锁。实际 201 项软件测试通过，详细真实数据对照与范围见报告。

上一增量（RPL-003C）：新增带源字节定位的装备操作流。整局 336 条操作、65 种物品编码；四份回放共 347 条。装备撤销/消耗和技能释放仍有缺口，不能宣称完整背包或完整动态理解。见 [装备解析报告](reports/replay_inventory_validation.md)。

在 `D:/1/yxlm/lol-coach` 离线运行：

```powershell
.\.venv\Scripts\python.exe scripts\export_replay_inventory.py --replay "C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl" --output data\private\replay_inventory\HN1-11360086609.json
.\.venv\Scripts\python.exe scripts\export_replay_inventory.py --replay "C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl" --output data\private\replay_inventory\HN1-11360086609-at50.json --at 50
.\.venv\Scripts\python.exe scripts\verify_inventory_economy.py
.\.venv\Scripts\python.exe scripts\verify_replay_inventory.py
```

`events` 是槽位更新、移除、换位，不自动推断购买/出售原因。`state_barriers` 列出尚未解码的重同步候选；完整物品栏、数量、特殊物品未知项保持明确。训练回放的 8 条特殊物品更新没有硬填 ID。最终背包参与部分物品字节校准，经济独立核对 165 个区间通过、14 个证据不足、2 个失败。软件测试实际 182 项通过，失败与修正经历见报告。`verify_replay_inventory.py` 会读取已生成的经济报告和测试 XML，不会冒充再次运行 pytest。

上一增量（RPL-003B）已恢复生命、资源、当前/累计金币动态状态；实际核对见 [状态解析报告](reports/replay_state_validation.md)。历史失败研究保留在 [前轮报告](reports/replay_dynamic_validation.md)。

在 `D:/1/yxlm/lol-coach` 离线运行（无需开游戏、密钥或联网）：

```powershell
.\.venv\Scripts\python.exe scripts\export_replay_state.py --replay "C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl" --output data\private\replay_state\HN1-11360086609.json
.\.venv\Scripts\python.exe scripts\export_replay_state.py --replay "C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl" --output data\private\replay_state\HN1-11360086609-at50.json --at 50
.\.venv\Scripts\python.exe scripts\verify_replay_state.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-state --junitxml=reports/pytest-replay-state.xml
```

该入口限定四份已登记文件及完整构建 `16.20.824.8524`。输出包含实体、原包时间/偏移、数值与单位；资源类型未知，状态更新可包含重复快照。`--at` 只保留截止前最后一次已同步值，不插值、不使用结算或未来信息。视野未解出，仍禁止把敌方状态当成当时已知信息。旧十类导出入口尚未合并这些字段，使用上述新入口读取动态状态。

字节表推导可用 `scripts/research_state_bytes.py` 重运行；它依赖原回放和既有父目录分包器，不依赖客户端二进制。`scripts/audit_replay_dynamic.py` 是前轮失败尝试的审计入口，不是本轮状态解析器。

已实现公开入口探测、缓存、显式补丁英雄规范化，以及本地地图资产提取、网格解析和离线测试。英雄模块只依赖 Python 标准库；地图模块另需 requirements-map.txt。不需要密钥。要求 Python 3.11+；本机 `.venv` 使用 Python 3.13.7。

PowerShell 实际命令：

```powershell
Set-Location D:\1\yxlm\lol-coach
.\.venv\Scripts\python.exe -m lol_coach versions
.\.venv\Scripts\python.exe -m lol_coach audit-sources
.\.venv\Scripts\python.exe -m lol_coach fetch-champion --patch 16.20.1 --champion Ivern
.\.venv\Scripts\python.exe -m lol_coach --offline fetch-champion --patch 16.20.1 --champion Ivern
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-local
.\.venv\Scripts\python.exe scripts\verify_real_sample.py
.\.venv\Scripts\python.exe scripts\verify_entries.py
```

新环境先运行 `python -m venv .venv`，再运行 `.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements-map.txt`。本机创建环境使用明确路径 `D:\py\python.exe`，避免提权进程 PATH 指向其他 Python。无需全局安装或安装本包。

`--offline`、`--refresh` 在子命令前。默认复用哈希核验的缓存，缓存不自动过期；需要新结果时使用 `--refresh`。`--offline` 绝不联网；缓存缺失则返回失败。`versions` 展示前 20 项；英雄补丁必须在版本列表内，中文可加 `--locale zh_CN`。

常规 HTTP 超时 12 秒、最多 2 次尝试、请求开始间隔至少 0.4 秒，重试退避 0.5 秒。401/403/429 不重试或绕过。默认上限 8 MB；地图配置已检查目录大小（JSON 约 9.2 MiB），地图流程专用上限 16 MB、超时 25 秒。超限不作为完整原始证据保存。

产物：

- `data/raw/<sha256>.bin` 保存原始响应，包括失败响应；`data/attempts/` 保存尝试、错误与 UTC 时间；`data/cache/` 是 URL 哈希索引。缓存命中保留原抓取时间。
- `data/normalized/16.20.1/en_US/Ivern.json` 与 `.manifest.json` 保存规范化字段、来源与版本列表证据。
- `reports/source_audit.md` / `.json` 保存候选入口 HTTP 探测；`entry_evidence.json` 与 `source_verification.md` 保存固定提交代码、许可及人工核验结论。
- `reports/pytest.log` / `pytest.xml` 是合成离线单元测试结果；`real_sample_smoke.json` 是真实下载静态样本的独立核验。
- `docs/clear_measurement_template.json` 是空实测模板，所有未知值为 null，不能当作实测。

缓存与原始证据默认被 `.gitignore` 排除但在本地保留；交接结果时须一并转交。原始技能描述不等于已核验机制；基础移速不等于本局移速。目标客户端版本、队友/对手交互仍未验证。本轮未做寻路、回放解析、动作耗时推算、前端或模型训练。详见 `reports/STATUS.md`。

## 第二轮：真实地图资产

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-map.txt
.\.venv\Scripts\python.exe -m lol_coach extract-map --game-dir 'D:\WeGameApps\英雄联盟\Game' --patch 16.20 --skin Default
.\.venv\Scripts\python.exe -m lol_coach --offline extract-map --game-dir 'D:\WeGameApps\英雄联盟\Game' --patch 16.20 --skin Default
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --x 7500 --z 7500
.\.venv\Scripts\python.exe scripts\verify_real_map.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-local
```

提取只读本地 Map11.wad.client；通过版本化公开地图配置的 BIN 哈希匹配和 JSON 引用选择资产，证据写入 data/private/map-assets/，网格与预览写入 data/maps/16.20/Default/。离线提取要求此前缓存过该版本公开配置；坐标查询只需要已有项目数据。

`grid.json` 保留按 Z 行升序的原始 flags，`base_flags.png` 逐格渲染（+Z 向上），白色表示静态开放候选、深灰表示阻挡候选、绿色为草丛候选、蓝色为阵营限制。图中没有应用 overlay。8 份 overlay 逐区域解析并保留未知尾字节，暂不合成。

Default 是显式选择的配置对象，不代表已经确认本局实际地图皮肤。query-map 的 actual_passability 保持 null，不能据此计算实际路径耗时。格式说明见 docs/MAP_FORMAT_NOTES.md，真实核验结果见 reports/map_validation.md、map_smoke.json，测试见 reports/pytest-map.log。

## 第三轮：本局日志与校准准备

已从 HN1-11363093470 对应的原始日志确认 Default 皮肤和安装 build；适用范围仅该局。地图 ID、活动 overlay、实际坐标及碰撞仍待核验。

```powershell
& .\scripts\run_calibration_audit.ps1
```

命令只读该局日志、原始回放和旧解码候选报告，检查哈希与版本/皮肤并生成 reports/calibration_audit.json。参数化入口为 scripts/audit_calibration.py（--help 可查看全部必填参数）。结果明确保持 needs_independent_visual_observations，不把计划点当实际到达、把记录间隔当行动耗时。

具体需录制的旧回放及核对时刻见 docs/CALIBRATION_HANDOFF.md；新增 tests/test_calibration.py，本轮总计 51 项离线测试通过。

## 出生基准与双导航引用审计

```powershell
.\.venv\Scripts\python.exe scripts\audit_map_context.py --offline
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --x 604 --z 612
```

首次缺少公开几何缓存时去掉 --offline（仍需原地图 bundle 和三份本地回放/旧 movement 报告）。当前脚本限定本机 Map11 16.20 Default 样本，原始回放不上传。

容器几何中的出生基准与已有出生候选支持泉水区域定位；皮肤 SRX_2 和容器 SRX_3 引用相异，4210 格 flags 不同。审计保留两份资产并更新 manifest，query-map 明示引用冲突和所查询资产，不决定运行时优先级。若重新运行 extract-map 生成 manifest，应再运行此审计；未经审计的查询会显示 container_reference_not_audited。

完整证据与限制见 reports/map_context_validation.md。本轮 61 项离线测试通过，不需要立即补录旧回放。

## 当前默认导航查询（更新）

默认选用 MapContainer 引用的 SRX_3，依据已检查的社区文档；旧的 SRX_2 保留供显式对照。下列步骤接在本地地图提取之后，取代旧版本直接查询 SRX_2 的流程：

```powershell
.\.venv\Scripts\python.exe scripts\audit_map_context.py --offline
.\.venv\Scripts\python.exe scripts\audit_map_rules.py --offline
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --x 604 --z 612
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --grid-source skin --x 604 --z 612
.\.venv\Scripts\python.exe scripts\verify_map_selection.py
```

规则或容器证据缺失时默认查询报错，不退回旧图。选择依据、实际查询资产和哈希随结果返回；runtime_observed=false，actual_passability=null，overlay 未应用。本轮 70 项离线测试通过，真实差异格 smoke 通过；详见 reports/map_rules_validation.md。

导航字段说明归属 [LoL Meta Wiki](https://meta-wiki.leaguetoolkit.dev)，CC BY-SA 4.0 with League Toolkit Developer Tooling Exception；[许可说明](https://meta-wiki.leaguetoolkit.dev/api/licensing/)。原文仅作为带来源的本地证据及开发工具依据，不代表游戏资产的分发许可。

## 十类回放信息导出（2026-10-14）

在项目根目录运行，输出同名 JSON 和 Markdown。六类配置/结算与四类时间序列明确分开，完整回放已覆盖十类；没有元数据的训练回放不会补造结算值。

```powershell
.\.venv\Scripts\python.exe scripts\export_replay_ten.py --replay 'C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl' --output data/private/replay_ten/HN1-11360086609.json
.\.venv\Scripts\python.exe scripts\export_replay_ten.py --replay 'C:/Users/21613/Documents/League of Legends/Replays/HN1-11360086609.rofl' --output data/private/replay_ten/HN1-11360086609-at50.json --at 50
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-replay-ten --junitxml=reports/pytest-replay-ten.xml
.\.venv\Scripts\python.exe scripts\verify_replay_ten.py
```

`--at` 只导出不晚于指定包时间的回顾性状态，不带入未来复活或结算数值；视野过滤尚未实现，不能作为玩家当时可知状态。只支持冻结客户端 16.20.824.8524，依赖已审查的父目录封装/移动解析器和字节表，不需要开游戏或密钥。

验证命令核对已生成的四份文件（11360086609、11363048522、11363093470、11372643015）、50 秒查询、父目录旧击杀/生命周期证据及测试 XML。其余三个文件重新生成时替换导出命令中的 GameID。完整结果、修改文件与缺口见 reports/replay_ten_validation.md；本轮最终 150 项软件测试、四份真实样本、三个 CLI 失败用例实际通过。

## 回放字段逆向（此前切片，2026-10-14）

基础 v0.1 范围已批准；用户指定优先逆向更多字段。新增等级候选导出，严格限定 16.20.824.8524。整局 150 条与十名英雄最终等级内部匹配，旧训练回放 12 条；其他两份移动回放无英雄升级事件。短回放英雄名称、生命/资源及技能字段仍未知。元数据结算值单独保存，不会回填成时刻 t 状态。

在项目根目录运行，无需密钥或打开游戏；需要现有项目环境和父目录已审查的 probe_packets.py：

```powershell
.\.venv\Scripts\python.exe scripts\extract_replay_fields.py --replay 'C:/Users/21613/Documents/League of Legends/Replays/HN1-11363048522.rofl' --output data/private/replay_fields/HN1-11363048522.json
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-replay-fields --junitxml=reports/pytest-replay-fields.xml
.\.venv\Scripts\python.exe scripts\verify_replay_fields.py
```

最后一条核对已生成的四份输出（GameID 11360086609、11363048522、11363093470、11372643015），需保留原文件。重新生成时逐一替换导出命令中的 GameID。结果及代码表适用边界见 reports/replay_fields_validation.md/json；本轮实际 126 项测试通过，等级解释仍标候选，未作为正式战术输入。

## 路径与艾翁基础证据（历史）

```powershell
.\.venv\Scripts\python.exe scripts\audit_replay_paths.py
.\.venv\Scripts\python.exe scripts\build_ivern_foundation.py
.\.venv\Scripts\python.exe scripts\verify_foundation.py
```

以上使用现有本地样本与核验过的缓存，无在线模型或 API 密钥。两份受控样本共 51 条候选记录与 SRX_3 没有基础阻挡接触；这是计划路径的静态相容性，不是实际走完路线的证明。新增艾翁五条机制卡及四条真人来源索引，实际耗时、结束状态和争议机制保持未知。

本轮 90 项离线测试及真实缓存复现检查通过。当前交接是第一份真实动作观察，具体见 docs/NEXT_OBSERVATION.md；不要求重开旧回放。结果见 reports/foundation_validation.md。

## 新录像与回放核验（2026-10-13）

已取得真实视频与 HN1-11372643015.rofl。旧解码器原样解析 187 个候选移动包；画面顺序和区域粗略相符，精确时钟校准尚未通过。没有重新拟合替换表或把计划终点当实测到达。详见 reports/movement_video_validation.md。

在项目根目录执行以下命令。需已有地图证据与父目录已审查的 decode_movement_1620.py、probe_packets.py、controlled-byte-synthesis.json，哈希随输出保存。原素材只读、不上传。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-video.txt
.\.venv\Scripts\python.exe scripts\inspect_movement_video.py 'C:/Users/21613/Documents/xwechat_files/WECHAT_USER/msg/video/2026-10/d967aa046c7bca8fd0b4b8645a3e8497.mp4' --output data/private/movement_11372643015/video_detail --times 0.25 0.5 0.75 1 1.25 1.5 1.75 2 9 9.5 10 10.5 11 11.5 12 12.5 19 19.5 20 20.5 21 23.5 24 24.8
.\.venv\Scripts\python.exe scripts\decode_movement_sample.py --replay 'C:/Users/21613/Documents/League of Legends/Replays/HN1-11372643015.rofl' --log 'D:/WeGameApps/英雄联盟/Game/Logs/GameLogs/2026-10-13T19-02-20/2026-10-13T19-02-20_r3dlog.txt' --decoder-dir D:/1/yxlm --output data/private/movement_11372643015/decoded.json
.\.venv\Scripts\python.exe scripts\verify_movement_sample.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-movement-video --junitxml=reports/pytest-movement-video.xml
```

100 项离线测试通过；真实证据哈希复核通过。脚本成功退出代表检查完成，报告仍记录时钟未校准、精确行动模型样本数为 0。合成测试与游戏实测分开，依赖只安装到项目环境。

## 时间核验更正（当前结论）

上节“时钟未校准”的旧结果已被本轮进一步检查更新。背景对齐证明此前把待机动画误标为出发，并把末段停稳标晚；旧报告在 reports/movement_video_validation_before_timing.md/json 保留。修订标注与像素诊断均可追溯，未改变解码器或字节表。

```powershell
.\.venv\Scripts\python.exe scripts\audit_packet_timing.py
.\.venv\Scripts\python.exe scripts\audit_video_timing.py
.\.venv\Scripts\python.exe scripts\verify_movement_sample.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-timing --junitxml=reports/pytest-timing.xml
```

748 帧顺序读取、24 帧逐像素抽帧比较和 6412 个包时间重算完成。四项修订事件有共同偏移区间；最后一段视频实测 **2.3–2.6 秒**，对应包间隔 **2.406 秒**，二者相容。规范化样本在 data/normalized/movement_samples/HN1-11372643015-base-movement-3.json，保留未知坐标、距离、完整速度/装备和结束血蓝数值，不能直接用于路线预测。

本轮 **107 项离线测试通过**。当前片段的时间对应不代表其他回放通用偏移，也不等于完整物理/碰撞验证。下一步需要明确的途中停步或转向对照及完整画面，见 docs/NEXT_OBSERVATION.md。新的入口会读取 v2 标注，重跑不会重新使用已撤销的出发时刻。
