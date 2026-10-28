# GOV-002-SYNC：公开同步与后续交接记录

日期：2026-10-28。用户明确要求更新GitHub并补充可指导推进的Markdown。[任务卡](../docs/GITHUB_SYNC_TASK.md)、[后续推进指南](../docs/DEVELOPMENT_GUIDE.md)、[当前任务](../docs/CURRENT_TASK.md)。

## 这次同步什么

远端及本地原基线为`e0b3a84d14aca40dcdc173182ec268946ed15482`。同步基线之后已存在的RPL-008计数/对象身份增量、国服调研、模型决策框架、模拟迭代与真实三时刻试跑的源码、规则、测试和可读报告。本次新增的是文档交接整理，没有新解码或模型能力。

新增推进指南把后续工作固定为：ROUND-006-JOIN逐字段可知性接入 → ROUND-007-CHAIN相邻回合计划 → 有证据的一类动作时间 → 独立战术评测。指南提供输入输出、允许改动、L1—L5 GWT与完成/停止条件；不能把身份分类直接升级为当前兵线状态。训练只在数据权利、标签、基线和持续错误都明确后再决定。

修正根/项目README、START_HERE、项目总结、分析信息清单、剩余解码矩阵、AGENTS、WORKFLOW及CURRENT_TASK/STATUS；历史初始任务、旧分母、真实失败仍保留。2026-10-21旧总结与RPL-007旧矩阵标为历史，不再驱动重复初始化或重复逆向。宪法原文内容不变。

公开实验记录CSV仅含表头，`.gitignore`增加这一个模板的窄范围例外。私人回放、视频、客户端、缓存、私有派生数据和完整机器报告仍不提交。新增报告中本地证据链接已明确标注为本地定位，公开MD保留结论、命令和限制。

## 实际验证

从Git可公开文件清单复制333份源文件构造新目录，没有复制私人素材。使用原开发环境的Python **3.13.7**运行，不是全新机器/依赖安装测试。之后的文档收尾另做链接和内容检查，产品源码、配置和测试与被测副本保持一致。暂存检查发现历史研究脚本`research_spell_all_attribute_join.py`第15行尾随空白，仅清掉空白并核对Python AST完全一致；未重跑该研究实验，修正前后哈希另存。

```powershell
# cwd：data/private/github_sync_20261028/public-source/lol-coach
# 使用原项目.venv的Python，临时目录为新的独立目录
python -m pytest -q --basetemp <new-private-test-directory>
python -m lol_coach --help
python scripts/reasoning.py --help
python scripts/simulate_reasoning.py --help
python scripts/run_reasoning_session.py --help
```

完整回归实际 **599 passed in 8.36s，exit_code=0，stderr为空**。四条CLI帮助均exit_code=0。原始完整命令、输出、Python版本、源码清单和哈希留在`data/private/github_sync_20261028/pytest-public.json`、`cli-help-public.json`和`source-manifest-before-tests.json`；这些文件不随公开仓库分发。

检查不证明真实游戏字段全部正确，也不证明模型战术正确。14题合成迭代与3个真实时刻试跑属于此前执行，本轮没有重新调用模型；其失败/恢复和限定结果按原报告保留。

| 验收ID | 状态 | 范围与证据 |
| --- | --- | --- |
| G1 文档可接手 | PASS | README→CURRENT_TASK→DEVELOPMENT_GUIDE；明确下一切片、输入输出、GWT、停止与恢复 |
| G2 状态真实 | PASS | 与RPL-008、ROUND-004/005代码及记录对照；原宪法哈希保持，旧历史保留；未伪造签署 |
| G3 公开可运行范围 | PASS | 公开源码副本599项回归与4条CLI帮助；测试源码和最终产品源码逐文件一致 |
| G4 公开同步 | PASS | 内容提交`4ad43af5b966f6456213d57a2991591c8e154a2f`已推送到public仓库main；`ls-remote`与本地HEAD完全相同。后续回执提交只更新文档 |

公开清单初审的71个未提交文件均为UTF-8文本、最大约50KB；未见原始媒体/客户端或扫描规则命中的凭据。收尾后的内容提交包含82个变更文件，仓库共334个公开文件；44处当前推进文档链接指向公开文件。237份被测源码/配置等逐字节未变，另1份研究脚本仅去空白且AST一致。忽略边界、UTF-8、暂存空白、宪法哈希及历史保留检查通过；这一限定检查不称全面安全审计。

## 连接失败、恢复与版本

首次`git fetch origin`因已配置的`127.0.0.1:10808`代理未运行而连接失败。GitHub连接工具独立读取仓库，确认其为public且有写权限；随后仅对该次Git命令覆盖http/https代理为空，fetch成功，远端仍为原基线。未修改全局代理或凭据配置。

随后直连再次出现连接重置/超时；GitHub连接工具创建树对象返回403 `Resource not accessible by integration`，未成功写入。`gh auth status`也未通过，未修改或删除凭据。检查发现已有Clash/Mihomo正在监听127.0.0.1:7897，Git配置仍指向旧端口；仅对本次Git命令指定已运行代理后，使用原Git认证正常推送成功，没有强推。

实际内容提交：[4ad43af](https://github.com/2161314112dddyf-code/lol-coach/commit/4ad43af5b966f6456213d57a2991591c8e154a2f)，82个文件、6876行新增、69行删除。推送后读取`refs/heads/main`得到同一完整SHA，与本地HEAD一致。此后只补这份发布回执与任务/状态中的提交入口，代码与测试不变；最终文档回执提交可从Git历史查看。完整本地回执在`data/private/github_sync_20261028/publication-content.json`。

本次用户授权提交/推送现有公开仓库，因此没有另行要求同一发布确认；没有更改全局代理、凭据配置或仓库公开范围，也没有覆盖远端不同历史。

恢复点：`data/private/document_backups/GOV-002-SYNC-20261028/manifest.json`与逐文件副本；同步前Git基线如上。回退用逐文件比较或新的修复提交，不整目录覆盖后续工作。

实施、自检与文档审查主体：Codex（含分工只读检查），不是外部教练。人工签署：未提供；战术质量：未独立验收。费用/Token未取得。下一任务ROUND-006-JOIN可用现有素材直接推进，当前没有要求用户补录、提供密钥或重新启动游戏的步骤。
