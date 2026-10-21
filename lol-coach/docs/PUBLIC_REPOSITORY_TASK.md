# PUB-001：公开 GitHub 仓库

授权：2026-10-21 用户明确要求创建 GitHub 仓库、存入项目并设置公开。

输入：现有工作区源码、冻结规则、测试、任务文档与 Markdown 研究报告。
输出：公开源码 Git 仓库及 HTTPS clone 地址。

范围：仓库根目录保留三个已冻结的分包/移动依赖；项目主体保持 lol-coach/ 层级。新增根 README、Git allowlist、字节保持规则；不改历史解码器和原始素材。

GWT 验收：
- PUB-1：Given 本地混合数据工作区，When 检查 Git 跟踪清单，Then 只包含公开源码/规则/测试/文档，排除回放、媒体、客户端、缓存与私有导出。
- PUB-2：Given 仅含提交文件的干净副本，When 用现有 Python 环境运行 pytest，Then 记录真实结果；核对冻结依赖 SHA256 不变。
- PUB-3：Given 已授权的 GitHub 账户，When 创建并推送，Then API 确认 public 且远端 main 与本地 HEAD 一致。

恢复：已有文件保留原文，仅在 STATUS 顶部增加本轮记录；不删除原数据。新建 Git 历史保存公开快照。若网络或登录阻断，先保留可推送的本地提交，不能声称远端已创建。

检查：Git 暂存清单与内容扫描、干净副本 pytest、GitHub 仓库可见性和远端提交查询。开发自检，不冒充人工签署或独立复核。
