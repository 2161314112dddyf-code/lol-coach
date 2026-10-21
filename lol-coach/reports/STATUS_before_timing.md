# 当前状态

更新时间：2026-10-13。已实际核验新回放和手机录像。当前任务是移动事件与时间/位置验证，不是艾翁刷野；不要求现在重开游戏。此前静态基础保留，历史见 STATUS_before_video_validation.md。

## 本轮完成

- 在项目虚拟环境固定 opencv-python-headless 4.12.0.88、numpy 2.2.6，读取视频：1280×720、748 帧、30 FPS、24.933 秒。保存抽帧及源哈希。
- 新回放 HN1-11372643015.rofl，版本 16.20.824.8524，metadata.gameLength 54051 ms；日志 GameID/版本/Default 皮肤匹配。视频同局关系由用户提供和动作顺序/区域支持，没有内嵌唯一 ID 证明。
- 先保存独立逐秒视觉标注，再原样使用旧实验解码器/替换表：187 个候选移动包结构解析，292 条记录、0 失败，无重新拟合。
- 英雄候选 0x400000ae：10 条记录（1 快照+9 stream 1）。三次单点等于前一计划终点，与画面停留粗略对应。一次路径被替换，不把旧终点当已到达。
- 用户确认“没有按s可能被我的下一个指令打断了”。保留“可能”，不指定哪段被主动打断。
- 9 条 stream 1 记录与 SRX_3 比较：0 基础阻挡接触、3 含不确定 flags、0 overlay 区域接触。实际碰撞/通行性未确认。
- 人工画面区间的时钟偏移没有公共交集（区间间隔约 0.58 秒）；未伪报精确时间校准通过。这个数不是解码器实际误差。

## 真实测试及缺口

完整离线测试 **100 passed in 1.17s**，无失败/跳过（既有 90+新增 10）。结果见 reports/pytest-movement-video.log、pytest-movement-video.xml。

真实素材复核脚本已通过哈希和结构检查，并如实输出时钟未校准，不是精确游戏动作验证通过。1 份视频可用于定性核对；可进入精确行动耗时模型的样本仍为 0。坐标误差、精确到达时间、途中主动停止和完整状态仍未验证。手机画面遮挡、英雄离开主画面时，不能补成连续轨迹。

## 文件与运行

新增 requirements-video.txt；scripts/inspect_movement_video.py、decode_movement_sample.py、verify_movement_sample.py；lol_coach/movement_validation.py；tests/test_movement_validation.py；reports/movement_visual_annotations.json、movement_video_validation.json/md、pytest-movement-video.log/xml、STATUS_before_video_validation.md。更新 README.md、docs/NEXT_OBSERVATION.md、本文件。证据在 data/private/movement_11372643015/，未上传。原视频/回放/游戏文件未修改。

在 D:/1/yxlm/lol-coach：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-video.txt
.\.venv\Scripts\python.exe scripts\verify_movement_sample.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-movement-video --junitxml=reports/pytest-movement-video.xml
```

首次抽帧及解码的完整命令见 README.md 最新章节。适配器依赖父目录已审查的实验代码/替换表，不宣称独立发行或支持其他版本。

## 下一项

现有视频已使用，无需立即重新操作。下一阶段解决时钟对应和独立位置精度，再建立行动耗时样本；补充明确的途中改令或停步对照。当前画面不能唯一解决这些问题，不以恒速或默认模型知识填补。未来有空补录见 docs/NEXT_OBSERVATION.md，英雄不限，S 不是强制操作。

不开发前端、不微调、不输出当前局决策点评。详细证据与限制见 reports/movement_video_validation.md。
