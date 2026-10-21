# LoL Coach：英雄联盟赛后复盘数据基础

用于建立可核验的地图、英雄机制、行动耗时和回放状态，再组织某个时刻、某个队伍可知的信息，支持大局观复盘。当前是 Python 数据与研究工具，尚未完成完整自动复盘；没有前端或微调模型。

项目主体在 [`lol-coach/`](lol-coach/)。保留父目录中已冻结的分包器、移动解码器和字节映射，以满足原有 SHA256 依赖校验。不要单独移动 `lol-coach` 后再运行回放导出。

## 安装与离线测试

需要 Python 3.11 或更新版本；开发环境使用 Python 3.13.7。在仓库根目录运行：

```powershell
cd lol-coach
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt -r requirements-map.txt
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m lol_coach --help
```

Linux/macOS 将 `.venv/Scripts/python.exe` 替换为 `.venv/bin/python`。首次安装依赖需要网络；单元与回归测试不需要游戏、密钥或私人回放。测试通过只证明测试覆盖的代码行为，不代表全部游戏字段已经正确解码。

如果 Windows 的系统临时目录报权限错误，可加 `--basetemp=.test-tmp-public-fresh`，该目录必须尚不存在。本次公开副本按此方式实际得到 **284 passed in 1.24s**。

## 公开数据与自有回放

首次获取公开静态数据需要网络，例如：

```powershell
.venv/Scripts/python.exe -m lol_coach fetch-champion --patch 16.20.1 --champion Ivern
```

已有合法取得的、兼容构建的回放时，可指定自己的路径：

```powershell
.venv/Scripts/python.exe scripts/export_replay_ten.py --replay 'D:/Replays/example.rofl' --output data/private/example.json
```

解码规则限定研究构建 **16.20.824.8524**，不承诺其他版本兼容。部分历史批量研究脚本仍绑定原样本路径、缓存及本地第三方工具，不能在全新克隆上直接重现全部真实回放实验。历史文档中的本机路径是原执行记录，不是新机器的运行要求。

## 当前边界与证据

- [项目要求](lol-coach/docs/PROJECT_BRIEF.md)、[工程约定](lol-coach/AGENTS.md)、[项目宪法](lol-coach/docs/PROJECT_CONSTITUTION.md)。
- [当前状态](lol-coach/reports/STATUS.md)、[剩余解码矩阵](lol-coach/reports/remaining_decode_matrix.md)、[最近一轮研究报告](lol-coach/reports/remaining_decode_validation.md)。
- [时刻分析结构](lol-coach/docs/MACRO_SNAPSHOT.md)：未知保持未知；不把未来或隐藏敌方信息当成当时已知。
- 背包同步载荷存在时间语义冲突，尚不能当作当前背包；部分属性标签仍是候选；敌塔可见性不等于完整地图视野。

本仓库公开源码、版本规则、测试、任务文档和 Markdown 研究报告。原始回放、录像、客户端、第三方研究缓存、私有派生数据、历史备份和机器生成的完整报告留在本地。报告中对这些文件的引用因此不一定在 GitHub 可打开。测试包含少量用于字段回归的包片段，不包含完整回放或玩家账户资料。

公开可见不等于已经授予开源许可；当前未新增许可证，也未改变第三方资料的权利归属。
