# RPL-004 失败与更正

- CommunityDragon 初次使用 `/16.20/game/characters/...` 返回 404；实际可用入口为 `/16.20/game/data/characters/...`。两份来源报告均保留。
- 技能早期受约束匹配中 LeblancQ 与 LeblancR 争用同一字节词；未据此接受两种语义，歧义结果保留 `data/research/spell_hashes_conflict.json`。
- 将稀有词重复门槛降到两次时，随机字段与 ZyraBasicAttack 产生误配，并冲突掉此前的 VeigarDarkMatterCastLockout 字节关系。失败结果保留 `data/research/runtime_spell_hashes_rejected_low_frequency.json`；恢复三次门槛，稀有项保持未知。ZyraR/P 另用七次资源扣减和静态 mana 字段区分，属于校准证据，不算盲测。
- 首次运行 `verify_world_collection.py` 失败于退款窗口：430.5 秒起的窗口把 430.541 秒正常增加 3 金币也包括进去。按同步事件之后的窗口收窄至 430.6–431 秒，保留两次 300 / 650 的增量；这是检查窗口修正，不是更改源数据。
- 英雄 replication group32 bit10 与最终补刀不相等，补刀字段假设不接受；终值留在 world-object-research 输出。
- Map11 公共配置虽然返回 HTTP 200，但首次正文超过默认 8 MB 上限，未取得哈希，不能计作成功下载。使用有界 32 MB 重试后成功保存并解析 1,572 个顶层对象；原失败见 world_map_sources.json，重试见 world_map11_retry.json。
- 兵线参考首次对照为 4/5：第五波时间窗还包含两只 400 生命的其他候选。后续将不匹配参考生命成长的对象单列，选中的兵线候选按间隔比较为 5/5；未把两只其他对象删除或当作小兵。

这份记录不替代最终实际检查报告；软件检查与语义覆盖分别报告。
