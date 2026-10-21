# 当前状态

更新时间：2026-10-11，首轮任务已实际实施。

## 环境与目录

用户工作区 `D:\1\yxlm` 已有历史 ROFL 实验，未修改这些文件；工作区不是 Git 仓库。所列交接文件最初不在工作区，来自 `C:\Users\21613\Downloads\lol_codex_handoff.zip`，解压到此前不存在的 `lol-coach/` 子目录，保留其他文件。已读用户指定的六份文件，以用户本轮请求为执行范围。

普通执行环境 Python 3.13.7（D:\py\python.exe）、pip 25.2，原环境没有 pytest；py launcher 未发现安装。提权进程 PATH 另指向 Python 3.10.9，因此使用明确路径 D:\py\python.exe 创建/修正项目 `.venv`，已确认环境为 3.13.7。固定测试依赖仅安装在项目环境。

## 已完成

- 最小 Python 包与命令行，运行依赖仅标准库；显式 --patch、--locale、--offline、--refresh。
- HTTP 超时、有限重试、请求间隔、8 MB 上限、内容哈希缓存和失败记录。HTTP 200、JSON 解析、字段校验、版本与许可状态分开。
- 实际下载官方版本列表及 Ivern 16.20.1；保存原始字节、manifest 和规范化文件。基础移速 330、攻击距离 475、生命 630、法力 450，技能描述保留原文及字段路径。
- 版本列表及响应 version 一致；目标客户端版本仍未核验，地图/模式、复杂机制、队友/对手交互为未知。
- 17 个候选入口实际 HTTP 200；其中 JSON 入口只作解析核验，其余页面只说明可访问。
- 固定提交检查 NGRID README/代码/AGPL 许可、Meraki README/MIT 许可、ROFL README/归档状态。真实失败：ROFL LICENSE 路径 HTTP 404，原响应与错误记录已保存。
- map11 16.20 与 latest 目录可读；公开刷野表格可读，标题已为 S16/2026，行级版本/条件待审核。建立空实测模板，没有伪造耗时样本。

## 修改与新增文件

- 交接包原文导入：AGENTS.md、START_HERE.txt、docs/PROJECT_BRIEF.md、FIRST_TASK.md、SOURCES.md、ROADMAP.md、source_candidates.json。
- 实现：pyproject.toml、requirements-dev.txt、lol_coach/__init__.py、__main__.py、http.py、champion.py。
- 测试与核验：tests/test_static_data.py、scripts/verify_entries.py、scripts/verify_real_sample.py。
- 文档：README.md、.gitignore、docs/clear_measurement_template.json；本 STATUS。
- 证据：data/raw/、attempts/、cache/、normalized/；reports/source_audit.md/.json、entry_evidence.json、source_verification.md、pytest.log、pytest.xml、real_sample_smoke.json。

## 实际运行与结果

以下业务命令均在 `D:\1\yxlm\lol-coach` 执行，最终环境可用 `.venv\Scripts\python.exe`；初次在线获取使用明确的 D:\py\python.exe，代码相同。

```powershell
& D:\py\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
python -m lol_coach versions
python -m lol_coach fetch-champion --patch 16.20.1 --champion Ivern
python -m lol_coach audit-sources
.\.venv\Scripts\python.exe scripts\verify_entries.py
.\.venv\Scripts\python.exe -m lol_coach --offline fetch-champion --patch 16.20.1 --champion Ivern
.\.venv\Scripts\python.exe scripts\verify_real_sample.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp-run2 --junitxml=reports\pytest.xml
```

最终离线单元测试：**12 passed in 0.77s**，零失败/跳过。全部网络响应为 synthetic，由测试内 opener 提供，测试不依赖密钥或模型。覆盖字段映射、缺失 null、无版本不通过、补丁冲突、非法字段类型、网络失败有限重试、403 不绕过、无效 JSON/非 JSON 分类、原文来源追溯、离线缓存和损坏缓存。

真实静态数据 smoke：**passed**，在先前真实联网下载的原文上离线核验 SHA256、版本列表证据、规范化完全复现、四个基础字段及五个技能描述；不是合成测试，也不是实际对局测试。结果在 real_sample_smoke.json。未单独执行在线 pytest 套件；实际网络验证来自上述 fetch/audit/verify_entries 命令。

历史失败如实记录：普通沙箱创建 `.venv` 和 data/ 遇 WinError 5，随后通过环境审批在项目内完成；初次 PATH 引用 Python310 导致 venv 启动失败，明确指定 Python 后修正。第一次 pytest 默认系统临时目录权限不足，5 passed / 7 setup errors；改用项目内专用临时目录后运行两次，分别 12 passed（0.83s、0.77s）。无自动审批拒绝、未要求用户重复确认。最终日志/XML 保存最后一次结果。

## 证据路径与缺口

真实规范化：`data/normalized/16.20.1/en_US/Ivern.json`，相邻 Ivern.manifest.json。真实英雄原始哈希：`984e6a1c8f51e7ddbf01c186c956739047f754aebdae5045a363af9a4ee4c47d`，原文路径可由 manifest 回溯，抓取时间 2026-10-11T08:26:10.629692+00:00。其他证据索引见 source_audit.json、entry_evidence.json，人工核验见 source_verification.md。

- 未取得目标补丁 AIMESH_NGRID/overlay，未计算实际路线或动作时间；需要明确目标补丁并取得对应版本资产。
- map11.bin.json 目录标注 9.2 MiB，超过首轮限额，没有下载或内部字段验证；配置不是网格。
- Meraki 样本没有整体版本字段，patchLastChanged=25.08 不证明当前补丁。复杂交互和阵容经验未验证。
- 刷野表格只是可读入口，未校准视频与游戏计时、结束状态，复用许可未确认；空模板不构成实测库。
- ROFL 仓库已归档，未发现许可证。工作区文件清单未检出原始 .rofl/.aimesh_ngrid/.ngrid_overlay；没有搜索全磁盘，也未重跑父目录历史实验。
- 未请求 Riot 需密钥接口、本地游戏接口、付费模型，未运行 NGRID/ROFL 转换、完整复盘、前端、微调或决策质量测试。

## 下一项最小任务

先锁定一份目标补丁对应的 map11 AIMESH_NGRID 及所需 overlay，记录资产来源/许可/哈希，检查二进制格式版本，再用小范围网格与实际坐标核验坐标轴、尺度和通行标记。在此之前不输出真实路径耗时。并可从公开刷野表格选择一条记录人工核验版本和计时条件，不批量抓取视频。
