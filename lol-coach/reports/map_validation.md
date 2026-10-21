# 第二轮真实地图核验

日期：2026-10-11。结果：已完成一份本地 16.20 安装中的 Default 地图网格提取、结构解析与证据闭环；实际对局通行性仍未校准。

## 已取得的数据

本机 Game/code-metadata.json 与 content-metadata.json 的版本构建号均为 `16.20.8248524`，分别带 code.publictencent / content.release 分支标记。只读查看 League of Legends.exe 文件版本为 `16.20.824.8524`。

来源：`D:\WeGameApps\英雄联盟\Game\DATA\FINAL\Maps\Shipping\Map11.wad.client`。WAD 3.4，2,528,886,306 字节，28,463 个索引条目；仅定向解压地图配置、一份网格和 8 份 overlay。为留存归档身份，顺序读取全文件计算 SHA256，没有整包复制或解压。

WAD SHA256：`947a27f421187eade8ed5c70499c57673835d769763df50970ff13781400cac7`。

本地 `data/maps/shipping/map11/map11.bin` 与 [公开 16.20 BIN](https://raw.communitydragon.org/16.20/game/data/maps/shipping/map11/map11.bin) 的 SHA256 一致：`5e9da133837575674effc29b58b69920f801db9c7e4f7d2bab09326e64d4f694`。随后从 [同版本 JSON](https://raw.communitydragon.org/16.20/game/data/maps/shipping/map11/map11.bin.json) 的 `Maps/Shipping/Map11/MapSkins/Default.mNavigationMesh` 获取路径，并确认该路径实际存在于本地 BIN 和 WAD 索引。

网格路径：`ASSETS/Maps/NavGrid/Map11/AIPath_SRX_2.aimesh_ngrid`。WAD 路径哈希 `e08d20957d2e2a3a`，压缩偏移 773137394，压缩长度 1954053，原始长度 9361843，压缩块 XXH3 校验通过。

网格 SHA256：`b7551b91dcdc3dec0228ff2df63483399b0b040552d2115b65d9fe1faf35bd93`。

这证明安装资产、补丁元数据和指定配置引用之间可回溯。安装包含多种皮肤/模式资产，本轮没有验证本局实际选择；不能把 Default 自动当作所有 16.20 对局的活动地图。

## 结构结果

| 字段 | 真实解析值 |
|---|---|
| NGRID 格式 | 7.1 |
| 网格维数 | X=295，Z=296 |
| 格子数 | 87320 |
| 格子边长 | 50 游戏单位 |
| 最小 XYZ | (-1.1048965, -71.2406006, 32.7557983) |
| 最大 XYZ | (14718.4003906, 184.5200958, 14792.2109375) |
| 高度采样 | 591 × 593 |
| 高度样本范围 | -150.3501282 至 186.8871002 |
| 静态开放候选 | 53724 格 |
| 静态阻挡候选 | 33460 格 |
| 阵营限制候选 | 136 格 |

全部格子原始 x/z 与 `index=z*width+x` 一致；头部尺寸与边界/格长一致，长度校验完全匹配已支持的 7.1 布局。1056 字节未知区与 hint 区保存位置和长度，未猜测其语义。

预览：`data/maps/16.20/Default/base_flags.png`，真实逐格渲染，+Z 向上。深灰为阻挡候选、浅色为开放候选、绿色为草丛候选、蓝色为阵营限制；未应用 overlay，未平滑或补画。已实际打开图像核查渲染。

## Overlay

| 名称 | 区域数 | 未知尾字节 |
|---|---:|---|
| AtakhanBot | 3 | 00 |
| AtakhanTop | 3 | 00 |
| Chemtech | 1 | 00 |
| Cup_Base | 2 | 00 |
| Infernal_SEASONAL | 2 | 00 |
| Mountain_SEASONAL | 6 | 01 |
| Ocean_SEASONAL | 11 | 01 |
| Tunnel_Base | 7 | 01 |

8 份资源均实际提取并检查压缩块/原文哈希。矩形区域边界和长度校验通过；重叠区保留次序。第二字节是区域数量，与旧转换器的单矩形/minor-version 假设不同。末尾一字节含义不明，暂不应用 overlay，也没有认定这些候选在指定对局中全部启用。

## 真实执行的检查

- pytest：**36 passed in 1.00s**，零失败/跳过。其中原有 12 项，新增 24 项；合成 fixture 覆盖 WAD 原文/Zstandard、校验和、索引越界、未支持压缩、NGRID 版本/长度/坐标/非有限值、边界查询、多区域 overlay、重叠区/未知尾字节、HTTP 限额。
- `scripts/verify_real_map.py`：**passed**。离线核对 15 份真实证据哈希、公开/本地 BIN 相等、规范化 flags 一致、87320 个格子的坐标往返、8 份 overlay 再解析。它不是实局移动或决策测试。
- CLI 查询 `(7500,7500)`：格子 `(150,149)`，flags=0，category=static_open_candidate，actual_passability=null。测试坐标是人工选定输入，不是玩家观测位置。
- 基础图已实际查看。没有运行游戏、回放、寻路或时间估计。

日志：`reports/pytest-map.log`、`pytest-map.xml`、`map_smoke.json`。完整数据来源和限制：`data/maps/16.20/Default/manifest.json`；原始私有资产：`data/private/map-assets/`；HTTP 原文：`data/raw/`。

## 失败及限制

初次普通沙箱网络证据落盘遇 PermissionError，随后经环境审批写入项目，成功。公开 hashes.game.txt 的 HEAD 探测返回 403，GitHub 候选文件路径返回 404；未绕过权限。改用本地配置中已有资产路径做 WAD 路径哈希查找，无需下载完整哈希库。404 与后续成功请求记录可在 map_source_evidence.json / data/attempts 中查到；HEAD 403 来自终端探测。

提取实现仅支持 WAD 3.4 的原文/Zstandard 条目与 NGRID 7.1；未支持的布局明确失败。社区 flags 含义、128 位意义、overlay 尾字节/叠加顺序、实际地图皮肤、客户端世界坐标、单位半径、动态障碍及阵营门均未完成实局校准。Riot 资产复用权限未判定，文件保留本地，未上传。

下一项应先核对目标对局的地图皮肤/模式及 overlay 选择，并用带实际坐标的少量开放地面、墙边、基地门样本校准空间映射。然后才适合增加带条件的通行判断和路径计算。
