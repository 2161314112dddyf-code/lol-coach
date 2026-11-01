# LoL Coach：英雄联盟 AI 赛后复盘

先建立可核验的地图空间、英雄机制、行动耗时和真人经验，再组织当时可知的局势，让通用模型比较行动、解释依据和改选条件。英雄判断结合队友与对手。当前为Python/CLI，没有前端或微调模型，完整自动复盘尚未验收。

## 从这里开始

- [文档索引](lol-coach/docs/INDEX.md)：现行文档、实验清单和历史资料的统一导航。
- [当前接管点](lol-coach/docs/CURRENT_TASK.md)：最近交付与实际待办。
- [能力现状](lol-coach/docs/PROJECT_SUMMARY.md)：已实现、未知和未验收的区别。
- [推进与验收规则](lol-coach/docs/DEVELOPMENT_GUIDE.md)：输入输出、约束、后续依赖。
- [当前阶段全部实验](lol-coach/docs/CURRENT_STAGE_EXPERIMENTS_20261101.txt)：可直接照做的完整操作单。

项目主体在`lol-coach/`。仓库根目录的分包器、移动解码器和冻结字节映射仍是依赖，不能只复制子目录。最初的FIRST_TASK仅是历史任务。

## 当前能力（2026-11-01）

| 层 | 已有能力 | 仍有限制 |
| --- | --- | --- |
| 基础与解码 | 版本化静态资料、地图基础，限定16.20回放的身份、路径、生命/资源、经济等导出 | 实际施法/冷却、完整连续背包和区域视野未全解 |
| 可知局势 | 按时刻/队伍过滤；可见活兵、持续HP、估计位置与分组进入决策帧 | 隐藏单位、精确模拟位置和线权不自动补全 |
| 时间工具 | 条件移动计算、冻结预测和改令/速度/死亡/视野等失效处理 | 实局到达证据不足，数值ETA仍未进入模型 |
| 分析链路 | 冻结输入、按需查资料、前卡承接、结构化回答与中文卡 | 契约通过不等于战术正确；旧建议不证明执行 |
| 整段组织 | 实际175时刻生成34检查点、保留141未选时刻；170变化候选完整保留 | 工程调度不是已验收回合，独立标签仍为空 |
| 新版兼容 | 16.21.829.9102容器已完整分包 | 游戏字段语义尚未适配，不能套旧opcode/字节表 |

[最新离线交付](lol-coach/docs/OFFLINE_FINISH_RESULTS.md)包含两次实际宿主分析、修订及限制；[同步检查记录](lol-coach/reports/github_sync_20261101.md)记录本次公开源码验证。不含私人回放和缓存的公开源码副本已实际通过1223项测试；真实数据和战术效果按各自证据另判。

## 安装和不依赖私人素材的检查

声明支持Python 3.11+；实际开发验证使用Python 3.13.7。仓库根目录执行：

```powershell
cd lol-coach
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt -r requirements-map.txt
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp-public-new
.venv/Scripts/python.exe -m lol_coach --help
.venv/Scripts/python.exe scripts/reasoning.py --help
.venv/Scripts/python.exe scripts/build_review_sequence.py --help
```

Linux/macOS用`.venv/bin/python`。安装依赖需要网络；测试与帮助入口不需要游戏、密钥或私人回放。重复测试使用新的临时目录以保留旧证据。没有声称已逐一测试所有Python版本。

## 使用真实数据

具体命令见[项目运行手册](lol-coach/README.md)。需要已有兼容回放及配套导出/缓存后，才能重建真实局势。文件模型会话需要宿主提供响应，CLI不会自行调用供应商API。`research_*`和部分批量脚本是版本限定研究工具，不是任意回放通用解析器。

## 公开范围

公开源码、规则、测试、来源索引及可读报告。原始回放、录像、客户端、缓存、派生数据和完整机器记录留本地，不随仓库发布。文档里的`data/private/`与未纳入Git的JSON是本地证据定位，不能在GitHub下载；公开副本可运行离线测试，但不能凭空重现全部私有实局结果。

[项目宪法](lol-coach/docs/PROJECT_CONSTITUTION.md)和[落实规则](lol-coach/docs/WORKFLOW.md)保持有效。代码发布不等于人工战术验收。公开可见不自动授予开源许可，目前没有新增许可证；第三方资料权利不变。
