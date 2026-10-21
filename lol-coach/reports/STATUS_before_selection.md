# 当前状态

更新时间：2026-10-13。本轮完成出生基准与跨回放核验，并发现/显式标记两份导航引用冲突。无需用户立即录屏。

## 本轮实际完成

- 取得 Default 地图容器的 base_srx.materials.bin/JSON，本地/公开 BIN SHA256 完全相同；首次确切找到 __Spawn_T1=(394,171,461)、__Spawn_T2=(14340,179,14391)。字段来源、版本和对象引用可追溯。
- 核对三份原始回放哈希；两份受控回放重复出现 (604,612)，其中一份还有 (14102,14194)。第三份没有满足当前出生筛选条件的记录，未当作出生验证。
- 出生基准直接加配置偏移仍存在约 58.83/109.60 单位残差，因此没有声称精确出生槽位已解决。
- NGRID 包围盒中心与旧解码原点每轴相差不到 1 单位，增加原点假设的独立来源支持，取整规则仍未知。
- 地图皮肤引用 SRX_2，地图容器引用 SRX_3；两份真实网格有 4210 格 flags 不同。已提取 SRX_3，保存原文与逐格预览，不擅自覆盖或决定运行时优先级。
- query-map 显式显示导航引用冲突与所查询资产，runtime_selected_path/actual_passability 均保持 null。

## 文件变更

新增 lol_coach/geometry_context.py、scripts/audit_map_context.py、tests/test_geometry_context.py；reports/map_context_audit.json、map_context_validation.md、pytest-geometry.log/xml、STATUS_before_geometry.md；目录探测和几何来源 spawn_*evidence.json / spawn_*directories.json。

修改 lol_coach/__main__.py、README.md、reports/STATUS.md。更新本地 data/maps/16.20/Default/manifest.json 的 navigation_reference_audit，新增 container_flags.png，真实原文存 data/private/map-assets/。第二轮 SRX_2 保留。父目录已有回放解析产物未修改。

## 运行方法与真实结果

在 D:/1/yxlm/lol-coach：

```powershell
.\.venv\Scripts\python.exe scripts\audit_map_context.py --offline
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --x 604 --z 612
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-geometry --junitxml=reports/pytest-geometry.xml
.\.venv\Scripts\python.exe scripts\verify_real_map.py
```

61 项离线测试通过（1.03s，原有 51 + 新增 10，零跳过）。真实几何/回放审计成功执行，原有真实地图 smoke 再次通过。查看了新网格逐格 PNG。本轮没有游戏画面观察、实局行走或真人刷野计时。

公开几何资源已实际联网获取；--offline 复用原始抓取时间和校验过的缓存。网页工具目录访问失败，项目 HTTP 工具成功；候选路径有 404，均保留真实结果。写报告和测试使用环境审批，没有审批拒绝。

## 结论边界与下一步

泉水区域定位得到更直接的出生基准、双侧/跨局坐标和网格中心支持，足以继续离线工作；精确槽位/取整、比例与方向尚未全部独立验证。两份导航的运行时优先级、活动 overlay、碰撞半径与行动耗时仍未知。

下一步优先确认导航引用选用规则、出生放置/槽位规则，使用更多固定地标交叉检查。录屏是可选补充，不是前置阻塞。复杂英雄机制的队友/对手交互和真人刷野条件/结束状态仍需来源；不做前端、微调或无证据的 AI 复盘结论。

详细结果与来源见 reports/map_context_validation.md；历史 51 项测试/日志关联及泉水门对照见 STATUS_before_geometry.md，前两轮见 STATUS_round1.md / STATUS_round2.md。
