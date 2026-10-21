# 首轮入口核验

日期 2026-10-11。原始证据索引见 `source_audit.json`、`entry_evidence.json`，evidence_path 均相对于 `data/`。仓库代码与 README 固定到本次读取的提交，未执行第三方代码。

## 官方英雄基础数据

实际下载了 [官方版本列表](https://ddragon.leagueoflegends.com/api/versions.json) 和 [16.20.1 Ivern](https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Ivern.json)。列表包含 16.20.1，响应 version=16.20.1、id=Ivern、key=427。

基础移速 330、攻击距离 475、生命 630、法力 450，被动与 Q/W/E/R 保留原描述及字段路径。目标客户端版本未匹配，地图/模式为 null。单位是工具对基础字段的语义标注，未实测地图尺度。原始英雄 SHA256：`984e6a1c8f51e7ddbf01c186c956739047f754aebdae5045a363af9a4ee4c47d`。规范化文件与相邻 manifest 包含 UTC 时间、URL、哈希及版本列表证据。

官方文档 HTTP 200，发布使用前仍需核对 Riot 数据与资产政策，本轮未认定商用权限。

## NGRID 和地图

[转换器](https://github.com/FrankTheBoxMonster/LoL-NGRID-converter)提交 `92943ed2b2d5e82c86d680e69f53f247c89aefee`，时间 2023-11-21T11:04:57Z，未归档。已读 Program.cs、NGridFileReader.cs 等。输入 `.aimesh_ngrid`，可选 `.ngrid_overlay` 必须配基础网格。代码支持 major 2/3/5/7，读取 minBounds/maxBounds、cellSize、cellCountX/Z、flags 与 height samples，输出 BMP 图层及 LSGNGRID 中间格式。

README 的历史地图尺度仅作线索，未当成当前补丁参数。overlay 版本检查使用 `&&`，不能据此认定严格兼容。未取得目标补丁网格/overlay，未验证动态障碍与真实路线；模块状态 `needs_local_file_or_versioned_asset`。AGPL-3.0 许可原文已保存，未集成或执行。

[CDragon 16.20 map11 目录](https://raw.communitydragon.org/16.20/game/data/maps/shipping/map11/) 与 latest 目录实际 HTTP 200，列出 map11.bin（4.4 MiB）、map11.bin.json（9.2 MiB），该目录未列出 NGRID；不等于全站没有网格。JSON 超过本轮 8 MB 限制，不下载、不声称核验内部字段，也不当成导航网格。目录补丁与目标客户端匹配尚未核验。页脚指向 Riot Legal Jibber Jabber，仅为许可线索。

## Meraki 机制资料

[Ivern JSON](https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions/Ivern.json) 实际下载并解析，包含 stats、abilities.P/Q/W/E/R、effects、cooldown、notes、targetRange。四个基础值与官方一致，未覆盖官方数据。没有顶层 version/patch；releasePatch=6.20、patchLastChanged=25.08。最后变化补丁不能证明全数据集版本，latest 不作为版本证据。技能数值、队友与对手交互均未审核。

[生成项目](https://github.com/meraki-analytics/lolstaticdata)提交 `df17d37deb861b8555e917593d5ba1e71de2603c`，时间 2025-11-12T05:03:52Z，未归档；README 指向 Wiki 上游，并说明复杂交互需逐例处理。源码 MIT 许可已保存，数据上游许可另待核验，仅读取并缓存单英雄。

## 刷野实测

[帖子](https://www.reddit.com/r/Jungle_Mains/comments/1ac12do/a_spreadsheet_for_optimal_jungle_clears_in_s14/) 作者 23NK1H / Zen'Kih，指向 [公开表格](https://docs.google.com/spreadsheets/d/1jE8bnlnIJnmWv9pnVW9veMKRXJNaaJf5tneQB3xUkbI/edit)。表格 HTML 本轮可读，标题现为 Jungle Clear Compilation S16/2026，不能仍用 S14 帖名作为其版本。

实际可见列 Champion/Patch/Camps/Smite(s)/Time/Path/Link/Player/Note；有行级补丁如 26.02，未自动映射到 DDragon 16.20.1。页面已保存，未提取成行动样本，未观看或下载视频。计时起止、等级、装备、加点、操作及结束状态仍待逐条核验，未取得批量复用许可。空模板已包含这些条件、阵容与误差。模块状态 `measurement_conditions_and_permission_unverified`。

## ROFL 及其他

[Mowokuma/ROFL](https://github.com/Mowokuma/ROFL)提交 `7181c9a745881cad9e14b79653c48af0d2fcd824`，时间 2025-02-27T15:11:03Z；GitHub API archived=true，pushed_at=2025-03-06T19:44:03Z。README 声称秒级位置及眼位输出，本轮未实测。LICENSE 请求真实 404，树未检出许可证，不能默认可集成。

父目录已有历史 ROFL 实验脚本和结果，未重跑或据此认定有效。工作区文件清单未检出 `.rofl`、`.aimesh_ngrid`、`.ngrid_overlay`，没有搜索全磁盘游戏安装。模块状态 `needs_local_file_and_compatibility_review`，未解析真实回放。

17 个候选入口均实际 HTTP 200，但 JSON 可解析、字段正确、当前补丁匹配、允许复用分别核验。meta-api 与 live sample 仅验证 JSON 解析，官方示例不是本局数据。LOLPT 等页面未被认定为公开 API；没有请求需密钥接口或本地客户端，没有读取密钥或浏览器会话。
