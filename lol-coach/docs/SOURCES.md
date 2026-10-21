# 待核验资源登记

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

只读访问官方和公开允许的数据；尊重认证、限流和许可。
源站描述了一个 API，不等于已拿到实际响应。能下载文件，不等于已正确解释文件。
不要为缺失地图、路径时间、营地时间或真人经验伪造可信样本。
不必首轮深挖所有来源；按照 FIRST_TASK 的最小闭环推进。
