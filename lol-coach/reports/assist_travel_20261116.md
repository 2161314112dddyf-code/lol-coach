# 潘森两次请求协助，能否及时到场

HN1-11468661236，红方打野，客户端 16.22.836.1077。相同玩家先后两次发「协助我」，两帧原版 HUD 的 R 图标均亮。两次正式 stdio MCP 都能分别读出本人最近的移动包、标点估计中心、同补丁射程和当前应复查的条件。

| 决策 | 普通步行与本人已下发的路径 | R 的射程与改选条件 |
| --- | --- | --- |
| 07:28，下路 | 07:27.241 本人在 [9370, 5430]，距标记约 4,500 单位。若从该点直接走向圈心，全程无阻且保持包速 345，算得 **12.9 秒**。实际命令只走向 [10108, 6280]，按该速需 3.26 秒；这个终点距圈心仍约 4,500。 | 从样点到估计圈心在 R 的 5,500 射程内。看烬的退路、泰坦能否先接、伊泽是否能输出，再选落点。若对方已退开、必须独自越塔或引导会被打断，就留大。 |
| 22:15，小龙坑 | 最近样点在 22:10.326，已旧 **4.67 秒**。[6806, 12528] 至圈心约 8,600 单位。从旧点以包速 432.44 无阻直走的算例为 **19.9 秒**。包里只有一个点，没有去龙坑的后续路线。 | 从旧点到圈心还比 R 射程远约 3,100；按相同理想条件，向圈心走 **7.1 秒**才能刚进射程。两项时间都从旧样点起算。先刷新本人位置与 R 落区，再看龙是否在场、己方谁能先照入口。 |

步行算例可复算为两点欧氏距离除以该条移动包的速度。标点来自游戏画面估读并取整到 100。数值没有计入地形、绕行、变速、改令、施法或其他位移。R 的 5,500 来自该帧封存的 16.22.1 官方资料，各等级相同；另核对了同构建客户端 `data/characters/pantheon/pantheon.bin` 的 `PantheonR.mSpell.castRange`。引导、升空和落地需要时间。技能字段 `mCastTime` 为 0.1 秒，完整引导至落地时长仍未知，两个工具结果均保留实际到场与落地时间为空。[官方补丁资料](https://ddragon.leagueoflegends.com/cdn/16.22.1/data/zh_CN/champion/Pantheon.json)

**封存后才读的反例。** 07:38.397 的本人样点为 [10336, 5618]，07:38.430 为 [11966, 2436]，两点相隔约 3,575 单位，后一点距原标点约 970。两份报告之间的 0.033 秒不能用作 R 的飞行时间，也不能得出命中了谁。22:18.312 的下一条本人样点已在基地侧 [14340, 14390]，离标记约 10,700；此后包速也变了。单点与包速没有证明玩家已向目标持续前进。[后续位置与原包指针](../data/private/assist-travel-20261116/v1/later-samples.json)

**执行范围。** 从此前 v2 的第 4、11 帧派生新文件，断言五人的既有位置事实 ID 不变，加入最近一次本人命令，再从两个独立 stdio 会话调用 `review_round_plan.team_pings.assist_distances.personal_travel`。返回值逐字段等于直接调用。旧模型两份答卷未重跑；本轮验证的是后验工具可提供的材料。此前四局、24,501 条冻结路径的独立评价对通用英雄到场时间仍判证据不足，本轮两个算例没有提高其精度评级。[07:28 正式 MCP](../data/private/assist-travel-20261116/v1/mcp-448.json) · [22:15 正式 MCP](../data/private/assist-travel-20261116/v1/mcp-1335.json) · [原有行动时间验证](action_time_validation_20261101.md)

运行时须选新输出目录。两帧只读本地回放与已有 v2 资料，未占用 2999。

针对性回归 15 项通过，包含旧位置、单点、零速、他人信号、冷却遮罩、死亡、构建不符及敌方位置早于公开死亡。全项目 **1,590 项通过**。首次混用两个 Python 环境时，三个 MCP 测试子进程缺少 `pywintypes`；改用项目约定的 `REVIEW_MCP_PYTHON` 指定完整 MCP 环境后全部通过。[全量测试回执](../data/private/assist-travel-20261116/full-03.xml)

```powershell
$r = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'League of Legends/Replays/HN1-11468661236.rofl'
data/private/agent_study_current/mcp-env/Scripts/python.exe -m scripts.audit_assist_travel --replay $r --output "data/private/assist-travel-20261116/run-$(New-Guid)"
.venv/Scripts/python.exe -m pytest -q tests/test_assist_travel.py tests/test_review_pings.py tests/test_player_action.py
```
