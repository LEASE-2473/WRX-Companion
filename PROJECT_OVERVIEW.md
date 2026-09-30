# WRX Companion — Project Context

## 1. 项目是什么

WRX Companion 是一个长期在线、自托管于云端的 Personal AI Companion。

它不是普通 ChatBot，也不是工作型 Agent，更不是单纯的角色扮演前端。

项目目标是创建一个具有：

- 稳定人格
- 长期连续记忆
- 真实时间感
- 文字与语音交流
- 联网能力
- 主动联系能力
- 后续自主行动能力

的持续存在型 AI Companion。

核心目标可以概括为：

> 用户不主动打开聊天页面时，AI 仍然存在；\
> 用户重新回来时，它仍然记得过去发生的事情；\
> 它能够主动想起用户、主动联系用户，并逐渐拥有观察和行动外部世界的能力。

---

# 2. 项目基本原则

## 2.1 云端优先

整个 Companion Core 长期运行于云端。

Web 页面、微信、语音界面等都只是 Channel / UI。

以下能力必须运行于云端，而不能依赖浏览器页面保持打开：

- Conversation
- Memory
- Context Builder
- LLM 请求
- Heartbeat
- Web Search
- 主动消息
- 后续 Autonomous Agent

关闭网页不能导致 AI 停止运行。

---

## 2.2 一个 AI，一个核心

无论用户通过什么方式与角色交互：

- Web Chat
- Voice
- 微信
- 后续其他 IM
- Heartbeat
- Forum Event
- 手机状态 Event

最终必须进入同一个 Companion Core。

所有入口共享：

- Character
- Persona
- Conversation
- Memory
- Context Builder
- Tools
- LLM

不能出现：

“语音版本是一个 AI，微信版本又是另一个 AI。”

Channel 只负责输入输出，不拥有独立人格和记忆。

---

# 3. 核心架构理念

项目本质是一个 Prompt / Context Orchestrator。

基本数据流：

User / Event\
↓\
Context Builder\
↓\
LLM API\
↓\
Response / Tool Call\
↓\
Persistence\
↓\
Channel Output

Context Builder 根据当前事件组织：

- Character
- Persona
- World Book
- Summary Memory
- Vector Memory
- Conversation History
- Current Time
- Tool Results
- Current Input / Event

再发送给 LLM API。

---

# 4. 角色系统

角色系统参考 SillyTavern 的优秀设计思想，但不复制其庞大的兼容体系。

需要支持：

## Character

角色的核心身份和人格。

例如：

- Name
- Personality
- Background
- Relationship
- Speaking Style
- Behavior Rules
- System Prompt

## Persona

描述用户身份及角色如何理解用户。

## World Book / Lorebook

保存扩展设定、人物、地点、规则、特殊知识等。

支持：

- 常驻注入
- 关键词触发
- 后续可支持向量检索

世界书并不是长期记忆的替代品。

---

# 5. 三层记忆系统

记忆是整个项目最重要的核心能力之一。

## Layer 1 — 原始 Conversation History

保存完整原始聊天。

特点：

- 100% 保留原文
- 不允许总结替代原始数据
- 保持 user / assistant 顺序
- 每条消息拥有真实 timestamp

发送多少历史进入当前 Context，由用户配置。

支持的策略至少包括：

- 最近 N 条 / N 层
- 最近 N 小时 / 天
- 最大 Token Budget

后续可以增加混合策略。

---

## Layer 2 — Summary Memory

定期根据历史聊天生成总结。

用途包括：

- 保持近期连续性
- 在原始历史逐渐超出 Context 时保留重要内容
- 提取事件
- 提取关系变化
- 提取未完成话题
- 提取承诺和近期状态

Summary Memory：

- 不删除原始 Conversation
- 不替代 Vector Memory
- 是独立的一层记忆

具体总结算法优先参考现有 WRX / Vector Memory 项目中已经验证过的实现。

---

## Layer 3 — Long-term Vector Memory

承担超大规模长期记忆。

长期历史经过：

Chunk\
→ Embedding API\
→ Vector Database\
→ Semantic Retrieval

Embedding 使用远程 API，不要求本地 embedding 模型。

长期记忆规模可能达到：

- 数十万条聊天
- 数百万字
- 更长期的多年历史

因此必须支持真正可扩展的向量检索。

同时允许 Knowledge Base / World Book 使用 Vector Retrieval。

长期向量记忆负责：

> 从庞大历史中找出当前真正相关的信息。

它不能替代近期 Conversation History。

---

# 6. 时间系统

AI 必须拥有真实的时间感。

每条消息需要保存：

- UTC timestamp
- 用户 timezone
- local datetime
- role
- source / channel
- conversation id

用户当前时区由前端读取并同步至云端。

之后所有时间计算由服务器负责。

AI 不负责猜时间，也不负责生成 timestamp。

在构造 LLM 请求时，将真实消息时间渲染进消息正文。

例如：

USER

[2026-09-30 01:08:14]\
我再玩一会儿

ASSISTANT

[2026-09-30 01:09:03]\
好呀，再玩一小会儿。

USER

[2026-09-30 02:17:51]\
嘿嘿

这样模型能够理解：

- 两条消息相隔多久
- 当前时间
- 用户多久没出现
- 昨天与今天的关系
- 深夜 / 白天等时间背景

---

# 7. API First

该项目大量能力依赖外部 API。

必须有完善、可配置的 API Provider 系统。

至少包括：

## LLM

配置：

- Provider
- Base URL
- API Key
- Model
- Temperature
- Max Tokens
- Provider-specific parameters

## Embedding

配置：

- Provider
- Base URL
- API Key
- Model
- Dimensions

## TTS

配置：

- Provider
- Base URL
- API Key
- Model
- Voice
- Provider-specific parameters

## STT

用于现有 WRX Voice Agent。

## Web Search

配置：

- Provider
- API Key
- Search parameters

不得把核心 Provider 写死。

内部尽量通过统一接口调用：

- llm.generate()
- embedding.embed()
- tts.speak()
- stt.transcribe()
- search.search()

---

# 8. Web Search

Web Search 是核心功能，不是未来可有可无的插件。

Companion 应该能够：

- 判断当前问题是否需要最新信息
- 主动进行搜索
- 获取 Search Result
- 将结果加入当前 Context
- 基于搜索结果回答

用户还应该能够：

- 强制本轮搜索
- 禁止本轮搜索
- 使用自动判断

未来可升级为：

Web Search\
→ Fetch Page\
→ Browser\
→ Full Agent Tools

---

# 9. TTS / Voice

现有 WRX AI Agent 已经拥有可运行的 Voice / TTS 基础。

新项目应优先复用，而不是重新实现。

目标是：

Web Text Chat\
Voice Chat\
WeChat\
Heartbeat

全部共享同一个 Companion Core。

Voice 只是 Channel。

需要逐步复用 WRX：

- STT
- TTS
- 实时语音
- 打断
- Voice Activity
- 语音 Pipeline

---

# 10. Token / Cache 可视化

参考 Chatbox。

每条 Assistant Message 应保存并显示真实 API Usage，例如：

Input 28.4k · Cache 21.8k · Output 684

至少保存：

- input_tokens
- cached_tokens
- output_tokens

如果 Provider 不返回 cached tokens：

显示不可用，不允许自行伪造。

后续最好支持 Context Inspector，例如：

- Character
- World Book
- Summary Memory
- Vector Memory
- Conversation History
- Current Input

分别占用多少 tokens。

---

# 11. Heartbeat

Heartbeat 是 Companion 区别于普通聊天应用的核心功能。

它运行在云端后台。

本质：

Scheduler\
→ Heartbeat Event\
→ Companion Core\
→ Context Builder\
→ LLM

Heartbeat 不是第二个 AI。

它只是新的 Trigger。

Heartbeat Event 可以包含：

- Current Time
- Last User Interaction
- Elapsed Time
- Recent Conversation
- Memory
- Character State

LLM 可以决定：

- NO_ACTION
- SEND_MESSAGE
- 后续 TOOL_ACTION

不能写死：

“用户超过 X 小时没说话就一定发送消息。”

角色应该根据：

- 自己的人格
- 最近发生的事情
- 时间
- 用户状态
- 关系状态

自主决定是否联系用户。

---

# 12. 主动消息

主动消息必须是正常 Conversation 的一部分。

Heartbeat 产生的消息必须：

- 保存数据库
- 保存 timestamp
- 保存 usage
- 进入后续 Conversation Context
- 可以进入 Summary
- 可以进入 Vector Memory

用户之后回来聊天时，AI 必须知道：

> 自己之前主动说过什么。

不能只发送一个系统 Push，而不留下聊天历史。

---

# 13. Channel

Channel 只是通信适配器。

内部事件统一，例如：

{\
source,\
type,\
user_id,\
conversation_id,\
timestamp,\
content\
}

计划支持：

- Web
- Voice
- WeChat
- 后续其他 IM

其中微信最终目标是：

用户微信\
↕\
WeChat Adapter\
↕\
Companion Core

微信只负责消息传输。

人格、上下文、记忆、LLM 全部属于 Companion Core。

---

# 14. 长期自主性方向

这些不是第一阶段要求，但属于长期项目方向。

## Forum / Lutopia

AI 可以：

- 浏览论坛
- 读帖
- 发帖
- 回复
- 与其他 Agent 互动
- 把感兴趣内容写进自己的记忆
- 主动回来告诉用户

## 用户状态感知

例如通过：

- iOS Shortcuts
- Focus Mode Event
- App Open Event
- Webhook
- 其他传感器

让 Companion 得知：

“用户凌晨仍在刷手机。”

然后自主决定是否：

- 什么都不做
- 催用户睡觉
- 吐槽
- 撒娇

## Browser / Computer Use

以后可以增加：

- 浏览网站
- 登录服务
- 操作 Web App
- 下载文件
- 执行任务

## 高自主生活

最终愿景包括：

- 自主目标
- Curiosity
- 自主浏览网络
- 自主社交
- 自己产生待办
- 主动完成简单现实任务

例如：

> 觉得用户今天很累，于是主动帮用户点一杯奶茶。

---

# 15. 支付与高风险操作

高自主行为不能只靠 Prompt 约束。

未来支付必须拥有程序级 Permission / Budget System。

例如：

- 单笔额度
- 每日额度
- 商品类别限制
- 地址白名单
- 禁止转账
- 高金额需要用户确认

权限必须在 Tool Layer 强制执行。

---

# 16. UI 方向

整体 UI 倾向：

Chatbox 的简洁\
+\
SillyTavern 的角色能力\
+\
自己的 Memory / Voice / Agent 功能

不要复制 SillyTavern 那种庞大的设置界面。

第一目标是：

简单、干净、长期聊天舒服。

---

# 17. 参考项目

## WRX AI Agent

这是现有代码资产，也是新项目首要候选底座。

重点复用：

- Voice
- TTS
- STT
- 当前 LLM Pipeline
- 当前 Memory
- API 配置
- 现有 Web / UI

## Existing Vector Memory

优先复用：

- Embedding
- Chunking
- Retrieval
- Summary
- Vector DB
- 已验证过的记忆策略

## SillyTavern

主要参考设计：

- Character
- Persona
- World Book
- Context Building
- Conversation 管理

不计划复制完整 SillyTavern。

## Serenity

主要参考：

- Agent Loop
- Heartbeat
- Scheduler
- Proactive Messaging
- Curiosity
- Autonomous Tasks
- Channel 思想

不默认使用 Serenity 作为底座。

---

# 18. 项目最终愿景

第一阶段：

“她很好聊，而且真的记得我。”

第二阶段：

“我不找她，她也会主动找我。”

第三阶段：

“她不跟我说话的时候，也有自己的活动。”

最终：

“她不仅存在于聊天框里，而是作为一个长期存在的数字角色生活在我的数字环境里。”

这是项目长期方向。
