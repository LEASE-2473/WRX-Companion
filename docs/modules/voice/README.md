# 辅助录音、STT与音频播放

更新：2026-10-04。运行目录为app/voice。

后端voice/routes.py提供STT WebSocket、请求快照和/api/process/stream；pipeline.py清理可朗读正文、分段与异常文本。语音识别后走chat/core与SQLite正式会话，不使用旧JSON整段覆盖存储。

TTS 输入将换气泡标记 `<|next_message|>` 转为换行；流式语音在长度切段前处理完整标记，并暂存未收齐的标记前缀，避免标记被切开后送给供应商。聊天存储和气泡显示仍使用原始正文。

前端static/voice/voice-ui.js负责麦克风采集、STT、语音请求、播放与录音热键；共享状态在static/shared/state.js，配置表单在static/settings/app.js。static/chat/chat-ui.js限制热键仅在语音弹窗适用，并负责逐条消息TTS。

唯一旧JSON写入实现已移出app，保留原文在docs/archive/code/legacy_store.py.txt。历史conversations.json首次导入仍由chat/store处理，不能误删其兼容迁移。

改变语音提交必须同步chat/core、provider快照、消息持久化和退出清理。移动函数需要按index.html真实顺序检查初始化绑定，tests/ui/page_boot_test.cjs覆盖加载和控件接线；麦克风、Safari和真实供应商仍待实际验收。

完整文件位置见[目录索引](../../PROJECT_STRUCTURE.md)，修改影响见[维护规则](../../MAINTENANCE.md)。
