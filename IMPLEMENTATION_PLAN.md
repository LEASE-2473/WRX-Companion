# WRX Companion — Implementation Plan

## 实际进度补充（2026-10-01）

- 当前明确授权：暂缓 Memory，实施多 Character、服务端统一会话核心、Input/Cache/Output、Web Search、Heartbeat/主动消息；最新澄清要求文字聊天主界面与逐条 TTS、消息编辑／重新发送／分支。原计划的阶段验收顺序保留作参考，本次已获用户批量功能施工授权，不把 Memory 或微信作为这些功能的前提。
- Phase 0：完成 GitHub WRX 基线接管，本地无 remote，未提交／推送／修改旧工作区。
- Phase 1：完成初步审计与基线检查；真实语音/API 尚未验收。
- Phase 2 / Phase 6：总结与向量记忆按用户要求暂缓；完整原始聊天由服务端保存。
- Phase 3：已补查 SillyTavern、Serenity 和 Chatbox 的具体源码与固定提交，见 docs/REFERENCE_RESEARCH.md。承认先前绕过研究、保留语音主界面的偏差，并据此修正。
- Phase 4：采用渐进 Option B：新增 CompanionCore／SQLite，复用 WRX Provider、Prompt／世界书和语音组件，独立重做文字主界面。
- Phase 5 / 8 / 9：实现服务端文字、多角色与 Persona／绑定、多会话、时间、真实 usage 标准化、Tavily／SearXNG 与 AUTO／ON／OFF；包含幂等请求、分支编辑／重生成。
- Phase 7：复用 LLM/STT/TTS 配置，新增搜索配置与角色默认音色；Embedding 方案暂缓。
- Phase 10–12：实现后端调度、相同 Core 的 Heartbeat、NO_ACTION／SEND_MESSAGE、主动消息正式落库、冷却／静默／日上限及检查记录。
- UI：当前主界面以文字聊天为主，角色／会话侧栏、按时间顺序消息、底部输入；朗读／音色／编辑／重新生成／分支在消息操作中。麦克风为辅助入口。
- 未完成：真实 API／复刻音色／麦克风联调、云端部署与鉴权、iOS Web Push／微信。不能把本地调度与模拟测试标为完整第一／第二阶段验收通过。Phase 14–17 未开始。
- 验证和当前事实以 PROJECT_CONTEXT.md / CHANGELOG.md 为准。当前交付等待用户验收；后续不自动施工记忆、论坛、外卖等范围。

---

## 总原则

当前不是从零开发。

首先评估现有代码资产：

1. WRX AI Agent
2. Existing Vector Memory
3. Serenity
4. SillyTavern

先理解现有实现，再决定：

- 直接复用
- 小幅修改
- 抽取模块
- 参考设计重写

不要未经审查就大规模重构。

每一个阶段必须：

1. 完成实现
2. 自测
3. 给出变更说明
4. 停止
5. 等待用户验收

用户确认后再进入下一阶段。

---

# Phase 0 — 创建项目副本

复制当前 WRX AI Agent。

原 WRX 项目保持不变。

新项目作为：

WRX Companion

不要破坏已经跑通的原项目。

同时保留必要的：

CHANGELOG.md

PROJECT_CONTEXT.md

IMPLEMENTATION_PLAN.md

---

# Phase 1 — WRX Code Audit

首先完整阅读 WRX。

禁止一上来直接改代码。

需要回答：

## 当前架构

确认：

- 前端技术栈
- 后端技术栈
- LLM 调用流程
- Session / Conversation 数据结构
- Prompt 如何拼接
- Memory 如何注入
- API Settings 如何保存
- Voice Pipeline 如何工作
- TTS / STT Provider
- 数据库存储方式

绘制实际数据流：

Input\
→ Backend\
→ Context\
→ LLM\
→ Output

以及 Voice：

Mic\
→ STT\
→ Context\
→ LLM\
→ TTS\
→ Playback

---

## 功能审计

逐项检查：

- 文字 Chat
- Character
- Persona
- World Book
- 原始历史
- Summary Memory
- Vector Memory
- Embedding API
- TTS
- STT
- Voice
- API Settings
- Token Usage
- Cache Usage
- Timestamp
- 多 Conversation

标记：

✅ 已满足

🟡 可复用但需要修改

❌ 不存在

---

# Phase 2 — Vector Memory Audit

阅读现有 Vector Memory 项目。

重点确认：

- Embedding API
- Chunking
- Metadata
- Vector DB
- Retrieval
- Ranking
- Summary
- Deduplication
- Conversation Integration

禁止为了“架构统一”重写已经稳定的算法。

如果现有实现效果已经符合预期：

优先迁移/复用。

---

# Phase 3 — 参考项目研究

只研究与当前项目有明确价值的部分。

## SillyTavern

重点：

### Character / Persona

研究如何组织角色 Prompt。

### World Book

研究：

- Keyword Trigger
- Always On
- Injection

### Prompt / Context

研究它如何组织：

Character\
Memory\
World Info\
History\
Current Input

不要研究与本项目无关的大量兼容功能。

---

## Serenity

重点：

### Heartbeat

研究：

- Scheduler 如何运行
- Heartbeat 如何触发 Agent
- 如何获取当前 Context
- 如何输出 NO_ACTION / SEND_MESSAGE

### Proactive Messaging

研究主动消息如何：

- 生成
- 保存
- 进入后续 Conversation

### Agent Loop

研究未来 Tool / Autonomous 能力扩展方式。

不需要整体迁移 Serenity。

---

# Phase 4 — 底座决策

完成前三项审计后再决定：

## Option A

继续基于 WRX 扩展。

适用于：

WRX 的：

- Backend
- Conversation
- Voice
- Memory

已经足够干净。

## Option B

建立新的 Companion Core。

然后从 WRX 抽取：

- Voice
- TTS
- STT
- Memory

适用于：

WRX 当前架构过于针对 Voice Agent，不适合长期扩展。

必须明确说明选择理由。

不能因为：

“改起来省事”

就保留明显不合理的结构。

也不能因为：

“新架构更漂亮”

就重写已经稳定工作的模块。

完成底座决策后停止，等待用户确认。

---

# Phase 5 — Companion Text Core

目标：

先让文字聊天成为完整的一等功能。

需要完成：

- Web Chat
- Conversation persistence
- 多 Conversation
- Timestamp
- Timezone
- Character
- Persona
- World Book
- Context Builder

所有内容运行于云端。

---

# Phase 6 — 三层 Memory

接入：

## 原始历史

100% Conversation。

支持配置：

- N 层
- 时间范围
- Token Budget

## Summary

接入已有 Summary Memory。

## Vector

接入已有长期向量记忆。

确保：

Web Text\
Voice

读取完全相同的 Memory。

---

# Phase 7 — API Settings Center

统一整理 API 配置。

至少支持：

## LLM

Provider / Base URL / Key / Model

## Embedding

Provider / Base URL / Key / Model

## TTS

Provider / Base URL / Key / Model / Voice

## STT

Provider / Key / Model

## Web Search

Provider / Key / 参数

配置必须持久化。

Sensitive Key 不得发送至无关前端日志。

---

# Phase 8 — Token / Cache Usage

每次 LLM 请求结束后读取 Provider 返回的 Usage。

标准化为：

{\
input_tokens,\
cached_tokens,\
output_tokens\
}

保存至 Assistant Message。

聊天 UI 显示：

Input xx · Cache xx · Output xx

如果 Provider 没有返回 cache：

显示 Cache —。

后续增加：

Context Inspector。

---

# Phase 9 — Web Search

这是第一阶段的重要新增功能。

目标：

Companion 原生具备互联网搜索能力。

实现三种模式：

AUTO

由系统判断是否需要 Search。

ON

强制当前请求 Search。

OFF

禁止当前请求 Search。

基本流程：

User\
↓\
Search Decision\
↓\
Web Search API\
↓\
Search Result\
↓\
Context Builder\
↓\
LLM

第一版不需要复杂 Browser Agent。

搜索结果需要有明确的数据结构，便于以后升级：

Search\
→ Fetch\
→ Browser

完成以后停止，由用户验收第一阶段。

---

# 第一阶段验收

必须检查：

- 文字聊天
- Character
- Persona
- World Book
- Timestamp
- Conversation History
- Summary Memory
- Vector Memory
- Embedding API
- Web Search
- TTS
- Voice
- Token / Cache
- API Settings

通过以后，Companion Core v1 完成。

---

# Phase 10 — Heartbeat Infrastructure

开始第二阶段。

Heartbeat 必须运行在云端。

不要依赖前端。

实现：

Scheduler

周期：

用户可配置。

例如：

5m / 15m / 30m / 1h

Scheduler 只负责生成：

heartbeat_event

然后：

heartbeat_event\
↓\
现有 Companion Core\
↓\
现有 Context Builder\
↓\
LLM

不能建立 Heartbeat 专用 Agent。

---

# Phase 11 — Heartbeat Context

Heartbeat Context 至少包含：

- current local datetime
- last user message time
- elapsed time
- recent conversation
- summary memory
- relevant vector memory
- character
- persona

Heartbeat 请求需要明确告诉模型：

这是一次主动唤醒。

允许：

NO_ACTION

SEND_MESSAGE

未来：

TOOL_ACTION

---

# Phase 12 — Proactive Message

当 Heartbeat 返回：

SEND_MESSAGE

必须：

生成正常 Assistant Message\
↓\
写入 Conversation\
↓\
保存 timestamp\
↓\
保存 usage\
↓\
进入 Summary / Memory Pipeline\
↓\
发送 Channel

不能只做 Notification。

---

# Phase 13 — WeChat Channel

在 Companion Core 稳定后再接微信。

目标：

微信只是 Channel。

需要：

微信 Incoming Message\
↓\
统一 Event\
↓\
Companion Core

Companion Response\
↓\
WeChat Adapter\
↓\
微信

第一阶段微信只要求：

- 收文字
- 发文字
- Heartbeat 主动发文字

不要因为微信语音条阻塞整体进度。

---

# 第二阶段验收

测试：

## Heartbeat

前端关闭时仍正常运行。

## NO_ACTION

Heartbeat 可以什么都不做。

## SEND_MESSAGE

AI 可以主动产生消息。

## Persistence

主动消息进入正式 Conversation。

## Memory

下一次聊天 AI 记得自己主动联系过用户。

## WeChat

用户微信可以：

- 收到主动消息
- 回复 AI
- 回复进入同一 Conversation / Memory

以上全部通过：

Companion v2 完成。

---

# Phase 14 — iPhone Sensor Events

后续功能。

通过：

iOS Shortcuts\
→ Webhook

发送例如：

app_open\
sleep_focus\
wake\
custom_event

Companion Core 可以利用这些事件判断：

- 用户是否还醒着
- 是否应该主动提醒
- 是否应该保持沉默

---

# Phase 15 — Forum / Lutopia

实现 Forum Skill。

能力：

- 获取帖子
- 阅读
- 回复
- 发帖
- 保存感兴趣内容
- 主动告诉用户

由 Heartbeat / Autonomous Agent 调度。

---

# Phase 16 — Autonomous Agent

逐步增加：

- Goal
- Task
- Curiosity
- Tool Use
- Browser
- Computer Use

不要一次性构建完整 Agent Framework。

从真实需求逐个增加 Tool。

---

# Phase 17 — Real-world Actions

长期目标：

- 网页操作
- 购物
- 外卖
- 支付

必须首先实现：

Permission System

Budget System

Audit Log

Confirmation Policy

例如：

低风险小额任务可以自主完成。

高风险 / 高金额行为必须要求确认。

---

# 当前近期施工目标

优先完成：

WRX Audit\
↓\
底座决策\
↓\
Text Companion\
↓\
Memory\
↓\
API Settings\
↓\
Web Search\
↓\
Heartbeat\
↓\
WeChat

暂时不要优先实现：

- Lutopia
- 手机模拟器
- Computer Use
- 外卖
- 支付

这些不应该阻塞 Companion 核心完成。

---

# Codex 工作要求

每个阶段：

1. 先阅读相关代码。
2. 修改前说明准备修改哪些文件。
3. 优先复用已有稳定实现。
4. 不擅自扩大 Scope。
5. 完成后运行必要测试。
6. 更新 CHANGELOG.md。
7. 更新 IMPLEMENTATION_PLAN.md 状态。
8. 停止并等待用户验收。

未经用户确认，不自动进入下一阶段。
