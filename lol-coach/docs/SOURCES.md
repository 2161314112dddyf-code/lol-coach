# 待核验资源登记

2026-11-19 中文社区扩采：新增74个去重资源入口，其中51个论坛讨论串；29个读到正文或相关楼层，45个只有搜索片段/元数据。具体阅读边界、作者、日期、旧版本限制、争议和查询记录保存在[资源目录](knowledge/中文社区资源索引.md)及其JSON。筛选15个已读来源进入手册，新增8卡、补充2卡，现为24卡32源；仅索引资料未成为机器依据。[经验取舍](knowledge/中文社区经验补充.md) · [实际验收](../reports/中文社区资源扩采_20261119.md)

2026-11-19 首版增加[连续决策知识手册](knowledge/README.md)。当时核读14份不同教学正文，另沿用3部已核选段的小汤宝视频，整理16张条件卡并接入Agent。逐项作者、链接、阅读范围、拒绝采用的绝对化规则和版本边界保存在两份专题及 `lol_coach/profiles/coaching_handbook_v1.json`。视频访问失败与字幕为空的条目只保留入口，不算已看过。工程验收见[首版报告](../reports/知识手册接入_20261119.md)。

技能与符文现有三种本地证据可回查。Riot 历史发布版提供中文符文页和物品原文；同构建游戏 WAD 的数值表、技能标签和说明绑定用于分段计算；ROFL 的赛前选页与本人的同秒面板决定本帧采用哪些参数。赛后符文计数仅用于独立核对。实际使用的归档、SHA-256 和复跑入口见[本地伤害资料](../reports/符文伤害与本地预加载_20261116.md)。

Riot Data Dragon 和腾讯 101 已进入个人复盘的本地数据链路。每次同步保存实际访问的 URL、时间、原始响应哈希、数据版本或请求的补丁，以及腾讯的统计日。版本查询可阅读 [Riot 版本目录](https://ddragon.leagueoflegends.com/api/versions.json)，国服分路和统计维度见[实际取表记录](回合复盘方案_v0.1/版本打法与对位数据源_20261112.md)，操作步骤见[运行手册](../README.md#更新复盘使用的公开数据)。

已按播放器时间核对小汤宝的打野攻守教学及实战片段，另列五篇 LoL 研究。[原片、论文与适用范围](回合复盘方案_v0.1/小汤宝的回合论与LoL论文_20261112.md)

版本打法、国服分时长胜率、对位时间线和出装已有 2026-11-12 的实际查询记录。见[单人复盘用哪些版本统计](回合复盘方案_v0.1/版本打法与对位数据源_20261112.md)。下表保留最初的线索。

以下是从当前聊天整理的检索线索，不是本轮重新验证的技术事实。某些此前讨论中的可用性、版本或字段判断可能过时或不完整。
**Codex 必须实际访问文档/样本，记录证据，再更新状态。** 不凭本文件认定授权、兼容性或完整性。
`docs/source_candidates.json` 可作为资源探测输入。

| ID | 入口 | 初步用途 | 核验重点 |
|---|---|---|---|
| riot-docs | https://developer.riotgames.com/docs/lol | 官方接口及静态数据文档 | 公共路由、字段、实际粒度、版本、政策 |
| ddragon-versions | https://ddragon.leagueoflegends.com/api/versions.json | 获取可下载数据版本 | 和目标客户端版本是不同的核验项 |
| cdragon | https://raw.communitydragon.org/ | 客户端资源与配置候选 | 版本目录、文件格式、字段意义、许可 |
| cdragon-map11 | https://raw.communitydragon.org/latest/game/data/maps/shipping/map11/ | 地图配置线索 | 不是已取得的 NGRID，latest 仅为探索入口 |
| ngrid | https://github.com/FrankTheBoxMonster/LoL-NGRID-converter | 导航网格解析候选 | 支持格式、当前资产、网格尺度、碰撞和动态障碍 |
| cdtb | https://github.com/CommunityDragon/CDTB | 资源包提取候选 | 与 ROFL 不同；读取格式和许可证后再使用 |
| cdragon-hashes | https://github.com/CommunityDragon/Data | 路径与字段哈希映射 | 版本和不完整映射 |
| meraki | https://github.com/meraki-analytics/lolstaticdata | 可读英雄机制资料及生成代码 | 来源、实际更新、复杂交互和许可 |
| meraki-ivern | https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions/Ivern.json | 机制数据样本 | latest 不代表已验证当前版本；空值与字符串 |
| meta-wiki | https://github.com/LeagueToolkit/lol-meta-wiki | 底层类与属性说明 | 文档和实际接口的可用性分开验证 |
| meta-api | https://meta-api.leaguetoolkit.dev/v1 | 配置说明 API 候选 | 响应、字段解释、来源、并非实时对局 |
| league-toolkit | https://github.com/LeagueToolkit/LeagueToolkit | 游戏资产处理库候选 | 不默认支持模拟和当前格式 |
| live-sample | https://static.developer.riotgames.com/docs/lol/liveclientdata_sample.json | 官方本地数据接口样本 | 示例不是本局数据，也不证明拥有完整全员状态 |
| replay | https://github.com/riotgames/leaguedirector | 回放控制与核验素材候选 | 不等于完整历史状态或反事实模拟 |
| rofl | https://github.com/Mowokuma/ROFL | 回放位置与眼位解析候选 | 维护情况、目标版本、字段实测、来源与许可 |
| lolpt | https://lolpt.gg/ | 用户发现的对局分析网站 | 未取得其公开 API/授权；不能默认已逆向 ROFL |
| clears | https://www.reddit.com/r/Jungle_Mains/comments/1ac12do/a_spreadsheet_for_optimal_jungle_clears_in_s14/ | 刷野实测作者和表格线索 | 表格实际可读性、版本、操作条件、使用许可 |
| jungler | https://jungler.gg/ | 路线与打法资料候选 | 实际补丁、统计范围、来源、无默认批量 API 授权 |
| ivern-guide | https://dignitas.gg/articles/a-guide-to-ivern-with-dig-exyu | 人类英雄/队友经验示例 | 历史材料，核对原意与适用版本；不是当前必选打法 |
| lolalytics | https://lolalytics.com/ | 阵容与英雄统计候选 | 样本与版本；统计不等于当前行动因果收益 |

## 使用原则

2026-11-07 的 [Hugging Face 资源实查](HUGGING_FACE_SOURCES_20261107.md) 附真实旧版解码包、排位时间线、视频解说与小地图标注样本，并标明各自能验证的项目字段和版本。

只读访问官方和公开允许的数据；尊重认证、限流和许可。
源站描述了一个 API，不等于已拿到实际响应。能下载文件，不等于已正确解释文件。
不要为缺失地图、路径时间、营地时间或真人经验伪造可信样本。
不必首轮深挖所有来源；按照 FIRST_TASK 的最小闭环推进。
