# 实验交接入口

更新于 2026-11-12。[进游戏照做的实验单](CURRENT_STAGE_EXPERIMENTS_20261101.txt)与桌面 TXT 同步。第一局使用拉克丝，完成空地施法和三趟移动后即可交原视频及同局 ROFL。第二局测背包槽位，第三局需要两人配合记录视野。

第一局对应 E00、S01/S02、M01～M03，第二局对应 I02/I03，第三局对应 V01。其他控制变量和完整验收口径见[工程实验设计](CONTROLLED_REPLAY_EXPERIMENTS.md)。R01 人工评阅的方法见[可行性实验报告](../reports/hf_experiment_feasibility_20261111.md)。

推进 Agent 工具链可直接使用现有帧。只有验证国服动作语义或到达时间时才检查同构建匹配素材；缺哪一项，才做 E00 中对应动作。旧 ec 的映射仍需旧构建证据。玩家新增 S/I/M/V 对照和独立战术盲评均待执行。

为什么需要这些对照，见[原对照设计](CONTROLLED_REPLAY_EXPERIMENTS.md)；当前离线工作及剩余阻断见[最新交付](OFFLINE_FINISH_RESULTS.md)。
