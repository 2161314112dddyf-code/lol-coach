# RPL-003C 实际结果（2026-10-19）

已新增可运行的装备操作解码与导出。目标构建 16.20.824.8524，限四份有哈希及实体目录的回放；不声称适配其他构建。整体 RPL-003 尚未完成。

## 已取得的动态结果

| 回放 | 操作包 | 槽位更新 | 移除 | 换位 | 未识别物品更新 |
|---|---:|---:|---:|---:|---:|
| 11360086609 | 336 | 190 | 115 | 31 | 0 |
| 11363048522 | 4 | 3 | 1 | 0 | 3 |
| 11363093470 | 3 | 2 | 1 | 0 | 2 |
| 11372643015 | 4 | 3 | 1 | 0 | 3 |

347 个包全部按当前支持的结构消费完，没有剩余载荷或截断错误。整局覆盖 65 种物品编码。每条结果保留英雄实体、原包时间、流、chunk、解压偏移、完整载荷及哈希；不是把结算背包倒填成时间线。移除事件不擅自附上旧物品 ID，更新不自动等同购买，换位不自动等同售卖。

三个操作码：0x025f 槽位更新、0x0132 槽位移除、0x0066 换位。位域分支及字节表仅涵盖观察到的形式；数量字段标为候选，操作包中的金币字节仍保留 opaque。金币数值由上一切片 0x03df 独立解出。

## 语义证据及其边界

物品名字来自官方固定版本 16.20.1 item.json，真实 HTTP 200，内容 SHA256 `bcd7100b7f6c336f585fccaa28324b9d676bf1b2932ae3bb79ee56b5775c47d6`。它是静态目录版本，不自动证明所有地图/模式的配方兼容。缓存含 URL、抓取时间和原响应。

14 个初始标签结合 ID/价格字节约束得到 37 种唯一候选；明确使用最终槽位校准后得到 55 种普通签名；再用同帧组件移除、合成目录和字节一致性解开剩余 7 种普通签名，以及天使之杖、炽天使和魄罗佳肴，共 65 种编码。最终槽位参与拟合，**不能再把最终背包一致称作独立验证**。两处换位字节也使用结算槽位校准，记录为 08→3、0e→4。

独立经济检查使用 `累计金币 - 当前金币` 的变化，比较操作后的首个金币同步（最多 0.15 秒）。同一个同步区间内的两次购物合并核对，避免重复归属扣款。该金币数据未参与物品 ID 字节拟合。

- 165 个区间：预测净支出与实际值误差小于 0.1 金币，PASS。
- 14 个区间：没有落入窗口的金币更新，INSUFFICIENT_EVIDENCE；主要是免费物品更新和自动转化，不能据此写成零扣款已验证。
- 2 个区间：FAIL，完整保留。瑞兹 433.848 秒预测 -300、实际 650；凯尔 510.598 秒预测 0、实际 550。此前分别出现 0x02ef 背包重同步候选，旧物品状态未恢复，说明只串联三个操作码不足以覆盖撤销购物。

例：婕拉 209.717 秒移除遗失的章节、更新为 Blackfire Torch，目录差价 1600 与实际净支出一致；732.156 秒移除 Haunting Guise 与 Fated Ashes、更新为 Liandry's Torment，差价 800 一致。

## 明确保留的缺口

1. 整局 6 个 0x02ef 重同步候选已作为 state_barriers 导出，尚未完整解码。关键帧背包的时间/观察范围也有不一致，未强加固定时间偏移。
2. 维迦、死歌最终无魄罗佳肴，但目前操作流没有还原其消耗消失。初始槽位、未观测消耗、未知特殊道具都不能补成空。
3. 三份训练回放的 8 条特殊物品更新保留 wire code，item_id=null。完整背包状态、交易原因、可靠数量均未完成。
4. 技能仍为 INSUFFICIENT_EVIDENCE。训练回放五处资源扣减分别 25、78.7723、25、25、55，与官方潘森 Q/E/Q/Q/W 消耗相容；这是关联证据，不是技能字段解码。0x02a1 有重复/阶段性记录，固定尾部偏移假设在整局的变长记录上不成立；接受的新施法事件仍为 0。
5. 视野仍为 INSUFFICIENT_EVIDENCE。整局 0x03cd 共 2184 个：a0f5 1319、a0c5 865；其中英雄 604 个包，前者只对应结算队伍 100、后者只对应 200，同一英雄没有值切换。这不支持将两值命名为可见/不可见。包的发生是否关联进出视野、观察阵营与区域视野仍未知。

所有输出 `decision_input_eligible=false`，`complete_inventory_state=false`。不能据此使用当时不可知的敌方信息。

## 实际运行

在 `D:/1/yxlm/lol-coach`：

```powershell
.\.venv\Scripts\python.exe scripts\export_replay_inventory.py --replay "C:\Users\21613\Documents\League of Legends\Replays\HN1-11360086609.rofl" --output data\private\replay_inventory\HN1-11360086609.json
.\.venv\Scripts\python.exe scripts\verify_inventory_economy.py
.\.venv\Scripts\python.exe scripts\verify_replay_inventory.py
.\.venv\Scripts\python.exe scripts\research_spell_vision_anchors.py
```

CLI `--at 50` 已实际运行，输出 32 条操作。四份回放的前缀结果与完整结果筛选完全一致；负时刻、NaN、Infinity、超过回放长度的查询均实际拒绝。源文件运行前后哈希不变。

软件测试：12 项新增检查（实际载荷 fixture 与人工构造的错误输入），加 170 项已有测试，最终 **182 passed in 1.23s**，零失败/错误/跳过。测试证明解析与拒绝行为，不等同于未解字段通过。

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\1\yxlm\lol-coach\data\tmp\pytest-inventory-20261019-a --junitxml=reports/pytest-replay-inventory.xml
```

以上是本次实际命令；再次运行请选择新的空临时目录，pytest 会清理指定目录。首次运行因系统临时目录拒绝访问得到 165 passed / 17 setup errors；第二次因我漏建临时父目录得到同样数量的 setup errors；修正父目录后全套通过。两份失败 XML 分别保存为 `pytest-replay-inventory-temp-permission.xml`、`pytest-replay-inventory-missing-temp-parent.xml`，没有抹掉失败经历。

结构化报告：`replay_inventory_validation.json`、`inventory_economy_validation.json`。研究证据：`data/research/inventory_{events,calibration,constraints,recipes}.json`、`spell_vision_anchors.json`。冻结配置：`lol_coach/profiles/inventory_16_20.json`。

下一项是解析已定位的重同步/撤销与消耗字段，并沿资源扣减锚点恢复施法标识及去重规则；视野另查进出事件和观察阵营。现有回放足够继续研究，无需用户再次移动、补录、提供密钥或启动游戏。

实现及自检：Codex；独立复核、人工验收签署未执行。恢复点：`reports/inventory_bytes_baseline/manifest.json`。
