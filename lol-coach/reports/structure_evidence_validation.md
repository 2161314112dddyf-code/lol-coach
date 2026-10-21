# RPL-004C 结构对象证据，2026-10-19

目标版本 16.20.824.8524。本轮确切结果是保存并重放结构对象的原始状态与生命候选，**不是完成小兵、水晶和基地身份解码**。沿用现有四份回放，没有用户新增材料、网络获取、游戏启动或人工签署。恢复点 reports/special_object_baseline/manifest.json。

## 成果与验收

|验收|结论|证据与范围|
|---|---|---|
|SO-01 初始布局后读字段|PASS|时间零完整 group 4 mask=4095、group 64 mask=3，48 个对象；随后只读 group 4 bits 0/1。186 条采样、332 个数值字段核对原解密载荷。仍称生命候选，不能由数值认定对象名字。|
|SO-02 状态原包定位|PASS|55 条 0x3f3 状态逐包核对，保留 8d/9c/9d 原码及研究相关解释，authoritative_state=null；未知码保留未知。|
|SO-03 无未来回填|PASS|四份回放各四次前缀比较；身份、阵营保持 null，decision_input_eligible=false。初始化之前的状态包仍保存在原始流，但不倒填到对象前缀。|
|SO-04 水晶摧毁相关链|PASS（相关性范围）|0x40000028 在 833.3770312500042 秒出现 9c，833.4440312500042 秒首次后续生命候选为零，840.29052734375 秒关键帧为 9d、生命仍零；最终 BARRACKS_KILLED=1。水晶类型是事件族推断，未获得完整名字、阵营、路线。|
|完整身份目标|INSUFFICIENT_EVIDENCE|小兵创建 ID/名字尚未解；水晶和基地完整名字未解；没有水晶复活循环、倒计时与非英雄可见性。|

执行主体 Codex，REPRODUCED 开发自检。软件检查不替代独立游戏 UI 验证，原始回放的结算仅用于事后交叉对照，不进入前缀输入。单局仅一个破坏相关转换，不声称通用枚举语义或所有地图兼容。

|回放|对象|采样|数值字段|状态|
|---|---:|---:|---:|---:|
|11360086609|6|130|220|31|
|11363048522|14|14|28|6|
|11363093470|14|28|56|12|
|11372643015|14|14|28|6|

四份源文件 SHA256 均未变化，完整值及逐项结果见 structure_evidence_real_validation.json。短局无结算列表，相关交叉对照为 null，没有将缺失统计当成零。48 为跨回放实例数，不能当作一局对象数或 48 座水晶。

## 失败与限制

1. `research_special_names.py` 使用缓存 Map12 静态哈希及客户端名称格式，扫描零时刻 ASCII 正序/逆序的一一字节替换重复结构，匹配 0。结果 data/private/world_objects/special_name_candidates.json。它不排除打乱、变长或其他编码。
2. `research_spawn_ids.py` 保存 38 对 0x10a 候选字段与附近出生对象的暂定关联（16 训练、22 保留）。16 位八个简单变换模板 UNSAT；32 位八个求解超时 unknown。结果 spawn_id_models16.json 和早期 spawn_id_models.json；没有把候选字段认定为对象 ID，没有正式 profile。早期样本满足的“对象 ID 加4、左旋1位、各字节独立双射”在完整38对有反例，原来的局部吻合不能采纳。即使拟合成功也不能仅靠此证明字段语义。具体反例保存为 spawn_id_candidate_rejection.json。
3. 首次 `verify_structure_evidence.py` 失败于 `assert following and ... == 0`。根因是初始 replication 在 stream=1 的零时刻，代码误限 stream=2，导致 discoveries 为空。修正为时间零完整布局筛选，新增实际对象数量断言，之后重跑通过。没有改原包、放宽生命断言或跳过失败项。
4. 基地候选虽然存在初始 5500 数值，尚无名字与生命终态解码；没有按血量宣布 Nexus 已完成。视野枚举不自动变成所属队伍，未知队伍保持 null。生命采样不等于连续状态，状态切换时不能提前填入晚 0.067 秒的零值。

## 文件与复现

新增 `lol_coach/structure_evidence.py`、`scripts/export_structure_evidence.py`、`scripts/verify_structure_evidence.py`、`tests/test_structure_evidence.py`；研究脚本 `research_special_names.py`、`research_spawn_ids.py`；任务卡 docs/SPECIAL_OBJECT_TASK.md。修改 README、CURRENT_TASK、STATUS 及信息索引生成器。派生数据 data/private/structure_evidence，报告与运行清单 reports/structure_evidence_*。

实际执行：

```powershell
.venv/Scripts/python.exe scripts/research_special_names.py
.venv/Scripts/python.exe scripts/research_spawn_ids.py
.venv/Scripts/python.exe scripts/research_spawn_ids.py --bits 16
.venv/Scripts/python.exe scripts/verify_structure_evidence.py
.venv/Scripts/python.exe -m pytest -q --basetemp=data/tmp/pytest-structure-evidence-20261019a --junitxml=reports/pytest-structure-evidence.xml
.venv/Scripts/python.exe scripts/build_information_catalog.py --catalog-only
```

实际 pytest **266 passed in 1.23s**，新增 12 项 synthetic 软件边界检查；XML 为 reports/pytest-structure-evidence.xml。上述 basetemp 是当时新建目录，重跑需更换新的目录名。求解脚本依赖已有 D:/1/yxlm/vendor/reverse-tools/z3，仅用于研究，不是导出运行依赖。32 位首次运行时尚无 --bits 参数；现在默认 32，输出名改为 spawn_id_models32.json，原结果保留不覆写。

下一项：从创建记录分界及独立对象标识入手，而不是扩大对现有血量/时间假设的拟合；随后关联对象名字、阵营与可见性。当前无需用户操作。人工签署、独立复核、费用与 Token 统计均未取得。
