# 当前状态

更新时间：2026-10-11。第二轮完成真实地图资产提取和结构核验。第一轮原始状态保留在 reports/STATUS_round1.md；历史“未取得本地网格”的缺口已更新。

## 本轮实际完成

- 从父目录既有脚本发现本机游戏安装路径，只读确认 exe 版本 16.20.824.8524，code/content 元数据均为 16.20.8248524。
- 只读 Map11.wad.client（2.53 GB），解析 28463 条索引；定向提取配置、Default 皮肤引用的 NGRID 和 8 份 overlay。没有修改安装、启动/注入游戏进程或上传资产。
- 本地 map11.bin 与公开 CommunityDragon 16.20 BIN 的 SHA256 一致；以相应 JSON 的 MapSkin.mNavigationMesh 字段定位网格。JSON 大小约 9.2 MiB，本轮明确将地图配置请求上限设为 16 MB，其余探测默认仍为 8 MB。
- NGRID 7.1，295×296、87320 格，边长 50 游戏单位；逐格坐标顺序、文件布局、flags、高度采样尺寸核验通过，生成 grid.json 和真实逐格 PNG。
- 8 份 overlay 按多个区域解析，原文与未知尾字节保留，尚未应用 overlay。
- 新增 extract-map 和 query-map；坐标查询返回静态候选分类，actual_passability=null。

证据证明的是该安装中 Default 配置引用的真实资产。本局活动地图皮肤、模式和 overlay 组合未验证，manifest.mode=null；不能认定所有 16.20 对局使用这份基础图。

## 文件变更

新增：lol_coach/wad.py、ngrid.py、map_pipeline.py；requirements-map.txt；tests/test_map.py；scripts/map_sources.py、verify_real_map.py；docs/MAP_FORMAT_NOTES.md；reports/map_source_evidence.json、map_validation.md、map_smoke.json、pytest-map.log、pytest-map.xml、STATUS_round1.md。

修改：lol_coach/__main__.py（地图命令）、http.py（请求大小可配置）、pyproject.toml（地图可选依赖）、README.md、.gitignore、当前 STATUS.md。

本地数据：data/private/map-assets/；data/maps/16.20/Default/manifest.json、grid.json、base_flags.png；HTTP 原文和尝试记录。游戏资产及派生地图已加入 Git 忽略，父目录旧 ROFL 实验未修改。

## 实际运行命令

工作目录 D:\1\yxlm\lol-coach，项目 Python 3.13.7。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-map.txt
.\.venv\Scripts\python.exe scripts\map_sources.py
.\.venv\Scripts\python.exe -m lol_coach --offline extract-map --game-dir 'D:\WeGameApps\英雄联盟\Game' --patch 16.20 --skin Default
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --x 7500 --z 7500
.\.venv\Scripts\python.exe scripts\verify_real_map.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-map1 --junitxml=reports\pytest-map.xml
```

公开 16.20 配置先由 EvidenceClient 实际联网取得，再执行离线提取。新环境可去掉 --offline，由 extract-map 获取公开配置。本轮没有在线 pytest 套件。

## 测试与证据

**36 项离线单元测试通过（1.00s）**：原有 12 项、新增 24 项，零失败/跳过。合成输入只验证解析、边界、错误处理，不作为真实地图证明。

**真实地图离线 smoke 通过**：15 份证据 SHA256、公开与本地配置二进制相等、87320 格坐标往返和 flags 一致、8 份 overlay 再解析。已打开 base_flags.png 检查渲染。这些不等于实局行走验证。

WAD SHA256：947a27f421187eade8ed5c70499c57673835d769763df50970ff13781400cac7。
基础网格 SHA256：b7551b91dcdc3dec0228ff2df63483399b0b040552d2115b65d9fe1faf35bd93。
完整来源、真实字段和限制见 reports/map_validation.md、docs/MAP_FORMAT_NOTES.md。

## 受阻或未核验

- 初次证据写入遇目录权限错误，随后经环境审批完成；状态文件的普通沙箱更新也受权限限制，改用已审批的项目内写入。没有自动审批拒绝。一次公开哈希表 HEAD 返回 403，GitHub 候选路径返回 404；通过本地配置定位文件，没有绕过权限。
- WAD 只支持本轮的 3.4 原文/Zstandard 条目；NGRID 只支持 7.1，其他格式明确失败。
- overlay 尾字节（00/01）含义未知，多区域存在重叠，实际叠加规则与运行时选择未核验。
- 坐标变换由文件头推导；墙、草、阵营门 flags 含义来自社区，未做实局坐标和碰撞校准，位 128 保留未知。
- 未实现单位碰撞半径、动态墙、位移机制或实际路线耗时。
- 第一轮 Ivern 16.20.1 数据仍可用；复杂机制、队友/对手关系、真人刷野计时与结束状态待核验。未添加前端、微调或云模型调用。
- 资产使用/分发权限未确定；只保存本地证据。

## 下一项最小任务

确认目标对局实际地图皮肤/模式与 overlay 组合；选取有实际坐标的开放地面、墙边、基地门样本，校准坐标映射及 flags；查明 overlay 尾字节。完成后再增加带阵营、单位半径与地形状态条件的通行查询及最小路径验证。当前不能输出真实路径耗时。
