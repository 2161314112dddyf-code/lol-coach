# 项目运行手册

复盘实验入口更新于 2026-11-12。能力边界见[项目现状](docs/PROJECT_SUMMARY.md)，执行顺序见[当前接管点](docs/CURRENT_TASK.md)，全部资料见[文档索引](docs/INDEX.md)。以下命令在`lol-coach/`执行，输出路径使用尚不存在的新文件/目录。

### 运行 2026-11-12 复盘 Agent 实验

宿主为每个冻结时刻启动 `lol-round-review` 只读 stdio 服务。工具包括 `enemy_sightings`、`compare_round_options`、`compare_help_duration`、`review_round_plan`、`get_reference` 和 `read_history`。例如在同一帧调用 `compare_help_duration` 并传 `{"help_seconds":9}`，可以检查多等四秒是否错过目标。原题、玩家、时刻和观察队伍保持绑定。己方兵样本另报最近一秒采到位置的数量，敌兵未被来源覆盖时保留未知。

公开克隆可先安装 `pytest` 和本页列出的项目依赖，再运行 `.venv/Scripts/python.exe -m pytest -q tests/test_round_agent_integration.py`。该组测试在本地生成合成输入，包括启动真实 MCP 子进程，无需私人回放。

**逐回合比较**已接入本地 MCP。以下示例使用同局蓝方 05:00、05:20 及原始 ROFL。若本机还没有这两份冻结输入，可用后文的 `scripts.reasoning prepare --vision-replay` 指定 `--player TwistedFate` 和时刻生成，并把命令中的 bundle 路径换成生成目录。

```powershell
.venv/Scripts/python.exe -m pip install ".[review-mcp,map]"
$rofl = "$env:USERPROFILE/Documents/League of Legends/Replays/HN1-11461276459.rofl"
$b = 'data/private/reasoning'
$out = 'data/private/reasoning_sessions/round-' + (New-Guid)
.venv/Scripts/python.exe -m scripts.run_review_agent --bundle "$b/round-framework-tf-300-v1/bundle.json" --bundle "$b/round-framework-tf-320-v1/bundle.json" --lane-replay $rofl --lane mid --target dragon --help-seconds 5 --backend probe --output $out
```

`probe` 输出每帧的 `evidence.md` 和 `evidence.json`。要让模型给建议，可用已启动的本机 Ollama 配 `--backend ollama --model <本机模型名>`，或用 `--backend file` 接入读取请求并按契约回写的模型宿主。每次选择新输出目录。模型通过校验后才生成 `answer.md` 并向下一帧传递计划，原始调用记录保存在 `result.json`。`--catalog-history` 将上一帧事实正文改为可按 ID 取回的目录。`--previous-bundle` 和 `--previous-answer` 用于从指定前卡继续。[真实输入、对照和验收结果](reports/round_agent_acceptance_20261112.md)

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

## 1. 安装和公开离线检查

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt -r requirements-map.txt
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
