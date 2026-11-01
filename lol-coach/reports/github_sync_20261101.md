# GOV-003：文档整理与公开同步记录

日期：2026-11-01。用户要求清理文档并更新现有GitHub公开仓库。[任务卡](../docs/DOCUMENT_CLEANUP_SYNC_TASK.md)、[文档索引](../docs/INDEX.md)。

本次整理根/项目README、START_HERE、当前任务、能力总结、推进指南、路线与实验入口；保留整理前主要文档到docs/history，任务卡和报告仍在原路径。项目宪法原文不改。同步此前已完成而尚未推送的兵线、前卡承接、时间失效、新版容器、检查点与评测源码/测试/报告；不新增游戏能力声明。

公开边界沿用现有Git忽略规则。私人回放、录像、客户端、缓存、派生输出和完整机器记录不提交；历史文档中相应路径是本机证据位置。桌面实验TXT在项目docs中有可公开副本。

同步前基线f5ca46a94eb0a1943d1c8c10be405e986ad14971，远端main已fetch确认无额外提交。首次fetch因原配置127.0.0.1代理端口无监听失败；检查到已有本机7897监听，仅对本次Git命令指定该代理后成功，未修改全局配置或凭据。

## 实际验证

| 验收 | 状态 | 证据与范围 |
| --- | --- | --- |
| G1 当前入口一致 | PASS | 根README→INDEX→现状/接管/运行/实验；历史入口已标记并归档 |
| G2 原证据与能力边界保留 | PASS | 宪法SHA256保持e5e771e1c21a2874c9754ef759488648e0c17d456a2f46e036f0f529bfc44b5e；历史失败、语义未知与人工未签署保留 |
| G3 公开源码可独立执行离线检查 | PASS | 434个Git可见文本文件、2,504,985字节的测试快照；没有私人回放/缓存。1223 passed in 12.08s，0失败/错误/跳过；7个CLI帮助入口退出0 |
| G4 提交与远端同步 | PASS | 内容提交cc8b2c54b1d4eedb9abd0f4f28f08d2226478039普通推送成功；ls-remote核对main与本地SHA完全一致 |

G3使用已有项目虚拟环境的Python 3.13.7，在公开副本目录执行`python -m pytest -q --basetemp <新临时目录> --junitxml <本机回执路径>`，import路径已确认来自副本。没有在全新环境重新安装依赖，没有运行GitHub Actions。7个帮助入口为`-m lol_coach`及scripts下reasoning、run_reasoning_session、build_review_sequence、finalize_review_sequence、evaluate_review_sequence、probe_new_replay_compatibility。

文件清单/常见凭据格式扫描无命中；这是有限的静态检查，不代表全面安全审计。补齐摘要后449个Markdown相对文件链接已检查，23个明确的私有/机器报告目标在本机存在但不公开，其余目标均在公开清单中；不检查外网可达性和标题锚点。源码/规则/测试与测试副本按SHA256核对一致。内容提交的434文件合计2,508,616字节，相较测试快照只有4份Markdown补充结果。

首次普通`git diff --check`将CRLF的CR判作行尾空白；检查脚本又因Windows默认GBK解码输出失败。保留原行尾策略，改用UTF-8读取并显式`git -c core.whitespace=cr-at-eol diff --check`检查，未以大规模改行尾规避。修正后的工作区和暂存区检查均退出0。

## 已执行发布

GitHub仓库[2161314112dddyf-code/lol-coach](https://github.com/2161314112dddyf-code/lol-coach)仍为public、默认分支main。内容提交[cc8b2c5](https://github.com/2161314112dddyf-code/lol-coach/commit/cc8b2c54b1d4eedb9abd0f4f28f08d2226478039)包含116个变更文件。普通push从f5ca46a推进至cc8b2c5成功，随后ls-remote和本地HEAD均为上述完整SHA，工作区干净；未强推或修改全局配置。

推送后本回执与CURRENT_TASK/STATUS补记实际结果，单独作为文档提交发布；最终分支SHA回执保留在本机，不把本报告自身尚未生成的提交号提前写成已验证结果。源码与已测试快照一致，不重复运行无变化代码的完整测试。人工战术签署仍未提供。

恢复点data/private/github_sync_20261101/backup/manifest.json。执行证据包括public_manifest_before_tests.json、public_checks.json、pytest-public.xml、doc_links.json及提交/推送回执，均保留本地。公开报告只记录实际执行摘要；软件自检不替代实局或人工战术验收。
