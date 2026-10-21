# 当前状态

更新时间：2026-10-13。已增加泉水出生区域锚点核对；录屏改为可选补充，不再阻塞离线推进。第三轮已完成本地日志与受控回放的证据关联。首轮/第二轮记录分别保存在 STATUS_round1.md / STATUS_round2.md。

## 本轮完成

- 只读已有受控回放 HN1-11363093470.rofl、旧坐标报告和对应原始客户端日志。
- 日志第 4 行版本为 16.20.824.8524，第 36 行 GameID=11363093470，第 57 行 mapskin=Default。版本/皮肤与第二轮本地资产元数据匹配。仅保存字段白名单、行号、来源路径与哈希，没有复制完整连接参数。
- 回放 SHA256 与旧报告一致：f89bb444d046b7e6a9699e6dc83c06861d81e2a6d4c2b7585cc4e35cc9654238。日志 SHA256：bc6f4e3ab770290c6b8ca8800ea0e2ad65518f82c737faff6a90c9f60b5dd3f5。
- 原回放中存在相同版本字符串；GameID 与回放关联依赖原文件名，没有声称新增了 GameID 协议解码。
- 将旧报告的 9 条候选记录映射到保存的基础网格，保留包起点和计划路径点的区别，实际到达时间、行动耗时、实际可通行性均保持 null。
- 新增可重复运行的审计命令、15 项合成单元测试、观测模板和具体录像交接说明。未更改父目录旧协议实验、未运行下载的第三方脚本。

## 文件变更

新增：lol_coach/calibration.py；scripts/audit_calibration.py、run_calibration_audit.ps1；tests/test_calibration.py；docs/CALIBRATION_HANDOFF.md、calibration_observation_template.json；reports/calibration_audit.json、pytest-calibration.log、pytest-calibration.xml、STATUS_round2.md。

更新：README.md、reports/STATUS.md；重新执行真实离线 smoke 后更新 reports/map_smoke.json、real_sample_smoke.json。建立 data/private/calibration/ 供保存录像。

## 运行与真实结果

在 D:/1/yxlm/lol-coach 执行：

```powershell
& .\scripts\run_calibration_audit.ps1
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-calibration-approved --junitxml=reports/pytest-calibration.xml
.\.venv\Scripts\python.exe scripts\verify_real_map.py
.\.venv\Scripts\python.exe scripts\verify_real_sample.py
```

- 单元测试：51 passed in 0.98s（已有 36 项 + 新增 15 项；全部离线合成/模拟输入；无跳过）。测试记录见 pytest-calibration.log/xml。
- 真实日志/回放审计：脚本退出 0；9 条候选记录输出成功，结果为 needs_independent_visual_observations，decision_input_eligible=false。退出成功不表示坐标校准完成。
- 真实地图离线 smoke：15 份证据哈希、87320 个格坐标往返、8 份 overlay 再解析通过。
- 真实英雄离线 smoke：Ivern 16.20.1 原文哈希、版本列表、规范化重现、4 个基础字段和 5 段描述通过。
- 本轮未新增在线抓取、未运行游戏实测、未观察视频。首次普通沙箱执行因项目写权限失败，pytest 临时目录/报告写入也失败；经环境审批重跑后才取得上述成功结果。没有自动审批拒绝。

## 仍然缺什么

- 本局 Default 皮肤与安装 build 已有独立日志证据；地图 ID/模式没有由这些日志字段独立确认，不能把皮肤名称等同于完整运行时地图。
- 旧版坐标原点 (7358,7412) 和英雄身份来自先前报告，尚无画面对照。9 个候选起点在静态开放候选格中只是相容性，不是准确性的证明，其中部分带未知位 128。
- 活动 overlay、未知尾字节及叠加规则、单位半径、阵营门、动态障碍与实际碰撞仍未验证。不输出真实路径和行走耗时。
- 机制中的队友/对手交互、真人刷野条件和结束状态仍待独立证据。首轮资源入口已经核实，不能视为完成机制理解。
- 未做前端、微调或云模型点评。真实对局输入尚未开放给决策分析。

## 2026-10-13：按用户建议核对泉水锚点

新增 scripts/audit_spawn_anchor.py 和 reports/spawn_anchor_audit.json，已真实运行：

```powershell
.\.venv\Scripts\python.exe scripts\audit_spawn_anchor.py
```

配置原文 SHA256 检查通过。CLASSIC 与 PRACTICETOOL 均引用 locator 对象 {a250382e} 和 respawn 对象 {5ec67f3f}。OrderSpawnGate 的 X/Z 为 (409.663,422.251)，ChaosSpawnGate 为 (14298.130,14383.980)。回放首个候选位置 (604,612) 距两者分别约 271.61 和 19421.55 游戏单位，与 Order 泉水附近出生的解释相容。

这是地图配置地标与回放候选坐标的独立来源对照，可用于初始区域定位；没有把坐标强制拟合到出生门。出生门不是英雄精确出生点，配置另有 Team 100/200 的 FirstSpawnPositionOffset (160,0,120)/(-160,0,-120)，其基准点与应用规则尚未确认，不能简单加到门坐标上冒充验证。

本轮执行的是实际缓存数据审计（退出 0），未新增或重跑 pytest；最近单元测试结果仍为上轮 51 项通过。没有新增游戏观察。

## 当前下一步

无需用户立即重开旧回放或录屏。优先继续查找首次出生基准点/槽位，结合已有跨局出生记录与固定地标交叉验证坐标原点；暂以泉水区域作初始位置锚点。尺度/轴方向、墙边碰撞和动态地形分别保留验证状态，不把局部不确定性当作所有基础工作的阻塞。录像说明保留为以后可用时的补充方案。
