# RPL-004B：对象身份和阵营字段

2026-10-19，用户要求继续。承接 W-01/W-02，不重做已验收的英雄移动与基础目录。输入四份现有 16.20.824.8524 回放、冻结解码器和固定版本对象配置；输出可追溯的对象名字/类型/阵营字段及其状态关联。研究推断与直接解码分开，未知对象不填类型，未核验的非英雄视野不进入决策快照。

Given 已知英雄与前五波候选及公共对象词表，When 检查创建/属性包中的重复结构，Then 只有字节关系、身份对应和独立保留样本都成立时才冻结新字段。关键不变量：错版本拒绝、源文件不修改、无未来回填、未知不是零；不能仅凭生命值赋予对象类型。只新增研究/解码模块和必要测试、报告，修改前备份 README、CURRENT_TASK、STATUS 到 reports/world_identity_baseline 并核验哈希。输出不足明确记 INSUFFICIENT_EVIDENCE，不以测试数抵扣。开发自检；人工签署、独立复核、费用和 Token 未取得。

实际切片收束到防御塔身份和生命/摧毁，前五波小兵身份仍不足，不替换其候选状态。复现命令：scripts/export_turret_state.py、scripts/verify_turret_state.py、pytest；完整参数见 reports/world_identity_validation.md。软件检查 254 项通过，真实核对及未解项见 reports/turret_state_real_validation.json。统一索引追加 turret_state，因此修改前另备份生成脚本和索引，共 5 份恢复副本；使用 --catalog-only，保留 RPL-004 历史运行清单。
