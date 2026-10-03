# 十二情绪与冷却管家

更新：2026-10-04。运行目录为app/character。

state.py保存每会话的十二情绪和日志，处理聊天／心跳的模型更新、显式手动评估、静止周期与冷却管家；routes.py提供设置、状态和评估接口。static/character负责配置界面，聊天状态条在static/chat/chat-ui.js。

精力由脚本时钟计算，其他情绪可由模型稀疏set／add。关闭十二情绪时不注入旧版脚本模拟状态，Heartbeat仍由调度规则和业务上下文决定。用户现实情绪／活动不由系统猜测。

默认静止10分钟进入冷周期，管家默认关闭；每个静止周期最多一次，有效2小时。评估／总结／主动联系可选择对话用途Profile。管家完整提示词在app/memory/prompts/emotion_summary.md；其他运行规则仍在当前配置／代码，不因为移入memory目录就归日记任务。

数据在role_emotions、emotion_logs、emotion_summaries。日志清理由chat/maintenance负责；revision保护并发结果。实验台36变量不接入此正式十二情绪系统。

改动同步chat/core、heartbeat、providers、models、提示词、静态状态条与tests/character。

完整文件位置见[目录索引](../../PROJECT_STRUCTURE.md)，修改影响见[维护规则](../../MAINTENANCE.md)。
