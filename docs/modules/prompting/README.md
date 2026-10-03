# 聊天预设、宏与提示词世界书

更新：2026-10-04。运行目录为app/prompting。

compiler.py按预设顺序编译角色设定、用户设定、历史、深度注入、世界书和最终trace；preset_store.py保存wrx_prompt_presets.json；lorebook_store.py保存wrx_lorebooks.json；routes.py提供管理／导入接口。界面在static/settings/app.js。

当前默认情绪规则在Chat History前；状态与服务器时间合并为D1 system，本轮真实输入／图片为D0 user。宏显式定位按预设生效。chatHistory必须启用，否则Core拒绝无法包含当前输入的请求。最终顺序以编译器与上下文调试结果为准。

提示词世界书是编译时常驻／关键词激活资料，不是系统记忆第五页导入的external_memory_chunks；两者数据、配置和检索路径不同。普通聊天预设也不是memory/prompts的独立总结任务提示词。

调试模拟不调用模型、搜索或Embedding；真实实录来自requests.debug，清除实录不影响消息正文。修改宏／深度同时检查chat/core、history、memory注入、character、tests/prompting与tests/ui。

完整文件位置见[目录索引](../../PROJECT_STRUCTURE.md)，修改影响见[维护规则](../../MAINTENANCE.md)。
