# 项目运行手册

2026-11-19 起，正式会话自动接入[本地知识手册](docs/knowledge/README.md)。模型按需通过 `get_reference` 读取条件知识卡，并在 `follow_through` 给出首选之后的分支和下一次观察点。推完不等于进塔、预期回推不等于已发生。下一帧继承计划再核对事实；安静个人帧仍不强制展开全队联动。已有运行命令无需新增参数。[本轮检查与边界](reports/知识手册接入_20261119.md)

复盘实验入口更新于 2026-11-18。个人行动模式已接入“近期动作 → 继续或改选 → 证据复核 → 封存 → 实际经过”。[两局实跑与边界](reports/个人行动链路实现_20261118.md) · [07:28 实战答卷](reports/潘森交战判断_20261117.md) · [当前接管点](docs/CURRENT_TASK.md) · [文档索引](docs/INDEX.md)。以下命令在`lol-coach/`执行，输出路径使用尚不存在的新文件/目录。

### 复跑个人行动与赛后执行核对

`--personal-actions` 默认围绕本人的操作。只有当时可证、会影响这一步的事件才会打开联动分析，写给谁、该说什么、等到什么变化就自己改选。普通补刀或清营直接给本人建议。所有卡封存后，执行报告才核对同局实际发出的信号和指定队友的后续位置。[个人复盘中的队友联动](docs/回合复盘方案_v0.1/AGENT_MCP_IMPLEMENTATION.md#个人决策如何考虑队友)

本机已安装 MCP 的解释器如下；其他机器按后文安装项目的 `review-mcp,map` 依赖，再改用自己的解释器。以下命令准备红方打野潘森的四个时刻。小数参数加引号，避免 PowerShell 在传给 Python 前缩短精度。

```powershell
$py = 'data/private/agent_study_current/mcp-env/Scripts/python.exe'
$r = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'League of Legends/Replays/HN1-11468661236.rofl'
$log = 'D:/WeGameApps/英雄联盟/Game/Logs/GameLogs/2026-11-14T20-24-44/2026-11-14T20-24-44_r3dlog.txt'
$frames = 'data/private/reasoning/personal-' + (New-Guid)
$out = 'data/private/reasoning_sessions/personal-' + (New-Guid)
& $py -m scripts.prepare_personal_match --replay $r --game-log $log --at '738.6788940429688' '744.606' '750' '750.4241333007812' --output $frames
& $py -m scripts.run_review_agent --sequence "$frames/sequence.json" --subject-replay $r --game-log $log --lane jungle --target dragon --help-seconds 5 --personal-actions --backend file --timeout 3600 --output $out
```

`file` 后端会等待模型读请求并回填文件，并非运行命令后自动获得云端模型。Codex 是本轮读写者。所有回复沿用 `{"request_id":"原请求ID","response":{"answer":规定对象}}`；查询用 `response.tool_requests`。依次处理各帧 `exchange` 和 `claim_exchange`，全部事前卡封存后才出现 `execution_exchange`。文件应原子写入，不能覆盖已有回执。已配置本机模型时可换成 `--backend ollama --model 模型名称`，其独立战术质量需另验。

正式个人会话封存并回看后，打开输出根目录的 `player-review.md`。重点题会讲两条走法的收益与代价，后面紧跟实际发生的事。`execution-review.md` 保留逐点核对，`review.md` 保存事前计划。若会话已有封存结果，可运行 `python -m lol_coach.player_review 会话目录` 重新组稿。逐帧文件保留答案、证据复核与真实工具回执，方便回查；任一决策复核失败会阻止后续实况进入这次判断。

个人整局使用 `--event-checkpoints` 自动选教学暂停点。加 `--schedule-only` 可先看 `schedule.json` 中的全部候选，以及 `selection.json` 中每一项保留或合并的理由。去掉 `--schedule-only` 即按所选时刻生成冻结帧与 `sequence.json`，后者可直接交给上面的 `--personal-actions` 命令。开发时需要给全部候选制帧可加 `--all-event-candidates`，检查指定时刻仍可用 `--at`。

事件取点会把本人的求援、出发、撤退、推进和进攻信号合并到附近的暂停点，同区域的连续同类信号去重。候选只用于决定何时回看；是否需要展开联动由该时刻本人可知的事件决定。

```powershell
& $py -m scripts.prepare_personal_match --replay $r --game-log $log --event-checkpoints --schedule-only --output ('data/private/reasoning/schedule-' + (New-Guid))
```

本机本轮离线回归命令如下。每次换一个新的临时目录；`REVIEW_MCP_PYTHON` 指向带 MCP 依赖的解释器。

```powershell
$env:REVIEW_MCP_PYTHON = (Resolve-Path $py).Path
.venv/Scripts/python.exe -m pytest -q --basetemp ('data/private/pytest-' + (New-Guid))
```

### 更新复盘使用的公开数据

在 PowerShell 进入 `lol-coach`，把 `$log` 指向该场游戏开局的 `r3dlog.txt`。下面第一条同步命令固定历史版本。刷新器从日志认出英雄及双方分路，向 Riot 和腾讯发送版本、英雄和分路参数，本机玩家身份与回放保存在本地。

```powershell
$log = 'D:/WeGameApps/英雄联盟/Game/Logs/GameLogs/2026-11-12T13-36-20/2026-11-12T13-36-20_r3dlog.txt'
.venv/Scripts/python.exe -m scripts.refresh_review_sources --version 16.22.1 --game-log $log --lane-profiles
```

要跟踪这组英雄在后续补丁的变化，运行以下命令。每六小时按 Riot 官方版本目录取当前补丁，同步本阵容的新版数据。前台运行可按 Ctrl+C 停止。临时需要重取可单次加 `--force`。腾讯统计有自己的数据日，轮询频率不代表统计按小时发布。

```powershell
.venv/Scripts/python.exe -m scripts.refresh_review_sources --version current --game-log $log --lane-profiles --interval-minutes 360
```

本机已在 2026-11-13 启动该阵容的六小时后台轮询，运行记录在 `data/private/review_sources/poller-20261113/stdout.jsonl`，错误单记在 `stderr.jsonl`。从项目目录运行下面一行即可停止这一次后台进程。关机后需重新启动同步命令。

```powershell
New-Item -ItemType File -Force data/private/review_sources/poller-20261113/STOP
```

完整批次保存在 `data/private/review_sources/snapshots/<补丁>/`，原始 HTTP 响应与访问记录在同目录树的 `evidence/`。任一请求失败会报告错误并保留上一份完整快照。默认六小时内同范围复用成功结果。换对局可传新日志，手选范围可用 `--champions` 和可重复的 `--matchup 分路 己方英雄 对手英雄`。

按下节运行个人复盘即可离线读取本地快照。英雄技能按回放补丁和场上阵容选取，群体统计按已核实的分路和开局时间选取，来源没列出的对位保留缺项。双帧或多帧共用同一份引用。已有另一份资料库时向复盘命令传 `--external-data-dir 路径`，做对照时传 `--no-external-data`。查看每帧的 `evidence.json → review_round_plan.external_data` 可见实际采用的资料范围及缺项原因。

### 查一帧的技能射程和伤害

在复盘前运行一次下面的更新命令。程序从 ROFL 取十人阵容和四段客户端构建号，从 Riot 选同补丁的 Data Dragon 发布版，还会按 SHA-256 核对并保存本场已审过的游戏资源。省略 `--game-dir` 可以只更新公开资料与已有规则。新构建尚无已核规则时，复盘工具会标记缺项。相同范围默认六小时复用，可加 `--force` 重新同步。一次更新失败仍可使用历史快照。

```powershell
$r = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'League of Legends/Replays/HN1-11468661236.rofl'
.venv/Scripts/python.exe -m scripts.refresh_review_sources --replay $r --game-dir 'D:/WeGameApps/英雄联盟/Game'
```

按下节运行个人复盘时，会话从本地固定一份版本快照，每帧取本人的六枚符文、三枚碎片和当时装备。下列命令可用现成的 07:28 冻结帧，查询潘森 R 中心命中烬的条件伤害。省略 `--target` 和 `--hit` 可单查技能。传 `--assumptions-file` 可另算假设，例如 `{"effective_magic_resist":40,"target_health_fraction":0.3999}`。血量比例取命中前，0.4 表示恰好 40%。

```powershell
$frame = 'data/private/reasoning_sessions/combat-runes-20261116-release/01/bundle.json'
data/private/agent_study_current/mcp-env/Scripts/python.exe -m scripts.inspect_ability --bundle $frame --slot R --target Jhin --hit R.landing_center
```

输出的 `frame_inputs_only.rune_damage` 是含施法者符文的主结果。查看 `parts`、`blockers` 和 `missing_inputs` 可知哪一击、哪枚符文或哪项抗性影响答案。单一情景的抗性后数值在 `after_resistance_total`，上下界在 `after_resistance_total_interval`。旧字段 `damage` 保留技能本体小计。[本局符文、公式与验收](reports/符文伤害与本地预加载_20261116.md) · [技能数值原件](reports/pantheon_damage_sources_20261116.md)

### 运行 2026-11-12 复盘 Agent 实验

**从开局连续复盘一名玩家。** 以红方打野潘森这场十人局为例，下面的命令先选出会影响本人走法的时刻，再通过正式 Agent 逐帧调用只读 MCP。平静期可抽查。新的暂停点可以续讲同一道题，是否换回合由先前计划和当时的信息判断。

```powershell
$r = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'League of Legends/Replays/HN1-11468661236.rofl'
$game = 'D:/WeGameApps/英雄联盟/Game'
$py = 'data/private/agent_study_current/mcp-env/Scripts/python.exe'
$log = Join-Path $game 'Logs/GameLogs/2026-11-14T20-24-44/2026-11-14T20-24-44_r3dlog.txt'
$frames = 'data/private/reasoning/match-' + (New-Guid)
$out = 'data/private/reasoning_sessions/match-' + (New-Guid)
& $py -m scripts.prepare_personal_match --replay $r --game-dir $game --game-log $log --event-checkpoints --output $frames
& $py -m scripts.run_review_agent --sequence "$frames/sequence.json" --subject-replay $r --game-log $log --lane jungle --target dragon --help-seconds 5 --personal-actions --backend probe --output $out
```

安装依赖使用下节的 `.[review-mcp,map]`。上面第二条命令生成工具证据。要让模型作答，另选新的输出目录，用 `--backend file --catalog-history` 接文件交换读者，或用 `--backend ollama --model 模型名称` 接本机模型。前一帧的建议通过校验后随下一帧提供。具体实战见[红方打野潘森的逐回合复盘](reports/红方打野潘森逐回合复盘_20261116.md)。

本机这局已归档公开击杀和个人状态。在另一台有同构建客户端的机器上，可先按以下命令从同一局重新生成这两种来源，再准备冻结帧。公开播报采集器用隔离的回放进程连续播放，需几分钟。若已有 2999 服务，它会退出。每次审计输出指定新文件名，同一份审计可反复导入；需要比对两次独立播放的观察时间时可用 `--root` 单存核对副本。

```powershell
$eventAudit = 'data/private/native-events-' + (New-Guid) + '.json'
.venv/Scripts/python.exe -m scripts.audit_native_match_events $r --game-dir $game --output $eventAudit
.venv/Scripts/python.exe -m scripts.publish_native_kill_feed $eventAudit
.venv/Scripts/python.exe -m scripts.sample_native_player $r --game-dir $game --team 200 --champion Pantheon --at 300 448 463 750 1335 1350
```

客户端白名单状态和原生 HUD 的血蓝条、R 图标是两种采样，单跑客户端命令不会凭空生成图像读数。原生取样与使用边界见[本人状态报告](reports/player_state_20261116.md)。

正式复盘默认给本机玩家。指定本场原始 ROFL 和开局的 `r3dlog.txt`，程序核对对局、阵营和玩家。准备冻结帧时传 `--game-log` 就能自动选本机英雄和队伍。研究队友时显式用 `--perspective comparison`，复盘自己的一场训练用 `--perspective practice`。游戏终局的小龙数用于赛后核对，随时间给模型的事实保留当时的可见范围。

连续时刻共用一份地图计划。每次暂停，先结合上轮计划和本队可知的变化，判断这名玩家应继续做什么、改哪一步、或为何结束上轮。`--target` 指定用于计算三种走法代价的候选地点，玩家仍可选择守线、换边或回补。会话有通过校验的答卷时，打开输出目录的 `review.md` 看整段；逐帧细节在 `01/answer.md` 等文件中。[卡牌守中与潘森收龙的实跑和复现](reports/macro_round_pipeline_20261112.md)

宿主为每个冻结时刻启动 `lol-round-review` 只读 stdio 服务。工具包括 `enemy_sightings`、`compare_round_options`、`compare_help_duration`、`review_round_plan`、`get_reference` 和 `read_history`。例如在同一帧调用 `compare_help_duration` 并传 `{"help_seconds":9}`，可以检查多等四秒是否错过目标。原题、玩家、时刻和观察队伍保持绑定。己方兵样本另报最近一秒采到位置的数量，敌兵未被来源覆盖时保留未知。

本人是辅助且选择 `--lane bot` 时，宿主按开局日志的下路分工绑定双方四人。`review_round_plan` 会给出对线组合、射手附近本队能看见的敌人、按出生批次拆开的己方兵，以及离线往返的条件。打开玩家卡先看怎么打这一波，再看短走或跨线支援能换什么。本轮有版本化机制的完整对位为 16.22 的潘森、女警对塔姆、大嘴。[对线判断与实战](docs/回合复盘方案_v0.1/阵容和强势期怎样进入判断_20261113.md)

同局开局日志可核实中野分工时，工具还会生成 `support_lane_opportunity.destination_comparison`。比较照应射手、接应打野、帮中单；能核实己方上单时也比较支援上路。每个去处保留各自的参与者、可见采样、额外收益、撤销信号和适用时钟。答卷的 `destination_choice` 给出当前首选及改选另一处的条件。保留 `--target dragon` 也能发现其他去处。[主播实例与判断依据](docs/回合复盘方案_v0.1/辅助游走目的地与收益.md)

公开克隆可先安装 `pytest` 和本页列出的项目依赖，再运行 `.venv/Scripts/python.exe -m pytest -q tests/test_round_agent_integration.py`。该组测试在本地生成合成输入，包括启动真实 MCP 子进程，无需私人回放。

在已核验的 16.22 回放上，`review_round_plan.team_pings.events` 默认给出最近 30 秒内本人发出的信号。要查队友在频道里发了什么，用 `get_reference` 读取 `team_channel_lookup.reference_id`。本队八类轮盘信号包括撤退、推进、正在路上、全力进攻、协助我、需要视野、敌人不见踪影和敌方视野。个人是否收到、注意或作出回应均需另有证据。可用原版 HUD 复核个别落点，通用二进制坐标字段尚待核实。同构建新文件可运行 `scripts.audit_replay_pings` 做离线核对。[国服实战与复跑命令](reports/replay_pings_20261115.md) · [Riot 的 Smart Ping 说明](https://support.riotgames.com/en-us/league-of-legends/gameplay/smart-ping)

**从本机玩家的第一帧复跑。** 以下例子使用十人实战蓝方辅助潘森的 05:00。若需连续复盘，可在新时刻再次准备冻结帧，并把新的 `--bundle` 依时间追加到最后一条命令。

```powershell
.venv/Scripts/python.exe -m pip install ".[review-mcp,map]"
$rofl = "$env:USERPROFILE/Documents/League of Legends/Replays/HN1-11461276459.rofl"
$log = 'D:/WeGameApps/英雄联盟/Game/Logs/GameLogs/2026-11-12T13-36-20/2026-11-12T13-36-20_r3dlog.txt'
$frame = 'data/private/reasoning/personal-' + (New-Guid)
$out = 'data/private/reasoning_sessions/round-' + (New-Guid)
.venv/Scripts/python.exe -m scripts.reasoning prepare --vision-replay $rofl --game-log $log --at 300 --output $frame
.venv/Scripts/python.exe -m scripts.run_review_agent --bundle "$frame/bundle.json" --lane-replay $rofl --game-log $log --lane bot --target dragon --help-seconds 5 --backend probe --output $out
```

复用本机 12:20、12:35 两份已带兵线的输入时，沿用上面的 `$rofl`、`$log`，运行以下命令。每帧的 `evidence.json` 包含按目的地计算的结果。

```powershell
$pair = 'data/private/reasoning_sessions/roam-destinations-1220-1235'
$out = 'data/private/reasoning_sessions/roam-recheck-' + (New-Guid)
data/private/agent_study_current/mcp-env/Scripts/python.exe -m scripts.run_review_agent --bundle "$pair/01/bundle.json" --bundle "$pair/02/bundle.json" --subject-replay $rofl --game-log $log --lane bot --target dragon --help-seconds 5 --backend probe --output $out
```

`--lane-replay` 从同源回放补入己方兵与移动采样。复用已经带兵线的冻结包时，改传 `--subject-replay $rofl`。`probe` 输出每帧的 `evidence.md` 和 `evidence.json`。要让模型给建议，可用已启动的本机 Ollama 配 `--backend ollama --model <本机模型名>`，或用 `--backend file` 接入读取请求并按契约回写的模型宿主。每次选择新输出目录。模型通过校验后才生成 `answer.md` 并向下一帧传递计划，原始调用记录保存在 `result.json`。`--catalog-history` 将上一帧事实正文改为可按 ID 取回的目录。`--previous-bundle` 和 `--previous-answer` 用于从指定前卡继续。[真实输入、对照和验收结果](reports/round_agent_acceptance_20261112.md)

在含原有项目依赖的 Python 环境中，可按需加装本地协议 SDK。以下用仓库已有的私有冻结帧运行。每次探测会启动独立的 stdio 服务，核对业务返回，并验证工具拒绝时间、视角覆盖。方法与读数见[调研结论](docs/回合复盘方案_v0.1/自建复盘Agent_20261112.md)。

```powershell
.venv/Scripts/python.exe -m pip install ".[review-mcp]"
.venv/Scripts/python.exe -m scripts.review_sightings_mcp probe data/private/reasoning/vision-blue-pantheon-5m-1622/frame.json
$old = 'data/private/offline_finish_20261101/answers_final'
.venv/Scripts/python.exe -m scripts.measure_review_history "$old/t300/bundle.json" "$old/t320/bundle.json"
```

同一帧上可用 `check` 核一份模型的结构化显隐答卷。答卷四个字段为 `visible`、`last_xz`、`position_fact_id` 和 `entrance_safety_proven`。退出码 1 表示至少一项不成立。以下是本机留存的真实答卷。

```powershell
$run = 'data/private/agent_study_current/reading-528a3c9908da4492b244b55fafd67efd'
.venv/Scripts/python.exe -m scripts.review_sightings_mcp check data/private/reasoning/vision-blue-pantheon-5m-1622/frame.json --entity 0x400000b4 --answer "$run/300-query.answer.json"
```

需要从同一原始 ROFL 重建第二帧时，指定尚不存在的输出目录。使用公开合成样本则可直接运行下方测试。

```powershell
$replay = "$env:USERPROFILE/Documents/League of Legends/Replays/HN1-11461276459.rofl"
$frame = "data/private/reasoning/agent-study-320-$(New-Guid)"
.venv/Scripts/python.exe -m scripts.reasoning prepare --vision-replay $replay --at 320 --team 100 --player Pantheon --output $frame
.venv/Scripts/python.exe -m scripts.review_sightings_mcp probe "$frame/frame.json"
.venv/Scripts/python.exe -m pytest -q tests/test_review_sightings.py -p no:cacheprovider --basetemp "data/private/review-tests-$(New-Guid)"
```

### 把本人复盘帧画在游戏小地图上

首版做了 16.22 蓝方潘森开局地形的两次暂停，[05:00](data/private/minimap-20261113/05-00/minimap.png) 和 [05:20](data/private/minimap-20261113/05-20/minimap.png)。取本机客户端原版纹理和 16 个营地坐标。兵线用本队真实采样，野怪存活和敌兵数量未接入。以下示例沿用上文的 `$rofl`、`$log`、`$frame`。含兵线的会话需要 `--lane-replay`。绘图时核验会话、开局日志和地图皮肤。

```powershell
.venv/Scripts/python.exe -m pip install ".[minimap,review-mcp]"
$game = 'D:/WeGameApps/英雄联盟/Game'
$assets = 'data/private/minimap-20261113'
.venv/Scripts/python.exe -m lol_coach.minimap_assets --game-dir $game --output $assets
$out = 'data/private/reasoning_sessions/map-' + (New-Guid)
.venv/Scripts/python.exe -m scripts.run_review_agent --bundle "$frame/bundle.json" --lane-replay $rofl --game-log $log --lane bot --target dragon --help-seconds 5 --backend probe --output $out
.venv/Scripts/python.exe -m scripts.render_review_minimap --bundle "$out/01/bundle.json" --assets "$assets/assets.json" --game-log $log --icons "$assets/icons" --output ("$assets/map-" + (New-Guid))
```

产物为一张 PNG 和一份可追溯到当时帧的坐标清单。本机有十人的 16.22.1 官方头像缓存，缺头像时以首字母标出。底图同真实训练 HUD 做了[方向与两处资源坑的对齐检查](data/private/minimap-20261113/texture-hud-alignment.json)。实现时参考了 [LeagueToolkit 的地图资产与坐标映射调查](https://github.com/LeagueToolkit/ltk-manager/issues/638)和[开源回放查看器的底图、时间线分层方式](https://github.com/chdoyle1/lol-replay-viewer)。

## 1. 安装和公开离线检查

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt -r requirements-video.txt ".[minimap,review-mcp]"
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp-public-new
.venv/Scripts/python.exe -m lol_coach --help
.venv/Scripts/python.exe scripts/reasoning.py --help
.venv/Scripts/python.exe scripts/run_reasoning_session.py --help
```

Python 3.11+为声明范围，3.13.7为实际验证环境；Linux/macOS替换为`.venv/bin/python`。公开副本不含私人素材，离线测试和CLI帮助可运行，不代表每个研究导出命令都能运行。

## 2. 获取官方静态样本（需要网络）

```powershell
.venv/Scripts/python.exe -m lol_coach fetch-champion --patch 16.20.1 --champion Ivern
```

英雄只作样例，不限定产品范围。固定资料补丁不等于本局技能可用，也不自动证明精确客户端兼容。来源缓存和规范化结果由工具记录。

## 3. 真实时刻输入（需要本地配套数据）

必须保留仓库父目录冻结分包器、16.20兼容ROFL，以及对应身份/状态/视野/兵线导出和资料缓存。无需启动游戏。

```powershell
.venv/Scripts/python.exe scripts/analysis.py context --replay-id HN1-11360086609 --at 300 --team 100 --player 0x40000034 --output data/private/analysis/current-300-new.json
.venv/Scripts/python.exe scripts/reasoning.py prepare --replay-id HN1-11360086609 --at 300 --team 100 --player 0x40000034 --max-chars 250000 --output data/private/reasoning/current-300-new
```

`bundle.json`保留资料库与本地审计；`messages.json`只提供模型应看到的内容。不能把完整回放或审计数据一并放进模型提示。敌方隐藏期间的旧位置不能当当前坐标。

## 4. 前后计划与模型

```powershell
.venv/Scripts/python.exe scripts/reasoning.py chain --bundle data/private/reasoning/current-300-new/bundle.json --previous-bundle data/private/reasoning/previous/bundle.json --previous-answer data/private/reasoning/previous/answer.json --max-chars 250000 --output data/private/reasoning/linked-300-new
.venv/Scripts/python.exe scripts/run_reasoning_session.py --bundle data/private/reasoning/linked-300-new/bundle.json --output data/private/reasoning_sessions/linked-300-new
```

`previous`是要替换成实际存在文件的示例路径；上一答案须与上一帧匹配并通过契约，否则链路按规则降级。会话CLI等待宿主写入响应，不自行调用模型API；无人提供响应会超时，不应当作模型已运行。协议见[模型框架](docs/回合复盘方案_v0.1/REASONING_FRAMEWORK.md)和[会话报告](reports/real_reasoning_validation.md)。

## 5. 整段检查点与评测输入

以下需要现有主回放及配套导出，默认观察队100、玩家`0x40000034`。调度是复盘检查点提议，不是固定时长的游戏回合。

```powershell
.venv/Scripts/python.exe scripts/scan_round_boundaries.py --output data/private/scan-new
.venv/Scripts/python.exe scripts/build_review_sequence.py --scan data/private/scan-new --output data/private/sequence-new
.venv/Scripts/python.exe scripts/finalize_review_sequence.py --sequence data/private/sequence-new --output data/private/ready-new
.venv/Scripts/python.exe scripts/evaluate_review_sequence.py --sequence data/private/sequence-new/sequence.json --output data/private/evaluation-new
```

最后一步输出空白标签模板；有真实外部标签时可增加`--labels <标签JSON>`。没有标签就不计算准确率；未选时刻也保留，不自动标成负例。整局分组，不能将同局切片拆到训练和测试两边。

## 6. 限定研究与实验

视野查询可直接读取已验证构建的 ROFL。用 `scripts/query_vision.py --replay <ROFL> --team 200 --subject entity:0x400000ae --interval 157 167` 可复现潘森中线暴露时长。逐点地面观测、地图坐标查询及决策帧接入方式见[视野实测](reports/vision_20261112.md)。

- 新版容器/旧规则探测：`scripts/probe_new_replay_compatibility.py`、`scripts/research_new_build_families.py`，需要脚本指定的本地样本。
- 时间冻结/失效：[时间结果](docs/ACTION_TIME_TEST_RESULTS.md)、[失效结果](docs/TRAVEL_VALIDITY_RESULTS.md)。当前模型`calculations`仍不填未验证ETA。
- 16.22 潘森训练局的实际复盘、复跑命令及二进制阶段收尾见[结项报告](reports/replay_closeout_20261112.md)。先前的[四项操作单](docs/CURRENT_STAGE_EXPERIMENTS_20261101.txt)已归档。
- 更早命令及阶段细节保留在[整理前运行手册](docs/history/PROJECT_README_before_20261101.md)和各报告；历史命令可能依赖原机器素材，不作为公开启动流程。

## 7. 数据与验证边界

16.20.824.8524是主要游戏字段研究构建；16.21.829.9102仅容器恢复，游戏语义未适配。实际施法/冷却、完整连续背包、区域视野和可靠实局到达时间仍有缺口。身份已解、当时可知、进入模型、战术正确是不同验收层。

原始ROFL/视频/客户端、缓存、`data/private`及完整机器报告不公开。文档的私有路径仅供本机追溯。所有历史失败和未验收项保留在[STATUS](reports/STATUS.md)，不由测试数量或发布状态替代。
