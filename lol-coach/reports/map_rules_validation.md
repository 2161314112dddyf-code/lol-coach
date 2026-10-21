# 导航选用规则核验（2026-10-13）

## 已取得的规则依据

[LoL Meta Wiki 的 MapSkin 说明](https://meta-api.leaguetoolkit.dev/v1/docs/MapSkin)将 mNavigationMesh 描述为旧入口，导航网格由 MapContainer 的 MapNavGrid 组件提供。本项目据此默认查询容器引用的 SRX_3，并保留 --grid-source skin 查询 SRX_2。

这是社区说明支持的分析选择，不是该局实际加载文件的观测。文档同时说两个字段引用同一个文件，但本地匹配版本的实际资产不符合这一概括；这项差异仍保留在结果里，不能把文档整段无条件当作已验证事实。

文档来源：LoL Meta Wiki，https://meta-wiki.leaguetoolkit.dev 。本段是上述资料的中文概述，按 CC BY-SA 4.0 标注；原文提供 League Toolkit Developer Tooling Exception，[许可说明](https://meta-wiki.leaguetoolkit.dev/api/licensing/)。这里只缓存原文、附上来源并用于工具验证，没有改动项目代码整体许可。游戏资产权利状态不因文档许可改变。

文档原文 SHA256 为 8b5e925982ffa1e0dabf71f9b9057ec33a3e81dd2aa6972f8dc3628c37fb046a。代码固定这份已检查的文本；若来源改变则要求重新审查，不自动把新文本当成相同规则。

API /v1 返回 dataset.latestPatch=16.20、latestBuild=8248524，与本地 code/content 元数据一致。该版本标签限定字段数据集；说明文字本身没有独立声明经过本机腾讯客户端运行时验证。元数据响应与文档原文均有哈希和获取时间，见 map_rules_audit.json。

## 出生规则调查结果

RespawnPointData 字段数据中包括 FirstSpawnPositionOffset、AlwaysRespawnWithOffset、Team、TeamDefinition，但类型和默认值不能证明坐标应用规则。MapNavGrid 和 RespawnPointData 的具体说明端点本次均返回 404，已记录，没有捏造解释。

还从本地 WAD 提取了皮肤引用的 ASSETS/Maps/Deprecated/Map11/CFG/objectcfg_SRX.cfg，SHA256=ba7d8524fc5279d798c80496cb7bc693a4b6f6c81d5a27f375cf4221a3fa1f53。含 spawn 的节名指向兵营资源，未取得英雄首次出生槽位规则。保留原文为证据，不将配置内容执行为指令。

## 实现与实际验证

- 新增 map_selection.py，容器默认值须具备地图容器审计、匹配元数据版本及已检查说明原文；缺失时明确报错，不静默退回旧网格。
- query-map 新增 --grid-source container|skin，默认 container；返回资产路径、哈希、选择依据、未应用 overlay 和未观测运行时的状态。actual_passability 保持 null。
- 新增 audit_map_rules.py 和 verify_map_selection.py；前者持久化依据，后者检查真实原文和实际不同格的查询结果。
- 本轮 70 项离线 pytest 通过（0.94s，已有 61 + 新增 9，无跳过）。这些单元测试是合成输入，不作为真实游戏观察。
- 真实离线 smoke 通过：在 X/Z=(3373.895103,1407.755798)、cell=(67,27) 处，默认 SRX_3 flags=70，而显式 SRX_2 flags=0；证据原文、元数据和资产哈希通过核验，运行时/碰撞状态仍未升级。

## 复现

```powershell
.\.venv\Scripts\python.exe scripts\audit_map_context.py --offline
.\.venv\Scripts\python.exe scripts\audit_map_rules.py --offline
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --x 3373.895103 --z 1407.755798
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --grid-source skin --x 3373.895103 --z 1407.755798
.\.venv\Scripts\python.exe scripts\verify_map_selection.py
```

这些命令需已有该局本地资产/回放及缓存；缺少 HTTP 缓存可去掉两个审计脚本的 --offline。重新 extract-map 会重建 manifest，之后应重新执行 context 和 rules 两步审计。
