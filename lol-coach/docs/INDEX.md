# 文档索引

更新：2026-11-01。现行入口负责当前状态，任务卡/报告负责证据，历史快照只供追溯。不要把旧文档里的“下一步”当作当前指令。

## 现行入口

| 想了解什么 | 读哪里 |
| --- | --- |
| 课程表单第 5 题的七项材料 | [完成情况、证据与复验命令](COURSE_SUBMISSION.md) |
| 安装、公开测试、仓库边界 | [根README](../../README.md) |
| 实际命令和私有数据前提 | [项目运行手册](../README.md) |
| 最新接管点与待办 | [CURRENT_TASK](CURRENT_TASK.md) |
| 已实现能力与未解缺口 | [PROJECT_SUMMARY](PROJECT_SUMMARY.md) |
| 后续依赖、验收、模型与训练边界 | [DEVELOPMENT_GUIDE](DEVELOPMENT_GUIDE.md) |
| 当前阶段全部实验，逐步操作 | [完整实验操作单TXT](CURRENT_STAGE_EXPERIMENTS_20261101.txt) |
| 哪些录像可以省、哪些仍需同局对照 | [公开数据可行性实测与国服补证范围](../reports/hf_experiment_feasibility_20261111.md) |
| 哪些事情依赖录像 | [依赖表](VIDEO_AND_OFFLINE_BACKLOG.md) |
| 宪法原文与执行规则 | [PROJECT_CONSTITUTION](PROJECT_CONSTITUTION.md)、[WORKFLOW](WORKFLOW.md)、[AGENTS](../AGENTS.md) |

## 最近交付及证据

| 主题 | 结果 | 规格/任务卡 |
| --- | --- | --- |
| 整段调度、资料接入、真实承接、外部标签工具 | [OFFLINE-003](OFFLINE_FINISH_RESULTS.md) | [任务卡](OFFLINE_FINISH_TASK.md) |
| 新版容器、原包检查与候选导出 | [OFFLINE-002](OFFLINE_EXECUTION_RESULTS.md) | [任务卡](OFFLINE_EXECUTION_TASK.md) |
| 兵线可知视图 | [兵线结果](LANE_WAVE_RESULTS.md) | [任务卡](LANE_WAVE_TASK.md)、[基础研究](LANE_DYNAMICS_TASK.md) |
| 前后计划承接 | [链路结果](ROUND_CHAIN_RESULTS.md) | [任务卡](ROUND_CHAIN_TASK.md) |
| 时间预测、失效与已有视频核查 | [时间](ACTION_TIME_TEST_RESULTS.md)、[失效](TRAVEL_VALIDITY_RESULTS.md)、[补证](TRAVEL_EVIDENCE_RESULTS.md) | [时间验收T5/T6](ACTION_TIME_TEST_TASK.md)、[失效规格](TRAVEL_VALIDITY_TASK.md)、[补证规格](TRAVEL_EVIDENCE_TASK.md) |
| 文档整理及公开同步 | [同步记录](../reports/github_sync_20261101.md) | [任务卡](DOCUMENT_CLEANUP_SYNC_TASK.md) |

完整历次执行按时间保留在[STATUS](../reports/STATUS.md)。报告中的私人路径和未公开JSON是本地证据指针，不是缺失的公开下载文件。

## 专题资料与设计依据

- [复盘 Agent 技术实施方案](回合复盘方案_v0.1/AGENT_MCP_IMPLEMENTATION.md)包含代码接入点、工具参数契约和两帧验收命令草案。

- [复盘 Agent 与 MCP 设计稿](回合复盘方案_v0.1/AGENT_MCP_REVIEW_DESIGN.md)涵盖回合判断、时间余量计算、工具权限和同帧对照实验。

- [项目初始目标](PROJECT_BRIEF.md)、[原始首轮任务](FIRST_TASK.md)、[来源索引](SOURCES.md)：背景，不重复初始化。
- [宏观快照结构](MACRO_SNAPSHOT.md)、[分析信息需求](ANALYSIS_INFORMATION_REQUIREMENTS.md)、[地图格式](MAP_FORMAT_NOTES.md)：接口/研究背景；当前覆盖以能力总结为准。
- [国服调研、回合框架、模型使用与模拟记录](回合复盘方案_v0.1/README.md)：保留来源阅读级别和历史草案身份。
- [对照实验原设计](CONTROLLED_REPLAY_EXPERIMENTS.md)：竞争解释与分析方法。实际采集步骤以完整TXT为准，避免两份操作清单漂移。
- [早期四项逆向进度](../reports/replay_completion_progress.md)、[旧剩余矩阵](../reports/remaining_decode_matrix.md)：历史证据，后续兵线/物品计数等变化见最新交付。

## 历史与维护规则

[整理前文档归档](history/README.md)保留多轮追加原文。其他`*_TASK.md`和旧日期报告仍保留在原路径，避免破坏引用；它们是该切片规格/执行历史，不是同时生效的当前任务队列。

更新能力时修改PROJECT_SUMMARY；更新接管点时修改CURRENT_TASK；运行方式放项目README；每轮证据追加STATUS并链接专门报告。不要再次向所有入口粘贴整段历史更新。宪法原文和原始实验文件不随文档整理改写。
