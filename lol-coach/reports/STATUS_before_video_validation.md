# 当前状态

更新时间：2026-10-13。本轮完成候选路径静态相容性、艾翁机制卡和真人刷野来源索引；当前需要第一份可读取的动作起止及结束状态画面。无需重开旧回放。

## 实际完成

- 将两份受控回放中实体候选 0x400000ae 的 51 条记录（26 条多点计划路径）与 SRX_3 逐格比较。51 条均无基础阻挡标记接触；14 条含不确定标记；0 条触及已提取 overlay 区域。
- 不连接不同包的点，不把瞬移画成步行，不把计划终点当实际到达。只检查零半径折线及边角接触，实际距离、耗时、可通行性保持 null。
- 艾翁 P/Q/W/E/R 五条机制卡有官方版本化来源，每条包括队友与对手条件；项目分析单独标记。未生成阵容推荐或当前局技能状态。
- 发现 E 刷新条件的官方简述与版本未明的 Meraki 资料存在描述范围差异，单独保留争议，不合成确定规则。
- 从实际缓存的作者表格提取 4 条 Ivern 真人来源记录，保留补丁原文、作者、路线、惩戒次数、备注和 URL。表格时间未转换成实测耗时，所有结束状态保持未知。
- 较新两个视频入口的网页工具访问失败（Cache miss，无 HTTP 状态），没有观看、下载或伪造视频观察。当前可用实测行动样本为 0。

## 文件变更

新增 lol_coach/path_audit.py、clear_sources.py；scripts/audit_replay_paths.py、build_ivern_foundation.py、verify_foundation.py；tests/test_path_audit.py、test_clear_sources.py；docs/NEXT_OBSERVATION.md；reports/replay_path_audit.json、foundation_validation.md、foundation_smoke.json、media_access_notes.json、pytest-paths.log/xml、pytest-foundation.log/xml、STATUS_before_path_foundation.md。

新增规范化文件 data/normalized/16.20.1/en_US/Ivern.mechanics.json、data/normalized/clear_candidates/Ivern.json。更新 README.md、reports/STATUS.md。原始回放、旧解析和本地游戏安装未修改。

## 运行与真实测试结果

在 D:/1/yxlm/lol-coach：

```powershell
.\.venv\Scripts\python.exe scripts\audit_replay_paths.py
.\.venv\Scripts\python.exe scripts\build_ivern_foundation.py
.\.venv\Scripts\python.exe scripts\verify_foundation.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-foundation --junitxml=reports/pytest-foundation.xml
```

90 项离线测试通过（0.90s，无失败/跳过；70 项既有 + 14 项路径 + 6 项表格解析）。此前仅加入路径模块时 84 项通过，最终 90 项结果为准。

真实离线 smoke 通过：原始回放/旧报告/网格/overlay/机制来源哈希核对，重算 51 条路径，重现 4 条来源表格行，确认未知耗时和机制争议仍保持未知。这是保存证据的可复现性测试，不是游戏实测。项目写入经环境审批，无审批拒绝。

## 需要用户接手的最小事项

提供一段当前版本的艾翁单营地操作录屏本地路径，已有录屏也可以。若需新录：训练模式记录版本/等级/装备/符文/加点，从种植前录到成熟、解放并结束后约 5 秒；不用惩戒，不开自动回复/刷新等训练开关；保留游戏时间、血蓝数字、等级、装备、技能栏和小地图。具体说明见 docs/NEXT_OBSERVATION.md。

这份证据用于核验真实动作耗时和结束状态，不是再要求验证泉水大致位置。不知道的条件保留未知；若现在不能操作游戏，此项可以等待，不能用表格时间冒充测量。E 刷新争议不要求本次同时测试。

## 仍有的缺口

实际运行时导航、overlay 合成、未知 flags、单位碰撞半径、精确出生槽位/取整仍未全部验证，但不阻塞已经完成的静态相容性检查。尚无真实行动时长和完成后状态，因此不能给当前局路线到场时间、刷野速度或决策点评。官方静态数据与 Meraki 的复杂交互及目标补丁兼容性分开记录。

没有前端、微调或云端复盘。下一次拿到录屏后，先核对来源/版本与可读性，标记动作起止和结束血蓝等级，再决定哪些记录能进入行动模型。

详细结果见 reports/foundation_validation.md，历史导航选用依据见 STATUS_before_path_foundation.md 及 map_rules_validation.md。
