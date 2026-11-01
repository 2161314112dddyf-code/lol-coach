# ROUND-008-EVIDENCE：现有材料实际补证

执行2026-11-01，目标构建16.20.824.8524。依据[任务卡](../docs/TRAVEL_EVIDENCE_TASK.md)，证据data/private/time_evidence_20261101；恢复点data/private/document_backups/ROUND-008-EVIDENCE-20261101。开发侧自检及独立AI代码审查，不是外部人工或教练签署。

## 结果

新增一条指令标记到停留的视觉时间旁证、一个稳定阵营字节候选及具体否定结果。没有新增完整步行实测，没有新增可靠绝对到达时钟标签，也没有正式补上短回放的英雄/队伍绑定。原T5/T6仍INSUFFICIENT_EVIDENCE，模型数值ETA未接入；不改门槛来宣告成功。

## 身份原包探测

`scripts/research_travel_identity_evidence.py`实际读取四份原回放596,985包，28项输入哈希未变。输出identity/research.json、summary.json、execution_checks.json；不是仅扫描既有摘要。

- 三短回放statsJson均为空，0x445目录只能提供owner。48522还有0x400000af，不能因旧state只选择ae就把第二owner删除。
- 新候选：0x355、payload偏移67，主局已知10英雄×15关键帧共150/150对应team100→0x26、team200→0x66。三短ae为0x26，48522 af为0x66。短片首包锚点均time0、stream2/chunk1；48522 ae offset6614、af13702；93470/43015 ae offset6556。
- 这是同局标注上的重复记录相关性，不是150个独立身份样本。字段语义尚未恢复，来源又是关键帧，不能直接赋予时刻t的live权限；生产目录保持unknown。
- 48522 ae实际重解命名活动PantheonQ×9、E×1、W×1；首条19.73005194091797秒，stream1/chunk9/offset1049。支持潘森技能使用者的旁证，不单独证明出生身份，也不跨回放外推。
- 93470/43015没有命名活动。21种明文/UTF16及既有对象名字编码探测没有短片命中。0x445中短片ae与主局MasterYi共有24—26字节片段，故不能用该片段直接认英雄。
- 68个固定偏移候选检查全部保留，51个因后续记录不稳定/短包等反例被否决。未只展示命中假设。

身份侧8项工件约束检查及py_compile通过，意义是脚本和证据完整，**不是身份语义验收通过**。

## 录像实际检查

原24.933秒、30FPS、748帧视频SHA c71effa29b0af009a47fb24789dce4a503fc5398517d8425a3d46a5e91720522。新增`research_existing_travel_video.py`只做原帧提取，不读取预测。顺序读取全部748帧，保存87个指定原帧；11组顺序/定位读取逐像素一致。另用原提取工具查看12—20秒概览与细节，视频侧16项检查通过。

最终标签video/visual_evidence_v2.json：

| 观察 | 视频时刻 / 帧 | 能证明什么 |
| --- | --- | --- |
| 英雄尚在上路 | 12.0秒 / 360 | 上路停留；此时尚未离开 |
| 镜头移走、英雄不在画面 | 12.2秒起；13—17秒概览 | 不能给中间段完整出发时间 |
| 地面指令标记 | 14.4秒frame432未见；14.5秒435圆环；14.6秒438绿色标记 | 接收/显示指令的视觉锚点，不等同物理起步 |
| 英雄重新入画 | 17.5秒未见，17.8秒534可见 | 修正首轮粗采样18.0秒，仍非出发 |
| 平移停止 | 19.6—20.0秒 / 588—600 | 保守停留区间；精确接触点、自动到达/打断未知 |

点击地点与最后停留地点位于相同草地/铺装区域，可作定性空间旁证，不能据此宣称精确世界坐标到达。用户旧说明“未按S、可能下一指令打断”保留，不推导成确定自动到达。

HUD时钟327—372帧放大后仍不能稳定分辨末两位。初看全图似00:34，放大后00:24等替代解释不能排除；没有采信任何读数。主代理实际查看原frame360与clock_sheet_02，同意不建立独立时钟锚点。不能按旧包时间偏移反推模糊字符。后段时钟出画，因此新增绝对游戏时钟到达标签为0。v1及更正后的v2均保留。

## 冻结预测与视觉对照

新增`lol_coach/travel_observations.py`计算完整区间误差，保留缺失与去重；`scripts/compare_travel_video_evidence.py`核验原ROFL/视频、提取manifest、旧预测SHA及旧样本身份后生成结果。实际两次运行exit0；最终comparison_v2仅修正内层文字为指令标记到停留，初版comparison保留，数值没变。

| 项目 | 预测 | 视觉证据 | 处理 |
| --- | ---: | --- | --- |
| 中间段，冻结预测eta_7b2ffa3bddeb1a845d5675ca | 5.27184683秒 | 指令标记[14.4,14.6]→停止[19.6,20.0]，区间[5.0,5.6]秒 | 数值相容的指令响应旁证；真实出发null，不计新增完整步行样本 |
| 旧末段，eta_426111a8f9c5943944c6b369 | 2.37512503秒 | 出发[20.7,20.8]→停止[23.1,23.3]，区间[2.3,2.6]秒 | 保留旧一例，不重复计新 |

前者包含未知的指令显示/执行延迟，起点与物理出发不同；比较相容不代表证明两种时间严格相等。最终new_complete_samples=0、total_complete_samples=1；完整步行准入、身份权限和指令响应三个结论分开。

## 软件检查与修正

新增tests/test_travel_observations.py共66项，覆盖区间误差传播、缺起止不凑样本、旧样本去重、关联/终点未知不升级、非法值及错源拒绝、输入不变。首轮61过/5失败：缺起止分支绕过预测及剩余窗口的数值校验，允许NaN/Inf/bool等进入结果；已提前验证所有已提供值，原66项全部通过，保留observations_first与final回执。

完整回归 **1185 passed in10.02s**，full_tests.json/JUnit记录目标源码运行前后哈希一致。独立AI审查记录在independent_review.json；真实源数据检查、软件测试、人工签署互不替代。人工签署、费用与token读数未提供；本轮决策模型调用0。

## 现有材料范围与下一步

replay_inventory.json实际检查同一回放目录33个容器头。当前支持16.20.824.8524仅既有四份；HN1-11404040952为16.21.829.9102，其余为其他构建/旧容器，没有冒用当前协议解码。

| 验收 | 结论 |
| --- | --- |
| E1 短片身份绑定 | INSUFFICIENT_EVIDENCE；新字节与技能旁证保留，未写确定身份 |
| E2 实际视觉检查 | PASS（原帧核读与缺失记录）；新增完整时长/绝对到达证据为0 |
| E3 冻结对照 | PASS；来源绑定、区间算术、旧样本不重复，新旁证不混作完整时长 |
| E4 软件与来源检查 | PASS；66新增、1185全套，8身份/16视频工件检查，原失败保留 |
| E5 数值ETA准入 | INSUFFICIENT_EVIDENCE；没有新增能满足原T5/T6的独立到达标签 |

本轮尝试已完成，不能据此说缺口已补齐。现有视频的起步遮挡与时钟模糊不会因重复查询而消失。下一必要输入是另一段可清楚核对起止/时钟的对应连续画面，优先已有兼容回放的录像；若只能录当前版本，先做版本解析与身份绑定检查，再安排一次成组录制。尚未要求用户新录、启动游戏或提供密钥。单独研究0x355候选可继续，但它不能代替物理计时证据，身份unknown也不应阻止离线时间比较。

## 运行

项目根目录执行，输出使用新目录，旧证据不覆盖：

```powershell
.venv/Scripts/python.exe scripts/research_travel_identity_evidence.py --output data/private/travel_identity_repeat
.venv/Scripts/python.exe scripts/compare_travel_video_evidence.py --visual data/private/time_evidence_20261101/video/visual_evidence_v2.json --output data/private/travel_visual_compare_repeat
.venv/Scripts/python.exe -m pytest tests/test_travel_observations.py -q -p no:cacheprovider --basetemp=data/private/travel_observation_tests_repeat
```

新脚本/模块/测试与本报告、任务卡、简版结果为新增文件；CURRENT_TASK、DEVELOPMENT_GUIDE、PROJECT_SUMMARY、STATUS同步接管点。原预测、旧标注、模型输入、decoder、宪法保持不变；无Git推送、训练、前端或游戏操作。
