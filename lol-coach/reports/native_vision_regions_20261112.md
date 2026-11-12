# 眼、塔与地面视野的原包对照

国服 16.22.836.1077 的实时包 `0x369` 在插眼时携带阵营和世界坐标。与独立解码的眼对象、施法者和 `0x482` 位置比较，十人局 115 枚眼均能在放置当刻找到相应区域中心。109 个中心与眼对象的第一条位置完全相同，其余 6 个相差 20.40–125.54 个地图单位。保留两组坐标及各自原包偏移。一枚远见眼同刻有两份同中心注册，保留双方记录。

| 潘森训练局游戏时钟 | 眼 | 0x369 的 X、Z | 与 0x482 位置距离 |
|---|---|---|---|
| 02:23.068 | 黄色饰品眼 | 2104，8310 | 0 |
| 03:19.842 | 控制守卫 | 12526，6460 | 0 |
| 03:42.856 | 控制守卫 | 9926，4580 | 0 |
| 05:21.753 | 黄色饰品眼 | 12390，6432 | 0 |

在已对齐的布局中，字节 10 上的 `71` 对应蓝方，`77` 对应红方。两个坐标各占四个字节，依次为大端浮点 Z 和 X，使用相同的逐字节置换。置换来自 22 个开局常规防御塔的独立地图坐标与本版本客户端的静态表。源程序 SHA-256 为 `0a3db62e27bb20e88b9fa1111edc5bd9f80f6d1969b70d7fa3739b9ce3c0691d`，文件偏移 `0x98d0e0` 起 256 字节为置换表 S。每个原包字节 w 的明文为 `S⁻¹(ROL8(w XOR 0x7d, 2) XOR 0xdb)`。训练局与十人局均有 22/22 个塔中心符合地图地标，最大距离约 1.42 单位。拉克丝局缺一份用来对应名称的塔记录，其区域中心在另两局有一致地标。

在十人局 107 枚有移除时刻的眼中，每次移除都能在同一游戏时刻找到 `0x57`。整局此类包共 969 条，单个放眼对象的移除时刻有时存在三个候选。区域半径、授予／撤销普通视野、移动区域的持续跟踪均缺少独立字段验证。分析输入保留原包中的区域中心与阵营，覆盖范围继续依赖具体眼的机制、地形、是否被压制及特殊眼位。远见眼有穿墙和扩张机制，仙灵之光另有随地点变化的额外视野形状。[Riot 远见改造说明](https://www.leagueoflegends.com/en-ph/news/game-updates/patch-13-10-notes/) · [Riot 仙灵之光规则](https://www.leagueoflegends.com/en-us/news/game-updates/patch-26-1-notes/)

对完整地面图还检验了一种封装假设。根据 Riot 历史渲染资料所述 128×128 格，枚举潘森全部关键帧中可放入 2,048 字节的一体位平面。四个有原录像时钟对应的关键帧逐点对照蓝方 HUD 的可读地面格；每帧约有 680–930 个可见格、2,500–3,150 个雾中格。允许任意包内位起点、八种空间朝向、两种位序和极性，另检查延迟 60 秒的对照帧。最佳平衡准确率低于 55%。允许任意固定字节替换时，对齐字节中八格同色的样本最乐观上界为 77%。这限定了上述对齐方式；跨包、分块、增量或其他大小的表达仍有可能。合成旋转及置换正例在相同程序中均达 100%。[Riot 渲染原理](https://www.riotgames.com/en/news/story-fog-and-war)

## 单独移动这个区域会怎样

对第一枚黄眼，实时包和随后两次关键帧里的区域编号都是 `0x394`。该编号可从第 11 字节起，逆变换再读变长整数得到。三条记录的中心都是 [2104, 8310]。十人局 115 枚眼均有可识别的区域编号。它与对象的网络编号分别保存，能关联同一区域的后续快照。

另生成两份本地实验副本。一份只重新压缩相同的三个数据块，逐包对比结果完全一致。另一份仅将这三条记录中对应位置改成 [6280, 9860]，原件、签名和结算元数据均保留。新位置在两套地图网格中都属于空地。原件在 211 和 212 秒，经同版本引擎渲染后，该点周围 17×17 个像素全部受雾变暗，两次相对亮度均约 0.463。

官方客户端对两份派生回放均报告 `bad signature / Failed to read replay file`，两组都没有进入游戏。这个实验只能确认原件的暗处和改动确实隔离到了指定字段。单独移动原包中的区域能否改变引擎迷雾仍待实证。[逐包差异](../data/private/vision_queries_20261112/intervention_pan_369/receipt.json) · [原件像素结果](../data/private/vision_queries_20261112/intervention_pan_369/native-original/center-controls.json) · [重压对照拒绝记录](../data/private/vision_queries_20261112/intervention_pan_369/native-proof-repacked_control/rejection.json) · [变更组拒绝记录](../data/private/vision_queries_20261112/intervention_pan_369/native-proof-shifted_region/rejection.json)

## 复跑

在 `lol-coach` 下运行，私有 ROFL、玩家视频与身份绑定的 HUD 校准文件留在本机。

```powershell
$py = '.\.venv\Scripts\python.exe'
$replays = "$env:USERPROFILE/Documents/League of Legends/Replays"
& $py scripts/check_spatial_wards.py "$replays/HN1-11461276459.rofl"
& $py scripts/check_spatial_wards.py "$replays/HN1-11461236084.rofl"
& $py scripts/research_region_intervention.py "$replays/HN1-11461236084.rofl" data/private/new_region_intervention
& $py scripts/research_fog_bitmap.py "$replays/HN1-11461236084.rofl" --profile data/private/vision_queries_20261112/geometry/minimap_profile.json --video "$env:USERPROFILE/Videos/Captures/League of Legends (TM) Client 2026-11-12 13-00-49.mp4"
& $py -m pytest -q tests/test_vision_regions_1622.py
```
