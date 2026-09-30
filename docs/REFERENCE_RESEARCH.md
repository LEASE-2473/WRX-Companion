# 参考项目源码研究与采用边界

核对日期：2026-10-01。先前功能施工没有先完成 Phase 3，且保留了 WRX 的语音主界面，这是执行偏差；本次补查源码并据此修正。用户最新要求明确：只暂缓 Memory，主界面以文字对话为主。原规划保留，实际状态由根目录连续性文档记录。

## 阅读范围与版本

使用 GitHub 官方仓库 API 获取提交，再读取对应版本原始源码。参考源码下载到系统临时目录用于阅读，未整体迁入项目，也未修改参考仓库。以下均为实际阅读的实现，不仅是 README：

| 项目 | 核对提交 | 实际阅读路径 |
| --- | --- | --- |
| SillyTavern | `06bde939fb1e9c4c8d8641d810f0a916b5bce127`（release） | `public/scripts/PromptManager.js`、`world-info.js`、`personas.js`、`bookmarks.js`、`extensions/tts/index.js`，以及 `public/script.js` 中相关入口 |
| Serenity / RECTDEV | `29717d71694dfbda7c4d619cb0772618df382a6c`（main） | `serenity/heartbeat/service.py`、`agent/loop.py`、`session/manager.py`、`bus/events.py`、`cli/commands.py` |
| Chatbox | `0ac6385ae1ff5bf778777826da3c5edcd55b61b8`（main） | `src/renderer/components/chat/message-token-display.ts` |

Serenity 项目入口来自 [awesome-ai-companion](https://github.com/DasterProkio/awesome-ai-companion)。独立 Vector Memory 本次不迁移、不决定新存储方案，遵从用户暂缓 Memory 的要求。

## SillyTavern：角色、注入、分支和朗读

- [PromptManager.js](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/scripts/PromptManager.js#L1081)：区分角色描述、性格、场景、Persona、World Info 和历史；`preparePrompt()` 展开角色／用户宏。采用这种职责划分，保留 WRX 已有的轻量预设编译器。本次修正 `CompanionCore.context()`：角色设定进入 `charDefinitions`，用户 Persona 进入 `userDefinitions`，顺序和开关由预设控制；真实时间独立注入。
- [world-info.js](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/scripts/world-info.js#L5265)：激活扫描与最终注入分开，输出角色前／后和深度注入内容。WRX 已有常驻、关键词、扫描深度、Role、Order 与 Marker 子集，继续复用；不迁入递归扫描、概率、复杂兼容与全量扩展体系。
- [bookmarks.js](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/scripts/bookmarks.js#L172)：`getBranchChatSnapshot()` 复制选定消息之前、含该消息的历史前缀；`createBranch()` 创建独立会话并记录来源。2.0 采用前缀快照和父会话指针，在 SQLite 事务中复制，分支消息生成新 ID。编辑／重新生成在新分支进行，原对话不覆盖；分支默认关闭 Heartbeat，避免复制出多个主动联系任务。用编号区分分支。
- [TTS 扩展](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/scripts/extensions/tts/index.js#L264)：朗读使用消息副本与独立任务队列，按角色映射音色，再单独处理朗读文本。2.0 使用每条 AI 回复上的朗读／音色按钮，复用 WRX 的 HTTP／豆包 TTS Provider。文字正文不做语音清理；角色可绑定默认 TTS，单次播放可覆盖音色。当前未迁移酒馆的 Swipe 候选与时间线扩展。

## Serenity：后台唤醒与主动联系

- [HeartbeatService](https://github.com/RECTDEV/serenity/blob/29717d71694dfbda7c4d619cb0772618df382a6c/serenity/heartbeat/service.py#L100)：后台 asyncio 循环；先通过结构化决策选择 skip/run，再执行任务和通知；活跃检查发生在模型调用前，带超时和异常恢复。2.0 采用后台生命周期调度、模型可保持沉默、调用前检查忙碌／冷却／静默／日上限，增加数据库领取和幂等请求，防止并发覆盖。
- [任务 Heartbeat 的接线](https://github.com/RECTDEV/serenity/blob/29717d71694dfbda7c4d619cb0772618df382a6c/serenity/cli/commands.py#L1213)：通过 `process_direct()` 进入 Agent，再由 `OutboundMessage` 输出。但是它的任务 Heartbeat 使用独立 `heartbeat` 会话并裁剪历史。**不采用此会话策略**：本项目要求同一个角色、同一个正式会话，不允许主动消息成为另一个 AI。
- [主动联系 `_fire_reach_out()`](https://github.com/RECTDEV/serenity/blob/29717d71694dfbda7c4d619cb0772618df382a6c/serenity/agent/loop.py#L1982)：读取离开时间与状态，让模型选择联系或保持沉默，解析后才发布。2.0 使用 `NO_ACTION`／`SEND_MESSAGE` JSON，不把模型控制 JSON 展示为聊天正文；SEND_MESSAGE 写入正常 assistant 消息，保存真实时间、usage、source，进入下次历史。NO_ACTION 仅记录请求与用量。
- [Session 管理](https://github.com/RECTDEV/serenity/blob/29717d71694dfbda7c4d619cb0772618df382a6c/serenity/session/manager.py)：服务端拥有会话并保存消息；Channel 与会话状态分离。2.0 用 SQLite 完整保留原始消息，仅在构造上下文时限制条数，暂不总结、不向量化。情绪系统、Curiosity、工具代理和自主任务不在当前授权施工范围。

## Chatbox：真实用量与估算分开

[message-token-display.ts](https://github.com/chatboxai/chatbox/blob/0ac6385ae1ff5bf778777826da3c5edcd55b61b8/src/renderer/components/chat/message-token-display.ts#L14) 将成功完成的 Provider usage 与本地估算区分，未确认的部分流不能看起来像已确认计费。2.0 在回复完成后保存供应商返回的 Input／Cache／Output；缺失显示 `—`，不由输入长度反推 Cache。搜索判断的额外模型调用单独记录，可在用量明细查看；上下文调试中的 Unicode Token 估算明确标为估算，不当作账单。

## 底座决策与验收边界

采用原计划 Option B 的渐进形式：在 WRX 后端旁建立 `CompanionCore` 与服务端会话存储，复用 Provider、Prompt 编译、世界书与语音适配器。原因是原 WRX 的浏览器全量覆盖历史和语音主界面无法支撑关页后主动消息；稳定的音色协议与配置编辑器仍有复用价值。新主界面独立使用 `chat-ui.js/css`，文字为主，录音位于辅助弹窗。

本次实现已进入离线自动检查与浏览器验收。这里的“采用”是机制与设计上的采用，没有整体复制参考项目代码。真实服务调用、云端部署、鉴权、PWA／iOS Web Push、微信尚未验收或接入；不能把本地后台调度描述为已经完成云端和手机通知。
