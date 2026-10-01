# 数据库字段说明

更新日期：2026-10-02。数据库：`data/companion.sqlite3`。本说明以当前实际结构为准。

## 模型只写内容，后端管理数据库

日记LLM只需返回 `{"content":"正文","tags":["事件标签"]}`。现有日记支持可选 `unresolved_hooks`，不返回时为空数组。正文必填，日记标签允许为空或多个。

ID、角色、会话、日记日期、时区、创建／修改时间、使用策略、标签ID、来源及向量都由后端处理。模型不输出SQL，不填写整张数据库表。

事件LLM输出 `{"records":[{"content":"事件总结","tags":["唯一标签"],"occurred_at":"有依据的带时区时间"}]}`；未提供事件时间时保存为空，不再用所选日期中午伪造发生时刻。

活动笔记LLM返回 `{"content":"记录正文","tags":[]}`；实际活动ID、时间、执行内容及结果由执行器提供。自主外出目前封存。

## 时间的区别

日记只保存一个业务日期 `diary_date`。`created_at`／`updated_at` 是后端自动审计时间，不是模型填表要求。日记已删除 `occurred_at`，界面仅编辑日记日期。活动和共同事件仍需要发生时间。

## 表与职责

Layer 1沿用messages原始对话表，后端选择最近N条；Layer 2为diaries；Layer 3为ai_notes；Layer 4为shared_records；Layer 5为external_memory_chunks。冷热改变使用方式，不搬移正文。

关键词用于检索，事件标签用于关联。event_tags在同一角色内保存唯一标签名称；diary_event_tags允许日记关联多个标签；shared_records仅一个event_tag_id。改名保留ID后关系不变，当前尚无标签改名UI。

## diaries

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `memory_id` | TEXT | 后端生成的稳定记忆ID |
| `character_id` | TEXT | 后端绑定所属角色 |
| `conversation_id` | TEXT | 后端绑定来源会话 |
| `scope` | TEXT | 应用设置：conversation会话私有／character角色共享 |
| `content` | TEXT | 模型生成或用户编辑的正文 |
| `keywords` | TEXT | 检索关键词JSON数组；目前用户可编辑，默认空，不要求模型填写 |
| `injection_mode` | TEXT | 应用设置：auto跟随规则／hot手动常驻／cold手动检索 |
| `created_at` | TEXT | 后端填写实际创建时间 |
| `updated_at` | TEXT | 后端填写最后修改时间 |
| `diary_date` | TEXT | 后端选择的日记日期YYYY-MM-DD，用户可改；不是生成时刻 |
| `timezone` | TEXT | 后端取来源会话时区，用于日期及转冷判断 |
| `entry_type` | TEXT | 后端类型：daily_summary；chat_entry为手动或聊天主动写入的即时日记 |
| `title` | TEXT | 可选标题，当前日记标题默认空，保留已有字段不要求模型填写 |
| `unresolved_hooks` | TEXT | 模型可返回的未结话题JSON数组，缺省为空；最多10条每条300字 |

## ai_notes

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `memory_id` | TEXT | 后端生成的稳定记忆ID |
| `character_id` | TEXT | 后端绑定所属角色 |
| `conversation_id` | TEXT | 后端绑定来源会话 |
| `scope` | TEXT | 应用设置：conversation会话私有／character角色共享 |
| `content` | TEXT | 模型生成或用户编辑的正文 |
| `keywords` | TEXT | 检索关键词JSON数组；目前用户可编辑，默认空，不要求模型填写 |
| `injection_mode` | TEXT | 应用设置：auto跟随规则／hot手动常驻／cold手动检索 |
| `occurred_at` | TEXT | 活动／事件发生时间；活动由执行器提供，事件来自材料；外部书为导入时间 |
| `created_at` | TEXT | 后端填写实际创建时间 |
| `updated_at` | TEXT | 后端填写最后修改时间 |
| `activity_id` | TEXT | 执行器提供实际活动ID |
| `activity_type` | TEXT | 活动类型，当前预留默认空 |
| `activity_content` | TEXT | 执行器提供实际活动内容 |
| `execution_result` | TEXT | 执行器提供实际结果JSON |
| `note_status` | TEXT | 后端记录pending／done／error |
| `note_error` | TEXT | 后端记录笔记生成错误 |

## shared_records

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `memory_id` | TEXT | 后端生成的稳定记忆ID |
| `character_id` | TEXT | 后端绑定所属角色 |
| `conversation_id` | TEXT | 后端绑定来源会话 |
| `scope` | TEXT | 应用设置：conversation会话私有／character角色共享 |
| `content` | TEXT | 模型生成或用户编辑的正文 |
| `keywords` | TEXT | 检索关键词JSON数组；目前用户可编辑，默认空，不要求模型填写 |
| `injection_mode` | TEXT | 应用设置：auto跟随规则／hot手动常驻／cold手动检索 |
| `occurred_at` | TEXT | 活动／事件发生时间；活动由执行器提供，事件来自材料；外部书为导入时间 |
| `created_at` | TEXT | 后端填写实际创建时间 |
| `updated_at` | TEXT | 后端填写最后修改时间 |
| `event_tag_id` | TEXT | 后端解析唯一标签名称生成／复用稳定ID |
| `record_type` | TEXT | 预留事件类别，当前默认milestone，暂无自动分类 |
| `status` | TEXT | 预留事件状态，默认unknown，暂无自动更新 |
| `due_at` | TEXT | 预留期限，默认空，暂无自动判定 |

## external_memory_chunks

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `memory_id` | TEXT | 后端生成的稳定记忆ID |
| `character_id` | TEXT | 后端绑定所属角色 |
| `conversation_id` | TEXT | 后端绑定来源会话 |
| `scope` | TEXT | 应用设置：conversation会话私有／character角色共享 |
| `content` | TEXT | 模型生成或用户编辑的正文 |
| `keywords` | TEXT | 检索关键词JSON数组；目前用户可编辑，默认空，不要求模型填写 |
| `injection_mode` | TEXT | 应用设置：auto跟随规则／hot手动常驻／cold手动检索 |
| `occurred_at` | TEXT | 活动／事件发生时间；活动由执行器提供，事件来自材料；外部书为导入时间 |
| `created_at` | TEXT | 后端填写实际创建时间 |
| `updated_at` | TEXT | 后端填写最后修改时间 |
| `title` | TEXT | 可选标题，当前日记标题默认空，保留已有字段不要求模型填写 |
| `tags` | TEXT | 外部书名称等标签JSON数组 |

## event_tags

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `tag_id` | TEXT | 后端生成的稳定标签ID |
| `character_id` | TEXT | 后端绑定所属角色 |
| `name` | TEXT | 模型／用户提供的标签名称，角色内唯一 |

## diary_event_tags

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `diary_id` | TEXT | 后端关联日记memory_id |
| `tag_id` | TEXT | 后端生成的稳定标签ID |

## memory_sources

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `memory_id` | TEXT | 后端生成的稳定记忆ID |
| `source_id` | TEXT | 后端关联原消息／活动笔记ID；来源保留，不随会话删除而清空 |

## memory_vectors

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `memory_id` | TEXT | 后端生成的稳定记忆ID |
| `vector` | TEXT | Embedding生成的向量JSON，未索引时空 |
| `model_signature` | TEXT | 后端生成Embedding地址及模型签名 |
| `index_state` | TEXT | 后端索引状态pending／ready／error；当前写入使用pending／ready |

## memory_jobs

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `id` | TEXT | 后端生成记录ID |
| `character_id` | TEXT | 后端绑定所属角色 |
| `conversation_id` | TEXT | 后端绑定来源会话 |
| `status` | TEXT | 预留事件状态，默认unknown，暂无自动更新 |
| `updated_at` | TEXT | 后端填写最后修改时间 |
| `document` | TEXT | JSON辅助信息；不是模型需要填写的整张表 |

## diary_hooks

| 字段 | 类型 | 用途／填写责任 |
|---|---|---|
| `conversation_id` | TEXT | 后端绑定来源会话 |
| `character_id` | TEXT | 后端绑定所属角色 |
| `date` | TEXT | 后端记录日记日期 |
| `scope` | TEXT | 应用设置：conversation会话私有／character角色共享 |
| `document` | TEXT | JSON辅助信息；不是模型需要填写的整张表 |

## 使用策略与索引

`injection_mode`由用户或应用选择，模型不填写。auto遵循层级策略，hot手动常驻，cold手动检索。向量成功才退出内部常驻，失败保留原使用状态；外部书只能冷，未索引时等待处理。正文编辑会清空旧向量。旧API返回的id/date/tags/mode为兼容展示字段，不额外存重复列。

## 其他应用表

characters为角色；conversations为会话；messages为原始消息；requests为模型请求与用量；settings为应用配置；regenerations／resends为重生成／重发关联；conversation_branches为分支关系；companion_states及角色状态相关表用于状态；自主外出相关表保留已封存的执行日志。本轮未修改这些模块。

## 迁移与边界

迁移在事务内执行，保留正文、来源、标签关系和向量，迁移前使用SQLite backup备份整个库。备份位于data/backups，包含私人数据，仅本地保管。主聊天已接入技能读取、关键词查记忆及新增日记／事件，详见SKILLS.md；事件自动完成及预留分类仍未实现。

## 日记生成任务范围（2026-10-02）

memory_jobs.document中的start／end为后端计算的带时区筛选边界，source_ids绑定原始消息；calls记录完整尝试、分段与合并阶段，usage累计成功请求用量。这些是任务审计字段，不新增diaries日期列，不要求LLM填写。手动即时日记与技能日记均保存chat_entry，前者选择日期／时间段，后者根据全部实际注入上下文自行选主题。

## 日记标题与管理（2026-10-02）

日记模型返回title、content、tags和可选unresolved_hooks；title是简短主题，不含日期；正文选择一至三个主线，不逐消息复述，默认三至六段、约五百至一千字；标签仅核心主题。主聊天日记技能也允许title，旧模型缺少标题时兼容为空，界面显示未命名日记。列表日期在最左侧，随后标题、类型与使用状态；展开可编辑标题／正文／标签并保存。

DELETE /api/role-memory/{character_id}/diary/{memory_id}按角色校验归属；删除将完整记忆（含标签、来源与向量）写入本地deleted_memories恢复表，再移出diaries，清理来源／索引／标签关联，重建该会话最新每日未结话题。关联生成任务标为deleted，允许同材料重生成。deleted_memories字段为memory_id、deleted_at、document，均后端填写，不参与注入或检索；暂未提供恢复UI，可从副本恢复。
