# RPL-003 动态字段研究结果：尚未完成

2026-10-19，目标回放构建 16.20.824.8524。执行者/自检：Codex；独立复核和人工签署未执行。

| 用户要求 | 当前结果 | 本轮新增可接受的动态记录 |
|---|---|---:|
| 动态生命/资源 | INSUFFICIENT_EVIDENCE：没有恢复数值字段的完整读法 | 0 |
| 技能释放 | INSUFFICIENT_EVIDENCE：没有证明施法者、技能槽/名称、目标的映射 | 0 |
| 装备变化 | INSUFFICIENT_EVIDENCE：没有恢复带时间的物品/槽位变更 | 0 |
| 金币变化 | INSUFFICIENT_EVIDENCE：没有恢复当前金币/累计金币时间线 | 0 |
| 视野 | INSUFFICIENT_EVIDENCE：没有证明可见性、眼位及阵营语义 | 0 |

结算装备、结算金币、已有移动/等级/击杀/生命周期不计入这些动态项。候选包数量、可读字段名、下载成功和软件测试通过也不计入完成。RPL-003 没有通过业务验收。

## 实际执行与所得证据

1. 复查本地 RoflLens 的技能/视野代码和许可：其 profile 为 16.14.794.5912，不能直接用于本批回放。公开 rofl-parser 固定提交为 `73530424162672aa7daafe233f647cc655607880`，随附 16.15/16.16 工件；公开 registry URL 实际返回 HTTP 404。未修改版本号冒充适配。
2. 通过公开版本目录找到完整构建 `16.20.8248524`，从 Riot CDN 下载 Windows 客户端副本。文件 46,635,448 字节，SHA256 `f6fd49d6fb21c6cec23e329ca8a9a7c0809393cb950daf29ca62cf60a08455c6`；manifest `CB4BCB7E1F5C1831`。文件只作静态分析，没有启动或安装。
3. 已检查的 `interpret.js` 对该副本实际退出 1：`Could not identify the common packet registration function`。`.text` 熵约 7.99999 bit/byte，没有 `PKT_` 字串，存在 `.riot*` 封装节。没有生成可用解码器。高熵本身不是解密失败的数学证明；这里的实际失败依据是提取器返回错误、未取得注册表。
4. 下载同版本 macOS 副本 80,518,288 字节，SHA256 `f0ff0944c204e51cce8df8493f8d769c82e0b0f70bae63fe90e074c30a973671`；manifest `66B91DB25E5AD56E`。可读到 `mHP`、`mMaxHP`、`mPAR`、`mMaxPAR`、`mGold`、`mGoldTotal` 等名称；位置记录在 JSON。已定位部分 x86_64 分派及字段注册代码，但未建立与 Windows 回放的包编号、编码、布局对应关系。不能因版本号相同就借用字段偏移。`mVisionScore` 是名称线索，不是视野状态。
5. 只读扫描四份真实回放，包数分别为 570431、7812、12330、6412，原始哈希前后相同。完整回放中 `0x03df` 有 7656 个 game-stream 包，`0x02a1` 有 3165 个，`0x0484` 有 190325 个；它们仅是研究入口，**不是**已经识别的状态更新/施法/视野事件。保留原流、chunk、解压偏移、时间和载荷哈希。
6. 对 `0x03df` 的实体高字节与数组长度假设做了实际探测：原假设出现 196 个有冲突的字节映射；八个无 S-box 有限变换模板全部 UNSAT；八个有 S-box 的 SMT 求解均超时 UNKNOWN；扩展有限常量表搜索没有匹配模型。不同尝试使用的假设与范围不同，不能把它们合并成“证明协议不可解”。失败结果保留在 `data/research/replication_*.json`，没有写入正式解析器。
7. 只读访问本机 `/replay/game` 与 `/liveclientdata/gamestats`，两次均超时，没有取得状态。官方 Replay API 文档列的是播放、相机/渲染、录像接口；Live Client Data 文档面向正在进行的游戏。未证明其能提供这份保存回放的全部动态字段，因此没有要求用户重开回放并承诺接口能解决问题，也没有修改配置。

## 实际测试与复现

在 `D:/1/yxlm/lol-coach`：

```powershell
.\.venv\Scripts\python.exe scripts\audit_replay_dynamic.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-dynamic --junitxml=reports/pytest-replay-dynamic.xml
```

本轮实际结果：**150 passed in 1.16s**，零失败/错误/跳过，见 `pytest-replay-dynamic.xml`。这是已有功能的回归检查，不能证明本轮动态字段成功。新增研究脚本实际运行结果见同名研究 JSON 和 `replay_dynamic_validation.json`；没有新增冒充真实游戏验证的合成用例。

审计依赖四份原回放、既有父目录分包器和本轮已缓存文件。无需游戏运行、密钥或联网。研究求解另需已有 `../vendor/reverse-tools` 的 z3、项目 numpy；下载脚本仅在缺失资料时使用，并非日常解析入口。

## 修改范围及恢复

- 新增 `docs/REPLAY_DYNAMIC_TASK.md`。
- 新增研究脚本：`audit_replay_dynamic.py`、`research_dynamic_replication.py`、`synthesize_replication_1620.py`、`synthesize_replication_sbox.py`、`search_replication_sbox.py`、`fetch_research_mac_client.py`。
- 新增本报告、JSON、测试 XML、公开来源缓存/独立研究副本；更新 CURRENT_TASK、STATUS、README。
- `lol_coach/replay_fields.py`、`lol_coach/replay_ten.py` 和旧解码器均未修改。原回放、游戏安装、用户视频没有修改或上传。
- 文档恢复点：`reports/replay_dynamic_baseline/manifest.json`。不得整目录覆盖后续工作。

## 明确缺口与接续点

缺的是 **16.20.824.8524 Windows 回放的有效载荷解码与字段语义**。四份回放已可分包；继续增加移动实验或重复跑软件测试不能补上此缺口。

接续应优先取得或恢复该构建的 Windows 反序列化实现，或提出有新证据约束的包结构模型。macOS 资料只能作为待迁移线索，必须先用现有已知移动/等级字段证明映射关系。不要重复本报告已经失败的长度假设，也不要把猜测的 `0x03df`/`0x02a1`/`0x0484` 名称提升为事件。

现有材料没有形成需要用户补录才能判定的具体反例。本轮没有要求用户进行新游戏操作；也没有把“更多测试”设为继续开发的门槛。任务仍未完成，不声称用户接手即可自动解决这些协议问题。

来源：[Riot 官方接口说明](https://developer.riotgames.com/docs/lol#game-client-api)、[rofl-parser 固定提交](https://github.com/shyunku-libraries/rofl-parser/tree/73530424162672aa7daafe233f647cc655607880)、[公开 Windows 构建清单](https://raw.githubusercontent.com/Morilli/riot-manifests/master/LoL/KR/windows/lol-game-client/16.20.8248524.txt)、[公开 macOS 构建清单](https://raw.githubusercontent.com/Morilli/riot-manifests/master/LoL/KR/macos/lol-game-client/16.20.8248524.txt)。HTTP 状态、原始内容和哈希在 `data/research/dynamic_sources`；这不是官方协议兼容保证。
