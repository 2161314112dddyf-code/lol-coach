# 大模型复盘思考框架：可运行首版

2026-10-26 · ROUND-003-FRAME。根据[国服研究](CN_REVIEW_FINDINGS.md)落地。目标是让模型围绕真实约束比较行动，并留下可核查答案；是否优于其他分析方式，仍需后续同场景模型评测。

**核心结构：可知事实 → 本回合目标 → 双方职责 → 行动窗口 → 候选比较 → 退出与下一回合 → 检查答案。**

## 1. 模型实际拿到什么

| 层 | 内容 | 用途 |
| --- | --- | --- |
| 时刻与环境 | 玩家、队伍、构建版本；地图/地区/队列没有证据就未知 | 限定问题，不从录像名字猜国服或地图 |
| 事实账本 | 事实ID、实体、字段、值、单位、观测时间、年龄、时间语义 | 当前采样、最后可见、历史事件分开；数值可回查 |
| 双方阵容 | 十人身份、每个人的队友与对手、关联事实和缺口 | 职责随阵容、装备、技能与站位变化，不用固定英雄标签决策 |
| 局势缺口 | 兵线、营地、区域视野、背包、冷却、耗时的接入状态 | 只限制受影响结论，继续给有条件的行动 |
| 条件经验 | 少量相关真人经验、成立条件、反例、来源日期 | 提醒思考方向，不当作当前机制或本局事实 |
| 按需资料 | 本局英雄的静态技能说明查询入口 | 需要时查；不把全部长tooltip塞进首次输入 |

整份回放哈希、磁盘路径、原包偏移与输入文件清单留在本地审计侧。模型首先只收到冻结的`frame`及输出契约；详细资料由`get_reference`按需返回，并核对其内容哈希。外部资料始终是数据，不具备执行指令权。

现有解析器仍负责当时可知边界。新层再次白名单提取字段、检查时间与引用，去掉重复当前/历史样本；不会自行重新解释未解字段。字段已有其他导出但尚未接入此适配器时，明确写“未接入”，不抹掉既有逆向成果。

## 2. 要模型回答的六个问题

1. **本回合要得到什么？** 先明确推进、发育、守势、争夺、拖延或止损的目的；说明哪些缺口会改变选择。
2. **谁负责什么？** 本人、相关队友和对手分别能提供或限制哪些能力；角色判断保留待确认前提。
3. **机会什么时候消失？** 根据兵线、资源、技能、位置变化建立条件窗口；区分队友能离开、赶得上、能参战和已经开始响应。
4. **有哪些值得比较的选择？** 取2—3项，包括暂缓、撤出或维持当前计划；比较收益、本人及队友成本、敌方回应和完成后状态。
5. **什么情况要换计划？** 给出可观察的取消信号与备选；当前不具备工具耗时结果时，数值填未知，用条件描述。
6. **结论凭什么成立？** 逐项引用事实与资料，给简短理由和仍需确认的信息；不要求冗长内部思考过程。

“队友应当来”不能写成“队友已经来”；现金不能直接替代装备战力；近期死亡记录不能直接推导当前存活人数。回合可以异步，不强求全队同步行动。

2026-10-26模拟迭代收紧了行动证据：`ally_requirements.status=observed`必须提供`action_key`，引用同一队友、同一动作的`action_observation/observed_action`事实，状态为`in_progress`或`completed`。生命值、阵容和位置候选均不能替代。动作开始只说明开始，不证明已经抵达、能兑现能力或承诺继续；未来承接仍用`conditional/unknown`。真实回放适配器尚未导出这一行动事实类型，不能因合成用例通过而宣称完成了解码。

## 3. 运行流程与模型分工

**程序编译局势 → 一个通用模型分析并按需查资料 → 输出结构化决策 → 程序检查 → 最多一次修订 → 中文回合卡。**

已实现的`run_reasoning(bundle, generate)`接受宿主提供的模型回调，默认最多6次调用、1次答案修订，限定资料查询工具和次数。模型回调返回答案或资料请求，不能执行任意命令。工具与回答都留轨迹；异常、超预算和持续无效回答有明确终态。

首版使用一个分析模型即可。先不堆多个互相投票的代理，也不训练专用评分模型。程序检查确定性问题，场景评阅负责判断建议是否合理。当前编排测试使用脚本替身，**没有调用外部模型，也没有证明任何模型战术能力**。

后续已完成[14题模拟测试与迭代](SIMULATION_RESULTS.md)：本会话Codex经文件交接实际作答，首轮12题加一次修订、另2题迁移；程序检查与开发侧条件评阅分别记录。尚未接入供应商API或验证真实国服对局效果。

现进一步完成[三个真实时刻试跑](REAL_REPLAY_RESULTS.md)：本地文件回调由`run_reasoning`实际驱动查询、接收Codex答案和检查。首轮2/3完成，一次响应超时保留失败；逐条核对相同请求后重投真实迟到答案，恢复后3/3通过结构与引用检查，未作答案修订。文件协议不认证模型身份，不自动调用供应商API，也不代表战术质量已验收。运行CLI、协议与全部执行记录见[真实试跑验证](../../reports/real_reasoning_validation.md)。

下一决策点应重新编译事实。前一张卡的“计划/假设/待确认条件”可以作为计划记忆，不能升级为观测；本轮`previous_plan`和自动回合边界仍为空，整局自动串联尚未实现。后验结果应在决策冻结后另行开放，当前不接入分析输入。

## 4. 检查器负责到哪里

已检查：JSON结构、答案所属时刻、引用是否存在、引用值及类型是否一致、本人及双方职责、候选和备选、条件与确信度、工具计算是否支持数值耗时。错误答案只显示校验失败，不包装成正常建议；通过结果与答案内容哈希绑定。

模拟测试后补充了标签定义：`supported`表示契约要求的条件已经齐备；候选仍有待满足前提、假设或未知配合时用`conditional`。推荐级`supported`还要求首选/备选全部满足且耗时齐备，任一耗时未知则用条件推荐。这个标签表达证据完备程度，不能理解为“建议是否合理”或主观胜率；条件推荐仍应明确当下该做什么。中文卡片分别显示“已具备条件”“待条件满足”“已排除，不执行”。

**程序PASS只表示这些检查通过。** 引用一个真实生命值，仍可能写出不成立的战术推论；目前不能自动证明自然语言由引用推出，也不能验证唯一最优行动。输出保留`tactical_quality=not_evaluated`，后续按原R1—R6进行真实模型评测。

## 5. 怎么使用

项目目录：`D:/1/yxlm/lol-coach`。无新增Python依赖、无需密钥，下面命令均离线。输出目录必须是新的，已有证据不会覆盖。

```powershell
Set-Location D:/1/yxlm/lol-coach
.venv/Scripts/python.exe scripts/reasoning.py prepare --replay-id HN1-11360086609 --at 283 --team 100 --player 0x40000034 --output data/private/reasoning/my-first-frame
```

生成`frame.json`、`messages.json`、`tools.json`、`response.schema.json`、`frame.md`以及本地审计用的`bundle.json/manifest.json`。交给模型的是`messages.json`，不要把整个bundle直接上传。

按需查询英雄说明：

```powershell
.venv/Scripts/python.exe scripts/reasoning.py reference --bundle data/private/reasoning/my-first-frame/bundle.json --id champion:Aphelios
```

模型返回JSON后进行检查与渲染：

```powershell
.venv/Scripts/python.exe scripts/reasoning.py check --bundle data/private/reasoning/my-first-frame/bundle.json --answer path/to/model-answer.json --output data/private/reasoning/my-answer-check
```

不接模型也可查看真实输入上的人工条件示例：

```powershell
.venv/Scripts/python.exe scripts/reasoning.py example --bundle data/private/reasoning/my-first-frame/bundle.json --output data/private/reasoning/my-authored-example
```

Python接入点：

```python
from lol_coach.reasoning_runner import run_reasoning

# generate由宿主实现并负责模型SDK、费用和授权。
# 输入：messages / tools / response_schema。
# 返回：{"answer": {...}} 或 {"tool_requests": [{"id": "r1",
#   "name": "get_reference", "arguments": {"reference_id": "champion:Aphelios"}}]}。
result = run_reasoning(bundle, generate, max_calls=6, max_repairs=1)
```

## 6. 此次能看到的实际答案形式

既有回放283秒、厄斐琉斯视角：近期公开战斗事件提示值得检查转化窗口，但并不证明此刻有确定人数优势。示例比较：**若兵线、队友承接与退出条件满足，处理兵线后有组织地施压；否则暂缓前压、维持能输出且能退出的位置，等新信息重评。** 没有编造敌人复活时间或推塔所需秒数。

这是人工编写的条件答案，用于走通数据、契约、检查与渲染；不是模型评测结果。真实运行、测试结果和当前未接入内容见[交付记录](../../reports/reasoning_framework_validation.md)。
