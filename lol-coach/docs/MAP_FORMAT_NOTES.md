# 地图格式与验证边界

本轮只读提取本地安装资产，代码写在 lol_coach/wad.py、ngrid.py、map_pipeline.py。未执行或复制第三方转换器，未修改游戏安装，未启动游戏进程。第三方源代码作为格式参考，下载原文、固定提交与许可均保存在 reports/map_source_evidence.json / entry_evidence.json 所指证据中。

## 格式参考

- [CDTB wad.py](https://github.com/CommunityDragon/CDTB/blob/005134d274fe1a15e1dc9a7e6c62879c2b67679a/cdtb/wad.py)，LGPL-3.0：WAD 3.4 的 272 字节头、32 字节索引项、压缩方式与校验字段参考。
- [NGRID converter](https://github.com/FrankTheBoxMonster/LoL-NGRID-converter/tree/92943ed2b2d5e82c86d680e69f53f247c89aefee/LoLNGRIDConverter/LoLNGRIDConverter)，AGPL-3.0：NGridFileReader.cs / NavGridCell.cs 的 NGRID 7 格式与历史 flags 解释。代码中的 hint 矩阵含义存在不确定性，本项目保留其原始位置及长度，不解释为路径。
- [LeagueToolkit overlay reader](https://github.com/LeagueToolkit/LeagueToolkit/blob/76bf57bf4fd195343dec610bf0f912a06b910914/src/LeagueToolkit/Core/Legacy/IO/NavigationGridOverlay/NavigationGridOverlay.cs) 及 NavigationGridOverlayRegion.cs，仓库 LICENSE 已保存：overlay 的版本后接区域数量，再逐个读取矩形区域。

依赖 xxhash 3.6.0、zstandard 0.25.0 只安装在项目虚拟环境。原始游戏资产归 Riot，公开读取/本机可读不等于可分发；本轮资产只留在 data/private/，未上传。软件许可和游戏资产使用条件是不同事项。

## 本轮支持的格式

WAD：仅 3.4、storage type 0（原文）/3（Zstandard），其他类型明确失败。先检查索引边界、输入大小和 XXH3 压缩条目校验和，再核对 Zstandard 帧声明大小、解压长度及 SHA256。不是完整 WAD 解包器。

NGRID：仅 7.1。头包含 xyz 最小/最大边界、格子边长及 X/Z 维数；随后是每格 48 字节记录、uint16 flags、每格 4 字节区域属性、1056 字节未知块、高度采样及 3243600 字节 hint 区。本轮解析 flags 与高度范围；区域属性、未知块与 hint 区仍保留在原始文件，未实现全部语义。严格检查总长度与全部格子的 (x,z) 顺序，不对未知版本猜偏移。

坐标查询采用头部推导：floor((world_x-min_x)/cell_size)、floor((world_z-min_z)/cell_size)。边界按 [min,max) 接受；最末格可能只覆盖部分声明范围。这是内部可复现映射，尚无游戏内采样校准，不能把往返检查称为真实移动验证。Y 作为高度轴、X/Z 作为水平轴来自社区格式说明及文件结构。

flags 中 0/1/2/4/64/1024/2048 等解释来自社区资料，128 含义未知且保留。查询只返回 static_open_candidate、static_blocked_candidate、team_restricted 或 unknown_flags；actual_passability 总是 null。尚未考虑单位碰撞半径、阵营门、动态障碍、位移技能与实际 overlay 组合。

## Overlay 差异

本地 8 份 overlay 都是首字节 version=1，第二字节分别为 1、2、3、6、7、11 等区域数量。按区域数量逐块解析后，每份还剩 1 字节（00 或 01），当前含义未知。海洋 overlay 有重叠矩形，保留写入次序和重叠计数。

旧 NGRID converter 将第二字节当 minor version，并只读取一个矩形；不能直接拿它处理本次多个区域的文件。LeagueToolkit 参考支持多个区域，但也未解释这里的尾字节。本项目准确保留 regions、原始 flags、尾字节，不套用旧单区域覆盖规则，不生成合并后的“当前地图”。

## 版本与选图

读取 code-metadata.json / content-metadata.json，要求其补丁与参数相符、构建号一致。本轮均为 16.20.8248524；另只读查看 exe 文件版本为 16.20.824.8524。本地 map11.bin 与公开 CommunityDragon 16.20 同名 BIN 的 SHA256 相同，再借助该版本 JSON 的 MapSkin.mNavigationMesh 定位 WAD 项。

当前显式选择 MapSkins/Default，读取 AIPath_SRX_2.aimesh_ngrid。证明的是该安装版本携带并由这个配置对象引用的真实资产；本局实际地图皮肤/模式仍未知，mode=null。安装包可能同时保留历史或其他模式资产，不能凭安装版本推断每场比赛使用这一份网格。需要后续用目标回放/受控场景核对选图和通行性。
