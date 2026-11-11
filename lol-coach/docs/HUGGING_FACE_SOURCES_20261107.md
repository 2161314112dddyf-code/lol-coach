# 哪些公开数据能推进英雄联盟赛后复盘

11 月 11 日已在现有决策输入编译器上用两局样本做实测，并用已有背包时间线重放四条操作。结果与玩家实验的变化见[可行性实验报告](../reports/hf_experiment_feasibility_20261111.md)。

2026-11-07，HF-001。逐秒职业赛数据最适合检验“某时刻模型能读懂多少状态”；旧版解码包最适合检验“哪些事件使这个状态发生变化”。当前国服回放构建为 `16.20.824.8524` 和 `16.21.829.9102`。

## 第一优先，真实对局的逐秒状态

[zauberine/lol-winprob](https://huggingface.co/datasets/zauberine/lol-winprob) 把职业对局整理成逐秒数组。实际统计 manifest 得到 6,242 局，按整数补丁号排序覆盖 **16.1 至 16.15**，其中 16.15 有 393 局。数据卡写作“16.1–16.9”，覆盖范围以固定版本的文件清单为据。按系列赛分组留出验证和测试集。作者标注许可 other，未在数据卡说明上游提供者、各字段的采样或填补方式。[固定比赛清单](https://huggingface.co/datasets/zauberine/lol-winprob/blob/d10424fb53f7a74b22b75a0c751edb96425fb40d/manifest.json)

实际从首个分片读出 `2877290_1` 的元信息和张量。此局为赛事服，版本 `16.1.736.4955`，有 1,934 个时间点。每个时刻有十名英雄各 26 项状态，以及每名英雄 7 个物品槽和对应的物品冷却列；眼记录为 261 行，含所属方、类型、位置、起止时间。英雄字段包含位置、生命、资源、金币、补刀、技能等级和冷却。这里的 CD 是采样状态，能否识别一次实际施法要另验。[字段顺序](https://huggingface.co/datasets/zauberine/lol-winprob/blob/d10424fb53f7a74b22b75a0c751edb96425fb40d/features.json) · [实际抽样分片](https://huggingface.co/datasets/zauberine/lol-winprob/blob/d10424fb53f7a74b22b75a0c751edb96425fb40d/shards/shard-0000.tar)

例如 10:00 的安蓓萨有 1,221 生命、75 资源、95 补刀，Q/W 冷却列约为 7.19、2.64，七个物品值是 `[2031,1037,3133,1054,3340,1222,0]`。这些是该库实际存储的数值。精确冷却单位、槽位排列与客户端 HUD 的一致性要另验，尤其不能把这一秒的采样值解读成按键时刻。样本的位置数值约在 0 到 1 之间，和 ROFL 世界坐标之间的变换未核实。

**接入点是现有回合快照的离线测试。** 截取时刻 t，仅选有依据可知的己方状态和已确认公开的事件，隐藏敌方逐秒真位置、未来帧、尚未发生的眼消失时刻、终局时间和胜负。比如可以测试“队友此刻的装备、资源与到场位置是否支持接团”，敌方视野不足时只给条件判断。数据没有逐单位兵线、普通营地里每个单位的状态或己方可见格；眼的寿命和位置本身无法还原全部草丛、墙体和扫描效果。

## 一局旧包能解答什么

从 maknee 固定提交 `04f9c7350e9ffcc689b731875ad9baf3ff6eaa6d` 的 `12_22/batch_001.jsonl.gz` 按 HTTP Range 读取，取齐第一行后停止。解压得到 **379,429 条、20 类事件**。这行只有 `events`，用目录标识 12.22，局内区服和地图模式留空。仓库另有 12.23、13.1、13.2。作者标注 Apache-2.0。[固定目录](https://huggingface.co/datasets/maknee/league-of-legends-decoded-replay-packets/tree/04f9c7350e9ffcc689b731875ad9baf3ff6eaa6d) · [抽样分片](https://huggingface.co/datasets/maknee/league-of-legends-decoded-replay-packets/blob/04f9c7350e9ffcc689b731875ad9baf3ff6eaa6d/12_22/batch_001.jsonl.gz)

| 项目缺口 | 一局里实际读到的证据 | 可以据此做什么 |
|---|---|---|
| 施法、冷却 | 1,528 条 `CastSpellAns`，其中 669 条技能名为空。15.469 秒的剑姬 Q 有施法者、槽 0、冷却字段 13、法力消耗字段 20。300.0995 秒机器人的 Q 与同角色同槽的 `DoSetCooldown` 同时出现，前者冷却为 18.518518，后者为 0，显示值为 −1。 | 检验“谁、何时、用哪一槽技能”的表示。把施法记录、冷却设置、自然转好分开。遇到后一例，仅凭这两条无法确定 Q 转好的时刻。 |
| 物品槽和金币 | 117 条购买、39 条移除、12 条换槽、122 条使用。科加斯在 14.081 秒买盾入槽 0，余额 50，14.709 秒买药入槽 1，余额 0，14.973 秒拿饰品入槽 6，18.309 秒交换槽 0 和 1。 | 用这一段检查状态回放。换槽后槽 0 应为药、槽 1 应为盾，槽 6 的饰品仍在。未知操作、缺初始状态和版本变化仍须单列。 |
| 兵线、营地 | 1,363 条 `BarrackSpawnUnit` 和 223 条 `CreateNeutral`。首次红 Buff 有对象 ID、坐标、名称和 `camp_id=4`。第一条出兵记录有波次和小兵 ID，兵种值却是 `18446744073709551615`。 | 可用营地身份和波次字段检验对象关联。异常兵种保持未知。营地生成时间不能用作打野开打、清完或离开的时间。 |
| 眼和区域视野 | 出现 `SightWard` 等对象。13,290 条 `EnterFog`、260,315 条 `LeaveFog` 的载荷仅有时间和对象 ID。 | 可研究某个对象的可见性转换。缺少观察方、地形遮挡和区域标签，无法凭两类包判断蓝方此刻能否看到龙坑入口。 |

导入还要保留原始行号。同局 10 个英雄各出现 13 次创建记录，按原顺序相邻事件的时间倒退超过 1 秒共 367 处。直接把每次创建当新英雄，或把文件行序用作实际发生顺序，都会产生错误状态。

如需筛选有身份的对局，同作者的旧归档更合适。完整解压 12.10 的 `BR1-2525639956`，内部记为单双排、时长 23:00，有 620,208 条事件和双方终局出装。该局蓝方打野皎月的出装列表可作终局参照，列表没有保留空槽，本次未把物品事件的对象 ID 绑定到皎月。主集和旧归档来自同一作者。配套 Gym 的动作是继续、快进和重置，适合重放已有轨迹。[旧归档](https://huggingface.co/datasets/maknee/leaague-of-legends-decoded-replay-packets-s12-unorganized/tree/037a3c58b9f0bd5ee95acddf2b8a76ded99c01c5/12.10) · [Gym 动作实现](https://github.com/Maknee/league-of-legends-decoded-replay-packets-gym/blob/ad6f264912d7b0e733292f4f3413ab9b59eb7607/league_of_legends_decoded_replay_packets_gym/league_replays_gym.py#L510-L545)

## 给复盘 Agent 的材料

| 来源 | 核对到哪一层 | 用在哪里 |
|---|---|---|
| [GPTilt 高分段时间线](https://huggingface.co/datasets/gptilt/lol-basic-matches-challenger-10k) | 实读北美 `NA1_5269865992`，版本 `15.8.675.10`。0 毫秒的英雄帧含血量、金币、位置。578,572 毫秒有人排眼，581,783 毫秒另一人购买 3057，583,587 毫秒又一人插眼。两条眼事件的坐标均为空。作者列 CC BY-NC 4.0。 | 分钟状态帧配合带毫秒时间戳的事件，测试经济、购买和目标事件能否按回合截断。保留空坐标与未知视角。击杀按参与者拆行须去重；强化表与基础表同源。[样本行 400–410](https://datasets-server.huggingface.co/rows?dataset=gptilt%2Flol-basic-matches-challenger-10k&config=events&split=region_americas&offset=400&length=11) |
| [GameCommBench 的 LoL 子集](https://huggingface.co/datasets/A4Blind/GCB) | 8,431 条职业转播片段元数据，含真人解说及描述、分析、背景分类。抽到一条解释减速英雄如何影响卡莉丝塔。全量核对原始解说文本，未检出基本汉字区字符；抽读为英语。许可标为 other。 | 评测模型能否把画面事实、机制解释和比赛背景写清楚。用 `human_commentary`，单独保留赛后已知信息与导播视角。国服主播的单排回合取舍仍需原视频、时码和可靠出处。[实际样本](https://datasets-server.huggingface.co/rows?dataset=A4Blind%2FGCB&config=lol&split=test&offset=5000&length=1) |
| [英雄对位与协同经验](https://huggingface.co/datasets/changjacHp/lol_champions_threat_synergy) | 预览约 21.2 万行。实际行有英雄、队友或对手、作者、作者主页、日期、主观分级和说明。2023 年的一位作者分别讨论敌方控制、己方保护如何改变进场选择。Hub 元数据未列许可。 | 按本局阵容检索带条件的经验，回到原攻略核对作者、版本、技能机制和适用场景。分级是作者判断。保留来源指针，批量复制正文或用于训练的授权未核实。 |
| [职业转播小地图](https://huggingface.co/datasets/ureca07/lol_viewport) | 抽读 manifest、比赛名单和视频来源。20 场，含 2024 世界赛 TES–T1 第一局。输入表示两队位置，监督目标为导播镜头区域。许可标为 other。 | 可找回真实团战画面核验“镜头看向哪里”。双方位置来自转播视角，不能原样送入玩家决策输入。[固定 manifest](https://huggingface.co/datasets/ureca07/lol_viewport/blob/8befa06a3ad0ff6c59025fad3165b303adb0f546/data/processed/manifest.json) |
| [合成小地图与英雄检测](https://huggingface.co/datasets/boboyes/leagueoflegends-minimap) | 1,200 张合成图，实读一个英雄框；配有已发布检测权重。雾层随机生成。数据与配套模型标 CC BY-NC 4.0。 | 有录像时先测裁图、缩放和图标检测，真实国服画面另测。随机雾不提供队伍视野真值。[标签样本](https://huggingface.co/datasets/boboyes/leagueoflegends-minimap/blob/60d4f4a9f96a63c2fea5734c56cddba32ee06fcb/test/labels/0.txt) · [配套模型](https://huggingface.co/boboyes/leagueoflegends-minimap-detection) |

GPTilt 的三份 `region_` 比赛表共 10,002 行，补丁 15.3–15.10。亚洲表 3,334 行由韩服 2,500 行、日服 834 行组成。另查 [LPL 赛事索引](https://datasets-server.huggingface.co/filter?dataset=gptilt%2Flol-esports-matches&config=games&split=train&where=%22tournament%22%20%3D%20%27LPL%2F2025%20Season%2FSplit%202%20Playoffs%27&length=2)，2025 第二赛段季后赛返回 71 行，决赛 AL 对 BLG 的前两局均为 25.11，录像链接和 Riot 对局号都为空。可凭对阵和补丁寻找中文录像，索引本身无法提供讲解。

另外核对了 [Match-v5 原始 JSON](https://huggingface.co/datasets/AngryBacteria/league_of_legends/blob/main/timeline_v5.json)，在欧服样本前缀看到 `frameInterval=60000` 和原始事件列表，可用来检查分钟帧的转换。[物品历史表](https://huggingface.co/datasets/HakimT/lol-item-catalog-history) 可按版本解释旧物品 ID，数据卡版本上限为 16.7.1。

## 对当前国服逆向最有用的下一步

另找到 Hugging Face 以外的 [RoflLens](https://github.com/ss26367098/rofllens)。作者给出了 `16.14.794.5912` 的施法字段、眼的创建与金币增减，并发布 5 份同构建韩服 ROFL。该构建施法为 `0x00c5`，包含施法者、技能槽、哈希、目标、耗蓝与冷却字段。装备整组与部分视野路由仍列为候选。作者的语义解析依赖精确匹配的客户端 EXE、协议摘要和哈希。本轮核对文档与发布清单，未运行该解码器。[发布说明和样本边界](https://github.com/ss26367098/rofllens/releases/tag/v0.1.0)

**先做施法。** 在已有国服回放中取已定位的潘森 Q/E/W 活动窗口，分别对照 16.14 解码器中施法者、技能哈希、槽位和时间的取值方式。在非施法窗口及另一份回放上盲查相同组合。能区分英雄与技能的候选再对照成功施法画面。冷却自然转好独立验收。这样可以直接用现有文件缩小候选范围，当前资料查找无需玩家补录。

## 如何复核这次抽样

逐秒样本的字段、数值、请求范围与文件摘要记录在本机 `data/private/hf_20261107/zauberine_sample_receipt.json`。从固定分片读取开头 1 MiB，取到完整 `sequence.npz`，SHA-256 为 `4d7fb51f9a063aca6df1dae70753eaf84d84c22b928e180f8659e7e6a83d1e52`。

压缩分片总长 86,557,239 字节；读了开头 2,424,832 字节即得到完整第一行。去掉换行后 57,608,291 字节，SHA-256 为 `cbece384fd9a6735570a35dfbe57e9d0100a9f010fa9b7a135bdf26c87f47482`。本机样本、抓取回执和计数在 `data/private/hf_20261107/`，原始玩家数据不随项目文档分发。从 `lol-coach` 运行即可复算事件总数和类别。

```powershell
.\.venv\Scripts\python.exe -c "import json,collections,pathlib; p=pathlib.Path('data/private/hf_20261107/maknee-12_22-batch001-first-match.json'); e=json.loads(p.read_bytes())['events']; print(len(e), collections.Counter(next(iter(row)) for row in e))"
```
