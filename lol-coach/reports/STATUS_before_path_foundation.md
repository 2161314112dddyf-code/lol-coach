# 当前状态

更新时间：2026-10-13。本轮找到导航选用的社区文档依据，默认查询已切换到 MapContainer 引用的 SRX_3；明确区分文档依据与本局运行时观测。无需用户立即录屏。

## 本轮实际完成

- 读取 LoL Meta Wiki 公开 API 元数据、MapSkin/MapNavGrid/RespawnPointData/RespawnPointDataList 字段和说明。数据集为 16.20/build 8248524，与本地资产匹配。
- MapSkin 说明将 mNavigationMesh 标为旧字段，指向 MapContainer 的 MapNavGrid 作为导航来源。据此建立可追溯的分析选择；来源文字的“两个路径相同”概括与本地资产不符，仍记录差异，未声称运行时已验证。
- 默认 query-map 选容器 SRX_3；--grid-source skin 可显式查询旧 SRX_2。缺少已审计规则会失败，不静默退回旧网格。文档哈希变化需重新审查。
- 读取本地 objectcfg_SRX.cfg 和出生字段定义，未得到英雄精确出生槽位规则。两份出生类说明端点中的 RespawnPointData 及导航类 MapNavGrid 说明均为 404，未捏造规则。
- 新增真实差异格 smoke，验证默认和显式旧网格确实返回不同 flags。

## 文件变更

新增 lol_coach/map_selection.py、scripts/audit_map_rules.py、scripts/verify_map_selection.py、tests/test_map_selection.py；reports/map_rule_meta_evidence.json、map_rule_docs_evidence.json、map_rules_audit.json、map_rules_validation.md、map_selection_smoke.json、pytest-selection.log/xml、STATUS_before_selection.md。

修改 lol_coach/__main__.py、README.md、reports/STATUS.md；更新 data/maps/16.20/Default/manifest.json 的 navigation_selection_policy，保存对象配置原文及 HTTP 证据。父目录回放实验未修改。

## 实际运行结果

70 项离线测试通过（0.94s，已有 61 + 新增 9，无失败/跳过）。真实离线查询 smoke 通过：cell=(67,27)，默认 SRX_3 flags=70，显式 SRX_2 flags=0；说明原文、元数据、容器资产哈希均核对。运行时文件选择、实际碰撞与 overlay 仍未验证。

在 D:/1/yxlm/lol-coach 执行：

```powershell
.\.venv\Scripts\python.exe scripts\audit_map_rules.py --offline
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --x 604 --z 612
.\.venv\Scripts\python.exe -m lol_coach query-map --patch 16.20 --grid-source skin --x 604 --z 612
.\.venv\Scripts\python.exe scripts\verify_map_selection.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-selection --junitxml=reports/pytest-selection.xml
```

首次建立地图资产或重新 extract-map 后，需要先执行 audit_map_context.py --offline，再 audit_map_rules.py --offline。去掉 --offline 可取得缺失的公开缓存，但说明原文改变不会自动接受。

本轮公开 API 请求实际成功，两个具体说明 404 已保留；部分 web 页面工具读取失败但项目 HTTP 客户端取得了 JSON。项目写入经环境审批，无审批拒绝。没有新游戏实测或录像观察。

## 仍有的缺口与下一步

- 导航默认选择有社区说明支持，本局实际加载与服务器导航仍无直接观测；不赋值 runtime_selected_path，不输出实际通行。
- 活动 overlay 的选择/合成、尾字节、单位半径和动态地形仍未知。出生槽位、坐标精确取整规则亦未解决，泉水区域锚点可继续使用。
- 下一步可在明确选定的基础网格上核对已有路径片段与固定地标，输出相容/冲突证据；遇到冲突不能自动判断解码错误或行走违规。并行方向仍包括英雄机制的队友/对手交互与真人刷野条件/结束状态，本轮未新增相关证据。
- 不做前端、微调或无来源复盘结论，录屏保持可选。

详细依据、许可归属和结果见 reports/map_rules_validation.md；上一轮记录见 STATUS_before_selection.md。
