# OFFLINE-002：离线工作实际交付

2026-11-01。承接用户“去做”：先推进前序兼容和字段研究，再做不依赖录像缺项的分析工具。没有把未解语义写成完成，没有新增游戏操作、模型调用、训练或前端。

## 做成了什么

| 工作 | 实际结果 | 能说明什么 |
| --- | --- | --- |
| 新版本容器 | 16.21.829.9102：58块、763,799包，完整读到容器结束；新增18字节块头读取器 | 已解决首块解压失败；**不是新版游戏字段已解析** |
| 旧版对照 | 16.20.824.8524：21块、6,412包，新旧读取器逐包一致；186条旧移动包结构可读 | 容器改动没有破坏这份旧版对照 |
| 未知物品原包 | 四份16.20回放共81条使用消息，与旧导出逐条对应；80接受、1条ec拒绝 | 实际查了原包，ec没有被猜成确定槽位 |
| 整段边界候选 | 主回放0—859.9619135742223秒，175个观察时刻、170个候选 | 实际从当时可知帧生成重审行动的候选，不依赖数值ETA/冷却/区域视野 |
| 评测数据工具 | 170份冻结输入、来源审计单独存放；同一回放禁止跨训练/验证/测试集；支持外部标签检查 | 当前只有1个回放分组、0个人工标签，准确率/召回率为空，不能训练或宣称战术效果 |
| 测试 | 新增16项；完整 **1210 passed in 8.00s** | 软件自检，非实局精度或人工验收 |

边界触发总数：可见性变化200、友军生命周期候选115、公共击杀事件113、英雄零血观测100、已知兵线组成变化145、塔零血观测1。同一候选可以有多个原因。扫描间隔5秒，并保留283/293/300秒对照；不是把5秒定义为一回合。候选覆盖170/175时刻，说明当前提议偏密集，后续需要评定有效触发并合并，不能宣称自动分回合已验收。

一个实际例子：300秒帧引用`f_a229df0296d55e7bccf4`，塔`0x40000030`在299.602246826177秒被观测为0血，因此生成“重审原塔相关计划”的候选。这里只说明已出现新的零血观测；没有推导赶路来得及、后续开团安全，或玩家已经执行过上一项建议。

新增源码为`lol_coach/replay_container.py`、`round_boundaries.py`、`boundary_dataset.py`；新增CLI为`scripts/probe_new_replay_compatibility.py`、`audit_unknown_item_use.py`、`scan_round_boundaries.py`、`audit_boundary_dataset.py`。新增对应3个测试文件。新增任务卡和本文，更新CURRENT_TASK、DEVELOPMENT_GUIDE、PROJECT_SUMMARY、VIDEO_AND_OFFLINE_BACKLOG及STATUS；其他已有未提交变更保留，不归成本轮新增。

## 原包结论和失败保留

新版每个块在旧17字节头后多出`04`，该字节含义未知。原读取器首块Zstd失败；尝试把它算进压缩内容再去掉也会截断解压。把新构建块头改成18字节后58块全部读通。实现只接受这两个实际观察构建；未知构建或其他扩展字节拒绝。旧移动编号`0xc9`在新版stream1中出现0次，所以不能拿旧移动规则直接解释新版，更不能据此要求用户批量录当前版本。

未知`84b6ec`出现在746.952767秒、实体`0x4000003c`。最近背包快照689.734419/783.308917秒，期间716.625429秒另有槽1使用消息；同实体前后5秒原始包63条（前轮34条只是已解析类别，不是原包总数）。既没有同期槽位真值，也没有同物品换槽对照；普通未映射槽3/4/5及其他扩展解释均无唯一判别依据。后快照含不同排列，不能拿事后背包倒填。字段继续未知，整个研究包禁止进入时刻t模型输入。

首次整段扫描因预设859.962超过真实证据尾部859.9619135742223而失败。已改为读取实际证据边界，成功扫描另存`boundaries_v2`，原失败目录和stderr保留；没有扩大数据有效时间来掩盖失败。

## 复现

在`D:/1/yxlm/lol-coach`执行，输出目录必须尚不存在：

```powershell
.venv/Scripts/python.exe scripts/probe_new_replay_compatibility.py --reader extended --output data/private/compatibility_repeat
.venv/Scripts/python.exe scripts/audit_unknown_item_use.py --output data/private/item_audit_repeat
.venv/Scripts/python.exe scripts/scan_round_boundaries.py --output data/private/boundary_repeat
.venv/Scripts/python.exe scripts/audit_boundary_dataset.py --scan data/private/boundary_repeat --output data/private/boundary_repeat_audit.json
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=data/private/offline_tests_repeat
```

实际证据在`data/private/offline_execution_20261101/`：`compatibility/`是原读取器失败记录，`compatibility_v2/`有新旧逐包对照和失败假设，`compatibility_cli/`是最终CLI重跑；`item_audit/report.json`保存全部未知原包邻居及前后背包；`boundaries_v2/summary.json`、`cases/`、`audit/`、`review_queue.json`是整段结果；`dataset_audit.json`和`full_tests_execution.json`是实际检查记录。只在本地存放，不上传原始回放。

可选标签文件是JSON数组，每项含`candidate_id`、`frame_id`、`author`、`useful_reconsideration`（true/false/null）；传给评测CLI的`--labels`，标签与输入分开。只计算已提供明确标签的候选有用率；没有负例时刻全集不能算召回，没有真实战术标签不能算战术准确率。author记录标签提供者，不代表已验证其资质。当前没有代填任何标签。

## 接下来如何推进

1. 新版语义适配仍是离线工作：先寻找身份/位置/消息族对应关系，再决定新录制能否用于对照。容器已可读，不再从解压问题重来；旧构建ec结论不能直接迁移到新构建。
2. 边界候选已可整段导出。下一切片是抽取不同触发的少量例子，评定“是否确实需要改计划”，再据标签合并噪声触发；保留未触发时刻的负例才能评估漏报。不能把本次170候选当170个正确回合，不能用同一局拆分冒充独立测评。
3. 真正依赖新证据的项仍是[录像实验清单](VIDEO_AND_OFFLINE_BACKLOG.md)中的完整起止计时、施法成功/转好、换槽使用、区域视野对照。当前没有要求用户开游戏或重录；若要安排新版本录制，先完成对应字段预检。精确ETA/冷却/区域视野继续隔离。

本轮落实了已明确的离线交付，不等于所有可研究方向都已穷尽。扩展国服人类案例、更多英雄机制和新版字段仍可独立推进。人工战术标签/验收未提供，自检没有代签。

## 验收记录

目标构建分别为16.20.824.8524和16.21.829.9102；执行者Codex，source=target_claim，evidence_level=REPRODUCED，signer=null。

| ID | 状态 | 证据及范围 | 缺口 |
| --- | --- | --- | --- |
| C1 | PASS | compatibility_cli与compatibility_v2；实际容器读完、旧版一致 | 新版游戏语义INSUFFICIENT_EVIDENCE |
| C2 | PASS | item_audit；原包对齐、唯一未知及竞争解释完整保留 | ec槽位INSUFFICIENT_EVIDENCE |
| C3 | PASS | boundaries_v2、时间/来源拒绝测试、dataset_audit | 仅上游可知帧上的候选，未证实回合质量 |
| C4 | PASS | 175帧实际扫描、170案例、分组/标签校验和1210项回归 | 人工标签0，战术效果INSUFFICIENT_EVIDENCE |

恢复点`data/private/document_backups/OFFLINE-002-20261101/manifest.json`；原始素材与旧decoder未修改。[任务卡](OFFLINE_EXECUTION_TASK.md)。
