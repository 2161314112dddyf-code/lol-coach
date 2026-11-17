# 地图信号怎样进入个人复盘

## 11 月 16 日 · 用地图地标找回潘森的两次请求协助

同一份红方打野回放 HN1-11468661236 里，你一共发过两次「请求协助」。两次均可在原版小地图上找到信号扩散环。把环中心投到英雄移动使用的 Map11 世界坐标，可在个人时间线上补出地点。

| 游戏时间 | 画面上标在哪里 | 估计 (X, Z)，取整到百 |
| --- | --- | --- |
| 07:25.905 | 下路两座外塔之间，偏红方一侧，距红方下路外塔约 2,000 单位 | (12,900, 2,700) |
| 22:12.697 | 小龙坑附近，在小龙出生点东北约 310 单位 | (10,100, 4,600) |

复核时更正了地标。地图配置中的 `Dragon` 是小龙出生点 (9,866, 4,414)，`DragonEelCamp` 是下半河蟹参照点 (10,500, 5,170)。此前的西南约 700 单位是相对河蟹量的。信号光圈的坐标没有变化。[本构建的原始地标提取](../data/private/minimap-20261113/assets.json)

第二条能证明你在小龙坑附近请求协助。你希望队友来打龙、接团还是掩护撤离，仍要结合同一时刻你能看到的局势判断。[两次标点的原版画面，左早右晚，白十字为环中心](../data/private/ping-landmark-20261116/personal/personal-preview.jpg) · [本人整局发信时间线](../data/private/ping-new-20261115/红方潘森信号时间线.md)

**怎样定位。** 对齐同一 HUD 的地标后，原生小地图向右一像素约为世界 X 增加 88，向下一像素约为世界 Z 减少 88。用 6 座内塔求变换，另外 12 座外塔和高地塔全部留作核对，留出塔误差中位数 35、最大 71 个世界单位。第二局相同布局可重复定位这 12 座塔。测信号时，在整张小地图上找连续五帧扩散环的共同中心。两条新信号把五帧分成奇偶两组，各自测出的中心分别相差 1 和 1.4 像素。塔中心的误差和光圈读数的重复性分别记录，两者均不足以给所有标点定误差上限。[逐塔位置与留出误差](../data/private/ping-landmark-20261116/towers/tower-registration.json) · [信号逐帧测量](../data/private/ping-landmark-20261116/personal/centres.json)

**只用英雄也能定位。** 拿阿木木、杰斯、诺提勒斯、卡牌在小地图上的头像，与同一时刻最近一次移动包的路径起点配对，共 13 个观测。把潘森、阿狸、伊泽瑞尔全部留出检验，9 个观测的误差中位数 53、最大 130 个世界单位。直接跳转后立刻取帧，初测中位数 262、最大 1,109；提前十秒开始播放，在原定时刻取帧后才得到上面的结果。在潘森两次协助标点上，分别用英雄和塔换算，两套方法的结果相差 37、14 个单位。两者共用同一个光圈中心，差值反映坐标换算的一致程度。[英雄头像与移动包对照](../data/private/ping-landmark-20261116/heroes/hero-warm-fit.json) · [跳转后直接取帧的初测](../data/private/ping-landmark-20261116/heroes/hero-fit.json)

**与二进制对照。** 本局共有 140 次发信。上述两条加此前四条孤立发信，共有六条能逐一配对时间、原包偏移和画面中心。沿用上一局提出的字节前缀范围，六条的 X、Z 共 12 个分量全落入对应的粗区间。此次新增的两条具有相同的一对前缀，实际位置却相距约 3,300 单位。当前可以用 HUD 还原具体区域；单凭这组前缀仍无法给全场补出精确 (X, Z)。[六条换算结果与原包](../data/private/ping-landmark-20261116/personal/mapped-markers.json)

还有一个能在游戏中叫出名字的参照物。17:52.040 卡牌的原版提示点名了蜜糖果实。独立匹配同局物体创建包与 Map11 的模型名，再看同址物体反复出现的路径采样，得到植物位置 (9,476, 5,304)。防御塔换算的信号中心约 (9,420, 5,457)，离植物约 163 单位。复盘可以说「卡牌标了这里的蜜糖果实」。植物模型中心和玩家点击点各自保留。[创建包、模型名和空间采样](../data/private/ping-landmark-20261116/objects/honeyfruit.json)

本机在项目目录运行下列脚本可复核已采集帧。第一条在完整小地图上重新测量光圈，第二条读取原始 ROFL 校验逐包映射，并比对同版本塔位与营地参照点。

```powershell
.venv/Scripts/python.exe data/private/ping-landmark-20261116/personal/find_rings.py
.venv/Scripts/python.exe data/private/ping-landmark-20261116/personal/map_markers.py
```

## 新录像盲测 · 红方打野潘森

国服 HN1-11468661236，构建 16.22.836.1077，局长 23:09.794。11 月 14 日开局日志确认本人是红方打野潘森，11 月 15 日的客户端下载记录绑定到这份 ROFL。十名玩家的开局名单、泉水侧、每人插眼数及真眼数均经独立核对。上一局潘森走蓝方辅助，本局重新绑定了发信人。[开局身份与原包](../data/private/ping-new-20261115/identity-research/roster-independent.json)

**原解析器首次盲测失败。** 212 个同指令候选中，旧规则能识别 138 条发信，另外两条 15 字节的目标指令触发了拒绝。把结算中的常规指令整列隐藏，用其余 13 类先匹配十名玩家，两条分别归属 13:27.684 的烬和 17:52.040 的卡牌，再与保留的常规指令计数对账。原版 HUD 另确认卡牌点的是蜜糖果实；烬发信后 0.101 秒又有另一条信号，烬的具体目标仍未知。修复限于这次有证据的包形状。[隐藏类别对照](../data/private/ping-new-20261115/held-out-commands.json) · [原版目标提示](../data/private/ping-new-20261115/hud/clip-1070.4/text-private-safe.png)

**修复后通过。** 得到 140 条发信、10 种类型，72 个候选被排除。十人各 14 类，逐格与结算相符。先保存不带已有名单的盲配结果，再用独立的开局身份映射重算，140 条的发送者逐条一致。本局请求协助 4 次、敌人消失 57 次、正在路上 42 次。其中本人潘森分别为 2、10、25 次，连同其他类型共发 50 条。此前十人局仍为 341 条、训练局仍为零。工程全量 **1,553 项通过**。[盲配输出](../data/private/ping-new-20261115/before-roster/HN1-11468661236.json) · [独立名单重算](../data/private/ping-new-20261115/verified/HN1-11468661236.json) · [测试结果](../data/private/ping-new-20261115/full-suite.xml)

| 游戏时间 | 谁发了什么 | 在原版小地图核对到的位置 |
| --- | --- | --- |
| 02:54.982 | 红方潘森 · 正在路上 | 上半区，靠上路 |
| 03:18.328 | 红方阿狸 · 敌人不见踪影 | 中路附近 |
| 04:57.130 | 蓝方卡牌 · 请求协助 | 下半河道一带 |

这三条来自二进制，表中的地点来自同局原版 HUD。02:55 左右 HUD 还出现了蓝方诺手提示杰斯使用闪现，属于另一类界面沟通，未计入上述 140 条。提示本身不足以证明杰斯确实交了闪现。[三种标记的小地图前后对照](../data/private/ping-new-20261115/hud/new-match-three-pings.png) · [原包和原画面对应关系](../data/private/ping-new-20261115/hud/hud-check.json)

**同秒双视角。** 12:17 暂停，回看 30 秒，潘森本人在 12:11.513、12:16.590 两次发「正在路上」，还可查到阿狸 12:09.442 的敌失提醒。对手卡牌只能查到自己在 12:10.945 发出的「正在路上」。两个真实 MCP 分别对照同侧原包，并各自拒绝跨队查询。红方整场时间线含本人 50 条与队友的 22 条轮盘信号，队友是否收到、本人是否注意仍未知。[双视角 MCP](../data/private/ping-new-20261115/mcp-1217.json) · [本人时间线](../data/private/ping-new-20261115/红方潘森信号时间线.md)

**跨局试算落点。** 固定上一局得到的两个字节前缀假设，再从本局原生小地图拟合四个孤立信号的扩散环。四个点的 X、Z 共八个分量均落在预测的粗略区间。以 02:54.982 为例，小地图估计约为 (5,140, 12,400)，是信号标点；发送前 0.368 秒潘森自身路径起点为 (5,674, 12,504)。两局还出现了相同的八字节串关联不同的静止守卫位置，X、Z 分别相差 4、44 个单位。用英雄或眼的位置替代标点会引入误差。目前 140 条二进制事件的精确坐标均保留为空。[跨局留出和反例](../data/private/ping-new-20261115/marker-geometry-holdout.json) · [潘森自身的位置样本](../data/private/ping-new-20261115/identity-research/pantheon-at-send.json)

额外核查了开局的两个相邻原包。00:12.079 阿木木与 00:12.112 烬先后报敌失。5 fps 时两个标记重叠；60 fps 复播的第 29、30 帧只出现阿木木提示，第 31 帧才出现烬的提示。两处都在蓝方泉水附近，此窗口单独验发信顺序，不计入上面的八个坐标分量。[原生高帧率记录](../data/private/ping-new-20261115/hud/clip-11.6/receipt.json)

复跑这份新录像，在 `lol-coach` 目录执行下列 PowerShell 命令。复盘帧的输出目录须为新目录。

```powershell
$replays = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'League of Legends/Replays'
$match = Join-Path $replays 'HN1-11468661236.rofl'
$log = 'D:/WeGameApps/英雄联盟/Game/Logs/GameLogs/2026-11-14T20-24-44/2026-11-14T20-24-44_r3dlog.txt'
.venv/Scripts/python.exe -m scripts.audit_replay_pings $match --output data/private/ping-new-20261115/verified
.venv/Scripts/python.exe -m scripts.reasoning prepare --vision-replay $match --game-log $log --at 737 --output data/private/reasoning/red-jungle-1217
```

## 首局验收 · 蓝方辅助潘森

适用样本为国服 16.22.836.1077 的十人实战 HN1-11461276459 和同构建的潘森单人训练局 HN1-11461236084。信号的发送时刻、发送者、阵营和类型已接入个人复盘。个人视角入口要求独立核对过的名单，未绑定的对局返回 `unsupported_replay`。同构建的新回放也可以单独做赛后发信审计，条件见 PING-06。

## 12:30 暂停，看谁当时表达了什么

| 游戏时间 | 蓝方发信 | 红方发信 |
| --- | --- | --- |
| 12:13.985 | 潘森 · 敌人不见踪影 | |
| 12:16.690 | 潘森 · 正在路上 | |
| 12:23.603 | | 剑圣 · 正在路上 |
| 12:27.544 | 潘森 · 敌人不见踪影 | |
| 12:28.146 | 潘森 · 正在路上 | |
| 12:28.880 | 杰斯 · 正在路上 | |
| 12:29.749 | | 剑圣 · 敌方视野 |

这张双边表用于开发核对。实际给潘森复盘时，最近 30 秒里他本人已报两次敌失、两次在路上，另可查到杰斯发出的在路上。给队友女警复盘时，五条均来自队伍频道，她本人发出零条。给对面塔姆复盘时，能查到的是剑圣的两条。当时队友是否收到或留意、标出的敌人是否真的离线、支援是否到达，分别要用其他证据判断。[四个真实 MCP 会话的对照](../data/private/ping-pov-roster-750-eight-v2/real-mcp-ping-proof.json)

把潘森的暂停点提前到 **12:20**，这一段只有前两条蓝方信号；再提前到 **12:10**，回看 30 秒两队均无发信。在 12:20 的复盘里可以追问「你已经给过提醒，按当时所见，下一步该留还是走？」把它写成「你已经答应去中路」会越过现有证据。[逐包时间截断对照](../data/private/rofl-pings-20261113/research/event_order.json)

## 验收

- **PING-01 · PASS**　原始实时流里的 473 个同指令包中，341 个满足玩家发信格式，132 个排除。十名玩家各按十四种结算类别独立比对，140 项完全一致。请求协助 20 条、敌人不见踪影 52 条、正在路上 130 条，潘森本人分别是 3、24、19 条。其余有实样的类别为全力进攻、常规指令标记、敌方视野、后撤提醒、需要视野、推进、撤退。保留每条的原始时刻、数据块和偏移，同一时刻的不同信号各算一次。[十人局逐条记录与计数](../data/private/rofl-pings-20261113/decoded/HN1-11461276459.json)
- **PING-02 · PASS**　同版本单人训练局解出零条，十四个结算计数也都是零。结算里的延迟字段 `PING` 不参与发信计数。另一份缺少结算名单的回放只作缺数据处理。[单人对照](../data/private/rofl-pings-20261113/decoded/HN1-11461236084.json)
- **PING-03 · PASS**　本人入口和十人入口重建 12:30 帧；潘森、女警、剑圣、塔姆四个真实 MCP 会话与直接计算相同，四次改阵营查询均被拒绝。按 Riot 所列的八类轮盘信号，本局共有 278 条可进本队频道查询。其余 63 条 `command` 或 `get_back` 当前只供发送者本人回顾。每条频道记录保留个人收悉未知。[本人正式入口](../data/private/reasoning_sessions/ping-probe-pantheon-750-eight-v2/01/evidence.json) · [Riot 轮盘信号说明](https://support.riotgames.com/en-us/league-of-legends/gameplay/smart-ping)
- **PING-04 · PASS**　用同构建客户端重新播放同一份 ROFL，按三个窗口导出原生 HUD。03:57.051 与 03:57.786 潘森连续两次报敌失，05:11.284 塔姆请求协助，12:16.690 潘森发出正在路上。前两个窗口分别出现两条敌失提示和一条协助提示；第三个窗口只有一条玩家发信，12:17 画面出现对应的英雄名及信号文字。[敌失窗口](../data/private/rofl-pings-20261113/research/native-ping-235/) · [协助窗口](../data/private/rofl-pings-20261113/research/native-ping-309.5/) · [正在路上原生帧](../data/private/rofl-pings-20261113/research/native-ping-735/000013.png)
- **PING-06 · PASS（离线身份核对）**　先隐去已核实的名单映射，按每个发信槽位的十四类全局计数，与结算中的每名选手做唯一匹配。十人局得到的身份与既有独立证据逐条一致，调乱名单顺序后 341 条仍全部一致。同构建缺名单和不同构建的真实文件均被拒绝。身份有歧义时同样拒绝。此入口供赛后审计，结果不能载入个人决策帧。上方新增的红方打野实战提供了第二个同构建非零样本。[逐槽核对](../data/private/rofl-pings-20261113/blind-20261115/HN1-11461276459.json) · [乱序对照](../data/private/rofl-pings-20261113/blind-20261115/real-roster-permutation-control.json)

工程全量回归共 **1,548 项通过**。上述原包、同构建客户端画面和真实 MCP 对照另列证据。验收为开发侧实跑。[pytest 结果](../data/private/rofl-pings-20261113/regression-final-blind-20261115.xml)

## 标在哪里

从同局原版小地图的扩散环可以核对四个标点。潘森 03:57.051 第一次报敌失标在地图中央偏上，0.735 秒后的第二次标得更靠上。塔姆 05:11.284 请求协助标在下路靠红方一侧。潘森 12:16.690「正在路上」标在**地图下半区、靠近下路**。当时观战镜头正在中路看卡牌和卡特交手。单看导播画面会把这条信号解读到错误的地方。这四个区域来自观战 HUD，仅作本次实战的画面对照；一枚原生小地图像素约合 88 个世界单位，尚无全图统一误差界。[四个标点前后对照](../data/private/rofl-pings-20261113/research/three-ping-hud-map.png) · [原版提示](../data/private/rofl-pings-20261113/research/three-ping-native-text.png) · [帧号、原包、地图配准和估计误差](../data/private/rofl-pings-20261113/research/hud-marker-evidence.json)

**PING-05 · INSUFFICIENT_EVIDENCE**　十人局的二进制事件目前把 `marker_xz` 留空。两个固定守卫可以提供候选坐标锚，但同一串疑似坐标字节也曾与不同英雄的不同位置同时出现。直接取发送者的站位、移动终点或关联对象的坐标都会引入错标。需在独立落点上核对同一套变换，才可把它用于全场 341 条信号。[关联对象、静止守卫及反例](../data/private/rofl-pings-20261113/research/object_anchors.json)

另外保留了两个单次「正在路上」的独立窗口。03:04.912 剑圣的标点出现在小地图左上，09:44.759 潘森的标点出现在右下，两处均有连续五帧扩散环。总计六处 HUD 落点可用来检验后续二进制变换。[两个留出窗口及原包](../data/private/rofl-pings-20261113/research/hud-marker-holdouts.json)

另查了国际服邻近构建 16.22.8348910 的离线客户端。同一指令号 `0x3F` 在该参考文件里的反序列化函数只写两个字段，无法直接移用到本局信号。这也是上述范围限定到具体构建的依据。[跨构建反例及复查命令](../data/private/rofl-pings-20261113/research-root/reference-mac-packet.json)

## 复跑

在 `lol-coach` 目录用 PowerShell 执行。下面三步依次核对两场的计数、准备本人 12:30 的决策输入、通过本地 MCP 读取这一帧。冻结帧和会话各用一个新输出目录。

```powershell
$replays = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'League of Legends/Replays'
$game = 'D:/WeGameApps/英雄联盟/Game'
$match = Join-Path $replays 'HN1-11461276459.rofl'
$practice = Join-Path $replays 'HN1-11461236084.rofl'
$log = Join-Path $game 'Logs/GameLogs/2026-11-12T13-36-20/2026-11-12T13-36-20_r3dlog.txt'
.venv/Scripts/python.exe -m scripts.audit_replay_pings $match $practice --output data/private/ping-audit
.venv/Scripts/python.exe -m scripts.reasoning prepare --vision-replay $match --game-dir $game --game-log $log --at 750 --window 30 --output data/private/reasoning/ping-personal-1230
data/private/agent_study_current/mcp-env/Scripts/python.exe -m scripts.run_review_agent --bundle data/private/reasoning/ping-personal-1230/bundle.json --game-log $log --lane-replay $match --lane bot --target dragon --help-seconds 5 --backend probe --output data/private/reasoning_sessions/ping-personal-1230
```

上述命令已在新目录实际复跑，潘森 750 秒的 MCP 输出含四条本人信号和一份队友频道引用。Agent 沿用 `review_round_plan` 的 `team_pings.events` 读本人的近期信号。需要查队友发过什么时，把 `team_pings.team_channel_lookup.reference_id` 交给 `get_reference`。旧冻结帧需从 ROFL 重新准备，才能获得这次接入的字段。[按文档复跑的会话](../data/private/reasoning_sessions/ping-personal-1230-doc-check/manifest.json)
