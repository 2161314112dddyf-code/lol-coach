# 项目运行手册

更新：2026-11-01。能力边界见[项目现状](docs/PROJECT_SUMMARY.md)，执行顺序见[当前接管点](docs/CURRENT_TASK.md)，全部资料见[文档索引](docs/INDEX.md)。以下命令在`lol-coach/`执行，输出路径使用尚不存在的新文件/目录。

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

- 新版容器/旧规则探测：`scripts/probe_new_replay_compatibility.py`、`scripts/research_new_build_families.py`，需要脚本指定的本地样本。
- 时间冻结/失效：[时间结果](docs/ACTION_TIME_TEST_RESULTS.md)、[失效结果](docs/TRAVEL_VALIDITY_RESULTS.md)。当前模型`calculations`仍不填未验证ETA。
- 其他字段与对照：[最新离线交付](docs/OFFLINE_FINISH_RESULTS.md)、[完整实验操作单](docs/CURRENT_STAGE_EXPERIMENTS_20261101.txt)。先短预检，不让用户盲录长实验。
- 更早命令及阶段细节保留在[整理前运行手册](docs/history/PROJECT_README_before_20261101.md)和各报告；历史命令可能依赖原机器素材，不作为公开启动流程。

## 7. 数据与验证边界

16.20.824.8524是主要游戏字段研究构建；16.21.829.9102仅容器恢复，游戏语义未适配。实际施法/冷却、完整连续背包、区域视野和可靠实局到达时间仍有缺口。身份已解、当时可知、进入模型、战术正确是不同验收层。

原始ROFL/视频/客户端、缓存、`data/private`及完整机器报告不公开。文档的私有路径仅供本机追溯。所有历史失败和未验收项保留在[STATUS](reports/STATUS.md)，不由测试数量或发布状态替代。
