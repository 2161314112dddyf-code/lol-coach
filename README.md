# LoL Coach：英雄联盟 AI 赛后回合复盘

先建立可核验的地图空间、英雄机制、行动耗时和真人经验，再组织当时可知的局势，让通用模型比较行动、说明依据与换计划条件。英雄判断必须结合队友和对手。当前是 Python 数据与分析工具，没有前端或微调模型，完整自动赛后复盘尚未完成。

## 从这里接手

1. [当前任务](lol-coach/docs/CURRENT_TASK.md)：本轮交付及下一切片。
2. **[后续推进指南](lol-coach/docs/DEVELOPMENT_GUIDE.md)**：实际链路、依赖、任务顺序、输入输出、验收和停止条件。
3. [项目现状总结](lol-coach/docs/PROJECT_SUMMARY.md)：已完成、尚未解出、已导出未接入的区别。
4. [项目宪法](lol-coach/docs/PROJECT_CONSTITUTION.md)与[落实约定](lol-coach/docs/WORKFLOW.md)：版本、证据、检查与责任。

项目主体在`lol-coach/`；根目录的分包器、移动解码器和冻结字节映射仍是依赖，不要单独移动子目录。`FIRST_TASK.md`与初始交接原文仅为历史需求，不要重复初始化项目。

## 当前能力（2026-10-28整理）

- 有固定版本静态资料、地图基础、限定回放的移动/生命/经济/身份等导出，以及按时刻和队伍过滤的快照。
- 四份研究回放的**兵线与营地身份分类限定通过**；连续兵线状态、实际施法/冷却、完整连续背包、区域视野仍不完整。详见[四项逆向边界](lol-coach/reports/replay_completion_progress.md)。
- 已实现冻结决策帧、按需资料查询、结构化答案检查、有限修订和中文卡。14个模拟场景用于迭代；同一真实回放的三个时刻完成实际Codex分析。一次超时保留失败后恢复，最终3份结构与引用通过，**不是战术准确率**。[模拟结果](lol-coach/docs/回合复盘方案_v0.1/SIMULATION_RESULTS.md)、[真实试跑](lol-coach/docs/回合复盘方案_v0.1/REAL_REPLAY_RESULTS.md)。
- 2026-10-26完整回归实际599项通过。本次公开源码副本验证以[同步报告](lol-coach/reports/github_sync_20261028.md)为准，不沿用旧284项作为当前结果。

下一项是把已有兵线/单位导出通过可用时刻、可见性与来源检查接入决策帧，再串联相邻回合计划；当前不要求用户重新开游戏或补录。未来模型/训练步骤见推进指南，不用新增机制案例绕开当前主线。

## 安装与公开离线检查

Python 3.11+；原开发环境Python 3.13.7。仓库根目录执行：

```powershell
cd lol-coach
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt -r requirements-map.txt
.venv/Scripts/python.exe -m pytest -q --basetemp .test-tmp-public-new
.venv/Scripts/python.exe -m lol_coach --help
.venv/Scripts/python.exe scripts/reasoning.py --help
.venv/Scripts/python.exe scripts/simulate_reasoning.py --help
.venv/Scripts/python.exe scripts/run_reasoning_session.py --help
```

Linux/macOS用`.venv/bin/python`。安装依赖需要网络；上述测试/帮助不需要游戏、密钥或私人回放。重跑须换一个新的临时目录以保留旧证据。Python 3.11+是声明支持范围，实际验证环境另记，不代表逐版本测试过。

## 真实局势与模型怎么运行

有本地兼容回放及配套导出、缓存后，运行`reasoning.py prepare`冻结指定时刻；通过`get_reference`查询机制，再用`run_reasoning_session.py`接收宿主模型响应，生成检查结果和中文卡。[模型框架与命令](lol-coach/docs/回合复盘方案_v0.1/REASONING_FRAMEWORK.md)、[文件会话协议](lol-coach/reports/real_reasoning_validation.md)。文件会话CLI会等待响应端，**不会自行调用模型API**。

首次获取官方静态英雄数据需要网络，例如：

```powershell
.venv/Scripts/python.exe -m lol_coach fetch-champion --patch 16.20.1 --champion Ivern
```

示例英雄不限定产品范围。解码器限定研究构建`16.20.824.8524`，不保证其他版本。`research_*`、部分`verify_*`和批量重建脚本依赖原样本、客户端/工具和缓存，不能把它们当作公开克隆的通用启动命令。

## 证据与公开范围

公开源码、版本规则、测试、来源索引和Markdown报告；私人回放、录像、客户端、缓存、派生数据与完整运行记录留在本地。历史文档中的`data/private/`和未收录JSON是本地证据定位，不是GitHub可下载资产。报告摘要可公开阅读，但公开读者不能仅凭摘要独立复核全部真实样本结论。

[状态与历史](lol-coach/reports/STATUS.md)记录完成声明、反例与缺口。软件测试通过不等于字段全部正确；模型格式通过不等于最佳策略；自动复核不代替人工签署。本次用户授权同步GitHub，不等于产品或战术验收。

公开可见不等于授予开源许可；目前没有新增许可证，第三方资料权利归属不变。
