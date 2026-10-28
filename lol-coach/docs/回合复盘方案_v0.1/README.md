# 回合复盘方案 v0.1

继续实施先读[后续推进指南](../DEVELOPMENT_GUIDE.md)：下一项是已有兵线信息的可知性接入，再做相邻回合计划。本目录保存研究依据、方案演进与试跑结果；原数值门槛仍为草案，当前任务以[任务入口](../CURRENT_TASK.md)为准。

这次讨论的材料集中在这里。**最新进展先看[真实回放三个时刻的试跑结果](REAL_REPLAY_RESULTS.md)**：实际模型与资料查询闭环、建议随信息变化，以及一次超时后的恢复。[模拟场景测试与迭代](SIMULATION_RESULTS.md)保留14个合成场景、首轮失败及三处修订。[大模型复盘思考框架](REASONING_FRAMEWORK.md)说明局势组织、思考顺序、模型调用方式、运行命令与实际边界；首版记录见[交付与验证记录](../../reports/reasoning_framework_validation.md)。

调研依据见[国服调研结论](CN_REVIEW_FINDINGS.md)：46项去重来源的实际阅读范围、六个关键发现，以及对原方案的修改建议。

## 主线阅读

1. **[方案简稿](ROUND_REVIEW_V0_1.md)**：先看这份，包含处理链路、回合定义、模型用法、训练规划和拟定验收标准。
2. **[具体场景与分析答案](ROUND_REVIEW_EXAMPLE.md)**：公开真实案例，以及现有回放4分43秒的分析。
3. [实现与验收细则](ROUND_PIPELINE_SPEC_V0_1.md)：需要讨论接口、判分和训练数据时再看。
4. [调研来源与阅读范围](round_review_research_20261023.md)：原始链接、采用的观点及证据边界。

## 国服补充研究（2026-10-23）

- **[国服结论简稿](CN_REVIEW_FINDINGS.md)**：短版，先读这份。
- **[链路补充、三个条件场景与六道对照题](CN_PIPELINE_ADDITIONS.md)**：讨论具体怎么分析、怎么验收与训练。
- [打野与资源回合来源17项](CN_JUNGLE_SOURCES.md)。
- [对线、兵线、辅助来源17项](CN_LANES_SOURCES.md)。
- [国服环境与经验迁移来源8项](CN_ENVIRONMENT_SOURCES.md)。
- [官方规则与楚钧回合理论入口4项](CN_OFFICIAL_AND_ROUND_SOURCES.md)。
- [完整来源索引与可复算计数](CN_SOURCE_INDEX.json)、[本轮任务与有限验收](CN_RESEARCH_TASK.md)。

文档仍为讨论初稿；新增观点与验收建议没有写成已实现能力。视频入口、平台智能文稿、原作者正文分开登记，本轮没有完整观看新的国服录像。文档自检见[检查记录](../../reports/cn_review_research_check_20261023.json)。
