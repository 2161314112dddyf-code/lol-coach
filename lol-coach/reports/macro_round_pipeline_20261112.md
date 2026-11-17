# 一名玩家的地图回合怎样进入复盘

每次暂停时，先回答玩家的一个问题：“我上一手图什么，现在还能照着做吗？”复盘把前一次给这名玩家的建议带到当前时刻，再用当时本队能知道的信息检查。期间一次交技能、换一个走位或转向另一片野区，都可以发生在同一个地图计划里。玩家是否真的执行过上一手，须另有行动证据。

## 两局实际跑出了什么

**11 月 13 日更正玩家归属。** 两份开局日志均把本机玩家标为蓝方潘森。十人实战 `HN1-11461276459` 中你是辅助潘森，卡牌是己方中单。重新读取原始回放每人的赛后 `DRAGON_KILLS`，蓝方五人均为 0，红方剑圣为 4，红方其余四人均为 0。下面卡牌的两帧用于测试队友视角。03:43 的己方击杀公告取自单人训练回放 `HN1-11461236084`，那局潘森结算记 2 条。此前把训练局收龙和队友守中并列展示，让读者误以为实战潘森拿过龙。这场十人局的本人复盘固定为蓝方潘森。两局结算数据只作事后核对。[两场本机身份及全员小龙结算](../data/private/pantheon-dragon-20261113/verified.json) · [从原始文件复验](../data/private/pantheon-dragon-20261113/verify.py)

| 对局和时刻 | 当时可知的变化 | 给这名玩家的判断 |
| --- | --- | --- |
| 十人局 HN1-11461276459，蓝方卡牌 07:10 | 卡特和剑圣都已脱离本队视野，最近的位置采样分别在约 3.5 秒和 44.4 秒前。 | 先守住自己在中路的回防位置，可报卡特消失。向小龙走缺少通行和接应依据。 |
| 同一名卡牌 07:35 | 卡特重新露头，剑圣仍失踪。 | 此刻可以报卡特的位置。报点内容已改，守中的理由仍在，延续上一轮。 |
| 训练局 HN1-11461236084，蓝方潘森 03:31 | 潘森正在打云霄亚龙，龙剩 9,458 血。 | 继续输出这条活龙。单人训练里没有对手回应可供推断。 |
| 同一训练局潘森 03:43 | 画面已经显示己方击杀云霄亚龙，坑外可见河蟹。 | 这轮打龙计划到此结束。现在可以查看河蟹值不值得打，后续是否去打留待观察。 |

两组都走正式命令、真实 stdio MCP、输出校验和跨帧传递。卡牌案例中，先封存 07:10 的答卷，再看 07:35。潘森案例用预写答卷复查已知事件。从同一时刻改用本地 `llama3.2:1b` 独立作答，它在三次响应中成功查询工具，却把事实编号当成玩家建议，答卷被拒。四张通过的卡用于核查工程链路，独立模型的战术判断仍待评阅。

本机可打开[实战本人潘森 05:00 可知的局势](../data/private/reasoning/vision-blue-pantheon-5m-1622/frame.md)、[实战队友卡牌的两张样例卡](../data/private/reasoning_sessions/macro-tf-430-455-v2/review.md)、[单人训练潘森的两张样例卡](../data/private/reasoning_sessions/macro-secured-cloud-drake-0b81d15a/review.md)、[训练录像 03:43 的游戏画面](../data/private/final_replay_20261112/video/13-00-49_132.0.jpg)、[训练局替换证据的对照结果](../data/private/reasoning_sessions/macro-secured-cloud-drake-0b81d15a/macro_acceptance.json)和[本地模型的实际输出](../data/private/reasoning_sessions/macro-local-1b-dragon-v2/01/result.json)。公开仓库只保留说明、代码和离线测试。

## 从暂停到出卡

1. 正式入口按对局、玩家、队伍和时刻绑定输入。MCP 的 `review_round_plan` 给出上一轮建议、支撑它的旧观测、本帧对应变化，以及实际有覆盖的各路兵线。旧位置的消息只变得更久，不能单独证明局势换手。
2. 模型先判断这名玩家该争、该守、换边、发育、回补，或暂时看不清。它写下地图目的、能这样做的条件、对手可能怎样回应，并引用本帧证据。另用 `compare_round_options` 比较立即走、协助后走、接线后走的代价。`--target dragon` 只给这组计算指定地点。
3. 下一张卡分别判断地图计划是否延续，以及眼前的第一步要不要改。结束旧计划须引用一项本帧能查到的变化。已覆盖的一个具体反例是上一手依据活龙施压，当前已有击杀公告，却用本人血量变化代替公告来宣称龙已死。宿主会拒绝这种答卷。其他换手原因还需要逐案评阅。
4. 通过校验后才写出单帧玩家卡，并把这张卡带到后续时刻。整段有可交付的卡时，`review.md` 按时间串起来，可点入每帧查看第一步、各选项代价与退出条件。

## 怎样复跑

从 `lol-coach/` 运行。公开副本可用合成输入检查收尾引用、跨目标延续、旧格式兼容和真实 MCP 子进程。

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pip install ".[review-mcp,map]"
.venv/Scripts/python.exe -m pytest -q tests/test_macro_round_contract.py tests/test_round_perspective_tools.py tests/test_round_agent_integration.py
```

这台工作机已保存卡牌两个冻结时刻。以下命令输出两帧可用的 MCP 证据。在安装了相应模型并启动 Ollama 后，把 `--backend probe` 换为 `--backend ollama --model 模型名` 可用同一输入独立作答。每次运行取新的输出目录。

```powershell
$py = (Resolve-Path 'data/private/agent_study_current/mcp-env/Scripts/python.exe').Path
$rofl = "$env:USERPROFILE/Documents/League of Legends/Replays/HN1-11461276459.rofl"
$b = 'data/private/reasoning'
$out = 'data/private/reasoning_sessions/macro-tf-' + (New-Guid)
& $py -m scripts.run_review_agent --perspective comparison --bundle "$b/macro-tf-430-r1/bundle.json" --bundle "$b/macro-tf-455-r1/bundle.json" --lane-replay $rofl --lane mid --target dragon --help-seconds 5 --backend probe --output $out
```

这台工作机也能一条命令重放潘森的预置答卷和替换证据的反例。

```powershell
data/private/agent_study_current/mcp-env/Scripts/python.exe data/private/macro-dragon-audit-20261112/run.py
```

本轮全量 pytest 结果为 **1,401 项通过**。跨目标延续已用合成案例验证了链路能表达。下一项战术验收是另取十人实战，逐帧判断取得线权后转点施压、对面回应后主动权由谁接手。比较工具目前只计算本次指定地点的三个走法，改去别处的到场时间仍需该地点的路线证据。
