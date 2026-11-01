# 时间计算独立测试结果

2026-11-01，ROUND-008-TIME-TEST。

**已完成独立于模型链路的测试；恒速短程计算有支持证据，但尚不足以把它当作可靠的实际到达时间，因此本轮没有接入模型。** 未修改原耗时公式或原回放，没有重新拟合参数。

先由实时路径和当包速度冻结24,501条预测，再单独用后续位置、死亡/复活候选和既有视频标注评价。修正评价器时保留全部原预测、初版结果及失败记录，没有挑选成功样本重新预测。

| 对照 | 实际结果 | 能说明什么 |
| --- | --- | --- |
| 已有视频实测 | 预测2.375秒；视频观察2.3—2.6秒，吻合 | 这一段短程的恒速估算合理；只有1条，且是历史回顾性标注 |
| 英雄终点实时报告 | 95个短程对照，报告时间偏差中位0.024秒、P90 0.047秒、最大1.196秒 | 对有终点报告的样本，公式与报告时刻通常接近；不是实际到达误差分布 |
| 小兵终点实时报告 | 7个对照，中位0.056秒、P90/最大0.316秒 | 数量不足；另1个稀疏关键帧终点单独保留，不混入实时报告精度 |

为什么还不接：16,354条0.1—10秒英雄预测中，15,950条在预计结束前收到新路径，57条遇终止证据，12条起点已知死亡，240条后续出现在别处而首次到达未获证实；95条得到终点报告。81个较窄到达观察区间集中在同一局，不能证明多局泛化。中途更换路径不算计算失败，后来出现在别处也不能证明之前从未到达。

独立审查纠正了三种评价误差：死亡后34毫秒生成的路径不能当可执行移动；隔8秒才出现的终点关键帧不能当真实迟到；同一时间戳内，路径后面的死亡消息不能漏掉。初版将这些混入“到期未到/时间偏差”的结果已保留并明确被修正版替代。

**准入结论：INSUFFICIENT_EVIDENCE（证据不足），不是证明距离÷速度公式错误。** 目前可保留为“沿该路径、速度不变且未中断”的条件计算，不可据它断言已经到达、能安全赶到或来得及撤出。下一子步仍属于ROUND-008：用现有材料补齐路径有效期与速度变化/观测中断处理，再按真实可比较的到达区间评价；不重复兵线解析，也不直接进入训练或战术盲评。

新增独立工具`lol_coach/travel_validation.py`、`scripts/audit_action_time.py`和`tests/test_travel_validation.py`。最终**61项新增边界测试通过；完整1019项通过（12.85秒）**。软件测试不代替实局精度验收。

在`lol-coach/`运行，输出目录必须是新目录：

```powershell
.venv/Scripts/python.exe scripts/audit_action_time.py freeze --output data/private/time-test-new/frozen
.venv/Scripts/python.exe scripts/audit_action_time.py evaluate --frozen data/private/time-test-new/frozen --output data/private/time-test-new/evaluation
.venv/Scripts/python.exe -m pytest -q tests/test_travel_validation.py --basetemp data/private/test_tmp_time_new
```

前两条依赖本机既有四份回放导出及视频标注；公开仓库可运行合成边界测试。实际最终证据位于`data/private/time_audit_20261101/evaluation_v3/`；v1/v2及所有失败不覆盖。[详细口径与执行记录](../reports/action_time_validation_20261101.md)。当前无需用户重开游戏或补录；没有模型调用、训练、前端或Git推送。
