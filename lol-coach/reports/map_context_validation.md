# 出生基准与导航引用核验（2026-10-13）

## 来源闭环

Default MapSkin 的 mMapContainerLink 指向 Maps/MapGeometry/Map11/Base_SRX。实际资源文件是 data/maps/mapgeometry/map11/base_srx.materials.bin，而非先前尝试的 base_srx.bin。

已取得[版本化几何配置](https://raw.communitydragon.org/16.20/game/data/maps/mapgeometry/map11/base_srx.materials.bin.json)，其对应的公开 BIN 与本地 WAD 提取 BIN 的 SHA256 完全一致：34295c111bae96d7543a60bea9ac5398d6a468ec7b24e1f1435b0723ddf7f1b9。读取前核对目录大小：BIN 1.7 MiB、JSON 3.5 MiB，使用既有 8 MB 请求上限。原文、抓取时间与缓存证据保留在 map_context_audit.json.geometry_evidence。

网页工具访问目录失败；项目 HTTP 工具实际返回成功并保存响应。候选 maps/mapgeometry/map11/ 返回 404，沿 data/maps/ 真实目录找到 materials 文件，没有绕过访问限制。目录探测另存 spawn_*directories.json 与 spawn_directory_evidence.json。

## 出生坐标

只遍历容器明确引用的 chunks，找到对象 {183e98d5} 中的两个 GdsMapObject（type=1），均为无旋转的平移矩阵：

|对象|X|Y（高度）|Z|
|---|---:|---:|---:|
|__Spawn_T1|394|171|461|
|__Spawn_T2|14340|179|14391|

三份原始回放哈希均与既有 movement 报告一致，版本均记录为 16.20.824.8524。以 stream=1、0≤time<1、flags=3、extra_byte=1 筛选首次出生候选：

|回放|候选数|候选 X/Z|
|---|---:|---|
|HN1-11363048522|2|(604,612)、(14102,14194)|
|HN1-11363093470|1|(604,612)|
|HN1-11360086609|0|不满足筛选条件，不强行把最早位置叫作出生点|

两份受控回放同侧值重复；另一侧位置与对侧泉水区域相容。它们使用同一旧解码器和原点，因此重复性不能算独立的坐标真值证明，实体阵营也没有由此解码。

检验“出生基准直接加 FirstSpawnPositionOffset”这一假设：T1 得到 (554,581)，距候选差 (50,31)，约 58.83 单位；T2 得到 (14180,14271)，距候选差 (-78,-77)，约 109.60 单位。假设不能精确复现这两个候选，尚不能确认出生槽位/放置规则；不调整原点来消除差异。

两份网格头部坐标框相同，中心为 (7358.647747,7412.483368)。旧解码原点 (7358,7412) 与中心分别差约 0.648、0.483 单位。这是来自地图资产的额外相容性证据，协议是否取整及其具体规则仍未验证。

## 导航引用冲突

MapSkin.mNavigationMesh 指向 AIPath_SRX_2，MapContainer.components 的 MapNavGrid.NavGridPath 指向 AIPath_SRX_3。两份真实文件都存在于本地 WAD，且成功通过校验和、NGRID 7.1 结构及逐格顺序检查。

|资产|SHA256|阻挡候选格|开放候选格|阵营限制格|
|---|---|---:|---:|---:|
|SRX_2|b7551b91dcdc3dec0228ff2df63483399b0b040552d2115b65d9fe1faf35bd93|33460|53724|136|
|SRX_3|28f6738003e01a0c13fa8a2f859d2947a8743606465b42139a24c423dd311bd9|32495|54689|136|

两者共 87320 格，其中 4210 格的原始 flags 不同。保留原有 SRX_2，不擅自决定哪一个引用优先；SRX_3 原文与 container_flags.png 单独保存。已查看真实逐格预览。query-map 增加 queried_asset_path、navigation_reference_status、container_asset_path 和 runtime_selected_path；本次后者仍为 null。

## 实际验证

在项目目录执行 scripts/audit_map_context.py --offline：成功，核对公开/本地几何 BIN、缓存 JSON 哈希、三个回放哈希，提取另一份真实网格并比较全部 flags。

61 项 pytest 离线测试通过（1.03s，零跳过），其中新增 10 项涵盖显式链接地标、缺失/重复对象、非有限坐标、未支持的父变换/旋转、导航引用冲突、出生偏移不自动升级为精确校准。

verify_real_map.py 再运行通过：原有 15 份证据、87320 格往返、8 份 overlay 未受影响。query-map 实际执行并显示 conflicting_navigation_references。

当前无需用户重开回放。后续优先查容器/皮肤导航引用的实际选用规则、出生槽位和更多固定地标；泉水区域锚点已足够支持继续离线核验，仍不输出实际路径耗时或墙边碰撞结论。
