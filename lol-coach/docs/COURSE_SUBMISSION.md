# 课程第 5 题 · 完成情况

项目为英雄联盟 AI 赛后决策复盘。本页按 2026-11-11 表单列出可从 Git 检查的材料。实现与测试数字引用 2026-11-01 的公开基线 `a31d118` 及其中的运行记录。11 月后续讨论中的方案单列为提案。伙伴对最终成果的测试尚待实际执行。

| 表单选项 | 提交材料 | 核查方法 |
| --- | --- | --- |
| 需求 | [项目目标与用户场景](PROJECT_BRIEF.md)、[已批准的基础阶段范围](FOUNDATION_ACCEPTANCE.md) | 从一局回放、一个玩家和决策时刻出发，结合资源、人物动向、经济装备以及双方阵容，解释可选行动、代价和改选条件。基础范围的批准记录只覆盖对应阶段。 |
| 规约 | [模型输入与输出契约](回合复盘方案_v0.1/REASONING_FRAMEWORK.md)、[整段处理的 GWT 验收条件](OFFLINE_FINISH_TASK.md) | 改动未来数据或隐藏敌情后，同一时刻的模型输入应保持一致。上一张卡的建议进入历史，后续要用新观测才能判断是否实际执行。 |
| ADR、前置调研与研究路线 | [架构决策记录](ARCHITECTURE_DECISIONS.md)、[自建复盘 Agent 与 MCP 设计稿](回合复盘方案_v0.1/AGENT_MCP_REVIEW_DESIGN.md)、[技术实施方案](回合复盘方案_v0.1/AGENT_MCP_IMPLEMENTATION.md) | ADR-04 记录拟议架构。设计稿用 5:00 和 5:20 两帧说明如何比较行动与调整计划，实施方案给出三个工具和分阶段验收条件。[行动比较参数契约](回合复盘方案_v0.1/compare_actions.v1.schema.json)可单独校验；MCP 服务的端到端运行待实现。 |
| 项目级 Harness | [AI 与工程约定](../AGENTS.md)、[工程工作流](WORKFLOW.md)、[开发与验收指南](DEVELOPMENT_GUIDE.md)、[运行手册](../README.md) | 代码沿用 Python 包和 CLI，复用已有模块，以对应测试核对行为。每项任务写明改动范围及恢复点。文档依职责维护，报告登记版本、命令、结果和失败。输入、事实引用和输出之间应能追溯。 |
| Global、Plan、Tasks | [总体目标](PROJECT_BRIEF.md)、[首轮任务与初期顺序](FIRST_TASK.md)、[路线图](ROADMAP.md)、[任务拆分规范](DEVELOPMENT_GUIDE.md)、[具体任务卡](OFFLINE_FINISH_TASK.md) | 初期先核验数据、地图、机制与行动耗时，再构建当时可知的局势，最后接入模型比较行动。任务卡记录输入、输出、验收条件、检查和恢复点；[接管点](CURRENT_TASK.md)记录已交付和待办。 |
| 可执行或验证的部分代码及评测证据 | [决策帧实现](../lol_coach/reasoning_frame.py)、[决策帧测试](../tests/test_reasoning_frame.py)、[评测实现](../lol_coach/review_evaluation.py)、[公开副本测试记录](../reports/github_sync_20261101.md)、[实际样例及修订](OFFLINE_FINISH_RESULTS.md) | 可在没有私人回放的副本运行下面的测试，对照已提交报告。实局卡另有输入前提。 |
| 其他（数据集、训练或微调说明） | [数据来源、样本范围与训练状态](DATA_AND_TRAINING.md) | 可核查公开样例、局内私有数据、合成语料的不同用途和评测限制。本阶段使用通用模型，未开展微调。 |

## 项目级 Harness 的执行方式

- **开发与 AI 操作。** 先用任务卡约定输入、输出、允许改动和验收，再做最小修改。外部攻略、字幕和回放元数据均作资料读取。人工判断、伙伴复核和签署保留实际执行者身份。
- **代码与文档。** 解析和判断逻辑放在现有 Python 模块，CLI 负责接收参数和写出结果。字段变更同时核对读取方、时间和版本含义，缺失值保留未知。运行方法更新项目 README，能力边界更新 PROJECT_SUMMARY，运行历史记入 STATUS。
- **日志与可观测性。** 实局检查记录对局和构建、时刻、观察队伍、输入标识、执行命令、期望与实际结果及证据位置。一次修订用新输出目录，保留失败版本。复核一项建议时，从分析卡的事实引用回查该帧的观测时间及来源；公开报告保留结果摘要，私人素材和完整会话按原约定留本机。

## 伙伴可独立执行的一组检查

按[项目运行手册](../README.md)安装依赖，在 `lol-coach/` 目录使用项目虚拟环境执行以下命令。其一检查未来信息和隐藏敌情，其二检查上一条建议如何传到下一帧，其三检查没有人工标签时是否保留空分数。

```console
python -m pytest -q tests/test_reasoning_frame.py::test_future_hidden_metadata_and_source_hash_do_not_change_model_input
python -m pytest -q tests/test_round_chain.py::test_previous_references_are_historical_and_not_execution
python -m pytest -q tests/test_review_evaluation.py::test_no_labels_is_no_score
```

公开源码副本在 11 月 1 日的历史运行记录为 1,223 项通过。当天另有 300 秒、320 秒两个真实输入的宿主会话，修正过一条依赖队友保护的退路建议。两者分别支持软件行为核查和有限案例复查。整局自动复盘质量及独立战术评价仍待验收。[软件运行记录](../reports/github_sync_20261101.md) · [会话结果与证据范围](OFFLINE_FINISH_RESULTS.md)
