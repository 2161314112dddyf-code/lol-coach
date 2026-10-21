# 潘森机制与阵容交互交付

日期：2026-10-21。任务 MECH-001，对应已批准 F-03 的来源卡和条件化查询。**已交付五张技能卡、一个队友配合案例、一个对手限制案例及可运行的离线查询。** 不代表完整英雄机制、实局交互测试或当前对局的技能可用性已经解决。

## 实际资料与结果

使用已缓存的官方静态版本 16.20.1：

| 来源 | SHA256 |
| --- | --- |
| [Pantheon](https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Pantheon.json) | cd6b77c20fc056c675c3c300c812a444e955885b68c3be4fb12af1eb98c99ce8 |
| [Jhin](https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Jhin.json) | 7e9a93cf95183dee279b0c4d6678142ad38f2e046b0212f7cf4e96e50545d49e |
| [Morgana](https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Morgana.json) | 346d7db6a34ac16ea002ea952b3cee0a7eb817dabddbf7ed2bf02f65783439bc |

当前官网英雄页面只作旁查，不作为 16.20.1 的版本证据。卡片结论引用固定缓存的 JSON 指针；原文抓取时间沿用缓存记录，不把本轮整理日期冒充抓取日期。还检查了既有内部潘森记录，但没有将其未验证参数或模式覆盖直接提升为运行时规则。

五张卡分别保留 P 的强化条件、Q 点按/投掷差异、W 伤害与眩晕、E 方向与非塔伤限制、R 投矛/落地及强化就绪。每张都有队友条件、对手条件、项目分析和未知项。详细 tooltip 明确 E 的免伤不含塔伤；未解析的模板变量没有填成精确数字，也没有声称控制免疫。被动精确层数与完整特殊叠层规则在本次官方描述范围内仍未定。

## 两个具体案例

| 案例 | 条件成立 | 条件不成立 | 条件未知 |
| --- | --- | --- | --- |
| 潘森配合队友烬 | 潘森 W 伤害衔接烬 W 禁锢的路径有来源支持；需双方相关技能可用、目标合法/范围满足、伤害标记仍有效、目标为首先命中的英雄且可受禁锢 | 该条路径条件不满足；不排除烬由其他伤害或陷阱触发控制 | 返回信息不足，逐项列出缺失条件 |
| 潘森面对敌方莫甘娜 | W 作用时目标黑盾仍有效，则不能计入眩晕；W 物理伤害与魔法盾吸收分开 | 该黑盾反制未成立；不反推 W 必命中或必晕 | 返回信息不足，不猜本局黑盾状态 |

这些是根据同一静态版本描述组合出的项目条件推论。输入统一标为 hypothetical_scenario，输出 actual_match_observation=false、decision_input_eligible=false，不写入宏观快照。当前回放并未自动提供黑盾、精确技能可用性或烬标记状态；也没有虚构这三名英雄组成现有回放阵容。

## 实际检查

- M-01 PASS：3 份真实缓存的 URL、HTTP 状态、内容哈希、版本与英雄 ID 核验；13 处来源指针及 7 项关键原文锚点核对；离线重新构建结果相同，源文件哈希不变。真实检查的是已有官方资料，不是新对局实验。
- M-02 / M-03 PASS：6 种明确标注的合成情景经 CLI 实际运行，分别覆盖两个案例的条件满足、不满足、未知。结论保留来源与缺失条件。
- M-04 PASS：错补丁 CLI 返回 1 且未生成结果；覆盖已有文件返回 2 且原输出哈希不变。测试覆盖损坏来源、缺文件、来源版本不符、指针缺失、缓存路径逃逸、数字/字符串冒充布尔值及未知字段。
- 新增针对性测试 **27 passed in 0.56s**；随后一次完整回归 **311 passed in 1.74s**，零失败/错误/跳过。既有 284 项不是新增测试，新增测试也不等于 27 个已验证实局机制。
- 信息索引更新为 16 类，complete_collection=false；使用 `--catalog-only`，没有改写历史 RPL-004 运行清单。

独立实局交互核验、人工签署、外部复核未执行；精确客户端机制兼容未独立验证。F-03 的限定来源/条件查询已落实，深层机制、其他阵容及实际时刻适用性仍有缺口；F-04 条件完整动作实测、F-06 统一基础调用等原验收不因本轮通过。

## 文件与运行

新增：`lol_coach/mechanism_rules.py`、`lol_coach/profiles/pantheon_mechanisms_16_20_1.json`、`scripts/pantheon_mechanisms.py`、`scripts/verify_pantheon_mechanisms.py`、`tests/test_mechanism_rules.py`、任务卡和本报告。信息目录构建脚本新增一个机制条目；更新 README、CURRENT_TASK、STATUS、总结及信息清单。

本机真实产物：`data/knowledge/pantheon_mechanisms/Pantheon.mechanisms.json`、六对 `.facts.json` / `.result.json` 和 `validation.json`。这些 data 文件未公开上传；公开源码测试使用 synthetic 缓存，不依赖私人回放。恢复点为 `reports/pantheon_mechanisms_baseline/manifest.json` 与六份原文件；本轮文件哈希清单为 `reports/pantheon_mechanisms_run.json`。

在 `lol-coach` 目录查询已生成的案例，输出文件名必须尚不存在：

```powershell
.venv/Scripts/python.exe scripts/pantheon_mechanisms.py query --bundle data/knowledge/pantheon_mechanisms/Pantheon.mechanisms.json --case pantheon_jhin_followup --patch 16.20.1 --facts data/knowledge/pantheon_mechanisms/ally_met.facts.json --output data/private/pantheon-followup-example.json
```

离线重建与六情景核对，目录必须尚不存在，且需要原有三份官方缓存：

```powershell
.venv/Scripts/python.exe scripts/verify_pantheon_mechanisms.py --output-dir data/knowledge/pantheon_mechanisms-fresh
.venv/Scripts/python.exe scripts/build_information_catalog.py --catalog-only
```

修改 facts 文件中的布尔条件可以比较场景；省略或 null 表示未知，不能用 0/1 或字符串代替。此入口不把任意人工条件认证为真实对局事实。
