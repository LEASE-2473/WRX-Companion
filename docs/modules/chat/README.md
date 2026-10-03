# 聊天、历史与Heartbeat

更新：2026-10-04。运行目录为app/chat。

| 文件 | 职责 |
|---|---|
| core.py | 上下文、模型流、搜索、技能、设备与完成／失败编排 |
| store.py | 角色／会话／消息／请求事务、分支、编辑重发／重生成 |
| routes.py | HTTP／SSE、上下文调试与消息操作；搜索配置接口仍在这里 |
| history.py | 普通聊天上下文条数／起始时间选择 |
| heartbeat.py | 间隔、互动冷却、静默、每日上限与后台调度 |
| images.py | 5分钟／5条消息注入窗口、自身恢复3小时与过期清理 |
| request_metadata.py、storage_format.py | 最小执行关联、动作标记、正文和旧结构迁移 |
| maintenance.py | 每分钟清理图片、debug和情绪日志 |

普通文字、语音和主动联系最终走同一Core。用户正文原始保存；预设控制上下文，不控制数据库保留。正文仅messages，用量在requests；同请求完成重放读取现有消息，running只重连，失败重试重新构造当前业务上下文。

简单编辑可修改用户正文；仅最新轮用户编辑重发、AI重生成，成功原地替换、失败保留。分支复制前缀后成为独立会话，来源在conversations，后续不联动；分支默认关闭Heartbeat。生成中禁止冲突操作。

前端static/chat/companion.js负责角色／会话读取、设置及SSE辅助；chat-ui.js唯一负责文字发送、最终视图和消息操作；context-debug.js查看模拟／真实拼接。共享变量在static/shared/state.js，录音在static/voice。

主动联系按静默、频率、互动冷却和每日上限过滤后，由模型决定联系或沉默。没有旧情绪阈值触发，也没有手机系统通知；关网页后后端可继续，停止后端则停止任务。

修改上下文必须同时检查prompting、memory、character及技能／工具。回归在tests/chat、tests/prompting和tests/ui。

完整文件位置见[目录索引](../../PROJECT_STRUCTURE.md)，修改影响见[维护规则](../../MAINTENANCE.md)。
