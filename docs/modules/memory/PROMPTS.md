# 运行提示词文件与修改位置

更新：2026-10-04。运行文件全部在app/memory/prompts，迁移保留原文；这里仅存说明。Python统一从app/memory/prompt_files.py读取。

| 文件 | 用途与调用方 |
|---|---|
| diary.md | 独立当日日记，role.generate，自动／手动共用 |
| diary_instant.md | 独立指定时段日记，role.generate的chat_entry |
| diary_merge.md | 超限分段日记合并，role.summarize_diary |
| system.md | 系统四表自动／追溯填表，system.scan |
| emotion_summary.md | 冷却管家总结，character/state |
| activity.md | 实际自主活动笔记，role.record_activity；外出封存 |
| event.md | 旧事件配置兼容；生成已停用，但配置模型仍读取 |

每份文件含完整正文规则与输出格式；原文整体发给模型，维护说明不要写进运行提示词。Markdown动态读取；页面保存写回同名文件。外部编辑后先刷新表单再保存，避免旧表单覆盖新文本。运行中的任务保留已读取的文本，新任务使用最新文件。

缺失／空白明确报错，不回退到SQLite中的旧提示词。SQLite保存任务及模型配置，不保存另一份生效文本。目录移动后需同步新代码、完整app并重启后端一次。

聊天技能日记正文在app/skills/definitions/diary-write/SKILL.md，共享协议在app/skills/PROTOCOL.md；设备技能在app/tools/toy/skill/SKILL.md。它们都是运行资源，不能作为旧说明归档。

普通聊天预设和提示词世界书仍分别保存在data/wrx_prompt_presets.json与data/wrx_lorebooks.json，不属于这七份任务提示词。
