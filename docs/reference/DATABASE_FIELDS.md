# 数据库结构与字段人工审阅清单

更新：2026-10-04（Asia/Shanghai）。按当前源码、最终精简部署快照及提示词文件化后的保存逻辑重新核对。本文是存储审阅清单，说明真实字段及用途，不执行数据库迁移或删改。

默认运行库为data/companion.sqlite3，可由WRX_DB_PATH覆盖。以下表概览行数以本机新精简副本remote service prepared/20261004-system-four-tables/data/companion.sqlite3为准：28张业务表＋sqlite_sequence，197个实体列＋4个VIRTUAL派生列。该副本基于本机297条消息，与之前服务器备份的1012条消息成品是不同数据源，不代表服务器最新数据。

2026-10-04只读审查已确认本机运行库也为29表／197实体列＋4虚拟列，旧companion_states、conversation_branches、deleted_memories、system_memories均不存在；requests.result已移除。表概览行数仍为上述固定精简副本，不等于本机实时计数。本机审查时297消息／192请求，情绪日志4890条，两个会话结束debug为158／32条，清理规则尚不能视作数据已清理。

提示词保存在Markdown；settings中的历史文本不生效。SQL实体列、虚拟派生列、JSON内部键与API计算字段分别注明。API的系统记录id为表类型和sequence组合，不是数据库中的额外ID列。

## 第一部分：有哪些表、保存什么、有什么作用

共28张业务表，另有1张SQLite内部表。下面的“当前状态”说明代码现状，是否删除由人工审阅后再决定。

| 表名 | 名称 | 数据内容与作用 | 当前状态／保留策略 | 快照行数 |
|---|---|---|---|---:|
| `characters` | 角色配置 | 每个角色的名称、人物设定、用户称呼及模型／预设／世界书引用。 | 当前使用；配置主体存JSON。 | 2 |
| `conversations` | 会话目录 | 会话归属、名称、时区、Heartbeat开关与下次触发时间。 | 当前使用；不存聊天正文。 | 3 |
| `messages` | 原始聊天消息 | 每条用户／AI正文、UTC时间和来源；身份为实体列，图片与用量关联读取。 | 当前使用；聊天、日记与追溯的原始材料，长期保留。 | 297 |
| `requests` | 请求与重试记录 | 每次请求的状态、指纹、用量、最小执行信息以及测试实录。 | 当前使用；每会话保留最近20条debug，执行关联／请求去重记录保留。 | 192 |
| `regenerations` | 重新生成关联 | 一个请求需要替换的AI消息ID。 | 当前使用；重新生成写回及重试去重。 | 3 |
| `resends` | 编辑重发关联 | 一个请求需要修改的用户消息及待提交的新正文。 | 当前使用；成功后写回messages并清空暂存正文，关联保留。 | 6 |
| `images` | 图片附件 | 图片二进制、所属消息／会话、原始上传时间与来源身份。 | 普通注入5分钟／5条用户消息窗口；自身失败重试／最新用户重发可用至3小时，届时清除内容、保留标记。 | 5 |
| `memory_action_keys` | 技能写入幂等键 | 请求＋动作序号关联随机记忆身份，避免重复提交。 | 按需创建；成品保存4条已成功写入关系。 | 0 |
| `settings` | 数据库内配置 | 搜索、记忆、情绪、旧自主外出设置及迁移标记。 | 当前使用；不是所有配置都在此表，部分仍在独立JSON文件。 | 8 |
| `diaries` | 角色日记 | 第一人称日记正文、标题、日期、类型、冷热策略和未结话题。 | 当前使用；默认角色共享，正文长期保留。 | 4 |
| `system_summary` | 聊天总结 | content、tag及来源窗口，按角色共享。 | 当前使用；自增序号，热注入／冷召回。 | 1 |
| `system_people` | 人物记忆 | name、relationship、history、impression。 | 当前使用；历史追加、印象刷新。 | 2 |
| `system_items` | 物品记忆 | name、description、location。 | 当前使用；描述／位置刷新。 | 1 |
| `system_agreements` | 约定 | content及约定来源窗口。 | 当前使用；正文去重追加。 | 1 |
| `system_memory_batches` | 系统填表批次 | 角色／会话、时间窗口、批次状态与错误。 | 当前使用；追溯去重和自动填表游标依据，不存模型原始回复。 | 0 |
| `external_memory_chunks` | 外部世界书切片 | 导入文本的切片正文、标题、关键词、标签和使用策略。 | 当前使用；系统记忆第五分页，独立于自动四表填表。 | 0 |
| `event_tags` | 角色标签字典 | 角色内唯一的标签名称和稳定标签ID。 | 当前使用；日记标签仍依赖此表，名称中的event是历史命名。 | 31 |
| `diary_event_tags` | 日记与标签关系 | 每篇日记关联哪些标签。 | 当前使用；一篇日记可关联多个标签。 | 12 |
| `memory_sources` | 记忆来源关系 | 每条旧体系记忆引用的原始消息／活动来源ID。 | 当前使用；来源追溯；当前系统四表使用窗口，不写入此表。 | 284 |
| `memory_vectors` | 旧体系记忆向量 | 日记／活动笔记／旧事件／外部切片的Embedding、签名与索引状态。 | 当前使用；系统四表的向量直接存在各自BLOB列中。 | 4 |
| `memory_jobs` | 日记等生成任务 | 任务状态、生成范围、来源、记录ID、用量、原始输出和分段尝试。 | 当前使用；包含重复输出审计，暂无自动时间清理。 | 7 |
| `diary_hooks` | 最新未结话题缓存 | 某来源会话最新每日总结产生的未结话题，支持角色共享读取。 | 当前使用；不是每篇日记的历史，历史仍在diaries。 | 2 |
| `role_emotions` | 十二情绪当前状态 | 情绪数值、冷却方向、计算游标、修订号和联系动机。 | 当前使用；每会话一份状态，并非每轮日志。 | 2 |
| `emotion_logs` | 情绪诊断流水 | 时钟变化、模型更新、手动评估、管家调用及错误。 | 当前使用；每会话最多200条且不超过7天。 | 400 |
| `emotion_summaries` | 情绪管家总结批次 | 每个聊天静止周期的一次管家总结、状态、原始输出和用量。 | 当前使用；与系统聊天总结不同；兼有每周期调用去重作用。 | 20 |
| `ai_notes` | 自主活动笔记 | 活动内容、实际执行结果及AI随笔。 | 自主外出已封存；旧数据、兼容接口与生成代码保留。 | 0 |
| `shared_records` | 旧重要事件／约定 | 旧事件正文、唯一标签、事件时间、类别、状态和期限。 | 旧功能兼容；已移出角色UI与注入，旧agreement已按迁移删除。 | 0 |
| `activity_runs` | 自主外出执行记录 | 外出步骤、外部证据、活动笔记引用及执行结果。 | 自主外出已封存；保留历史读取和中断归档。 | 0 |
| `sqlite_sequence` | SQLite内部自增序列 | messages、emotion_logs及四张系统表的自增计数。 | SQLite自动维护；不属于业务表。 | 2 |

### 表之间的主要关系

- characters → conversations → messages／requests：角色、会话、正文与请求执行记录。正文仅存在messages；删除debug不会删除messages。
- regenerations／resends依赖requests；分支是独立conversations行，来源标记直接保存在该行，复制消息不会与父会话联动。
- diaries → diary_event_tags → event_tags：日记多标签关系；shared_records也引用event_tags。
- diaries／ai_notes／shared_records／external_memory_chunks的来源和向量在memory_sources／memory_vectors中。这些多类型关联多数由代码维护，没有SQLite外键。
- 系统四表各自包含对应内容与向量；system_memory_batches记录处理窗口。二者没有显式外键，范围校验／去重由代码实现。
- role_emotions是当前情绪；emotion_logs是变化流水；emotion_summaries是每次冷却周期的管家总结。旧companion_states已退役，关闭十二情绪时不再使用脚本模拟状态。

### 不在这个SQLite库里的数据

| 文件／目录 | 保存内容 |
|---|---|
| data/provider_profiles.json | STT／LLM／TTS供应商Profile、模型配置、激活ID及凭据 |
| data/wrx_prompt_presets.json | 提示词预设、模块内容和拼接顺序 |
| data/wrx_lorebooks.json | 提示词世界书配置；与external_memory_chunks导入切片是不同存储 |
| data/wrx_runtime_settings.json | 历史层数／时间过滤等运行设置 |
| data/vector_memory.json | 独立向量资料库、切片、原始资料标识、内容摘要和向量；与SQLite角色记忆向量不是同一存储 |
| data/conversations.json | 旧会话兼容文件，SQLite初始化只导入一次，原文件保留 |
| data/presets.json、prompts.json、prompt_presets.json | 历史可能留下的文件；当前代码已无这三项路径常量／读取者，不属于必需部署配置 |
| app/memory/prompts/*.md | 独立日记、即时日记、合并、封存活动／事件、系统填表及情绪管家提示词，共7份 |
| app/skills/definitions/*/SKILL.md、app/skills/PROTOCOL.md | 技能说明／提示词与共享调用协议；网页目前只读，聊天写入仅开放日记，event-write停用 |
| data/toy/ | Toy工具自己的运行记录，不属于此SQLite表清单 |

### 当前体积和重复内容的对应位置

最初部署快照702,234,624字节，上一阶段清理后20,561,920字节；本轮独立精简副本2,244,608字节，缩小约89.08%。原备份不变；历史图片已过3小时，10份附件内容被清除但标记保留。前轮已清理的512条实录不能恢复，本轮保留2条独立debug，4条已成功技能写入关系提取至memory_action_keys。

requests.result已物理删除。仍存在的测试／任务审计内容副本包括独立debug列中的llm_messages与prompt_trace.final_messages、memory_jobs.document.raw／calls[].output，以及分支复制的消息与独立附件关联；分支附件沿用上传时间并受相同清理规则。这些位置的用途在第二部分分别列明。

## 第二部分：每张表的字段

“非空”指显式SQL NOT NULL；“主键序位”大于0表示主键，联合主键按1、2排序。TEXT主键在目前普通SQLite表中没有全部额外声明NOT NULL，不能把主键标签等同于显式非空标记。默认值显示的是SQL默认值；“无”表示调用方填写，可能另有应用层默认值。空字符串与NULL不同。

当前普通持久化日期时间为UTC秒级`YYYY-MM-DDTHH:MM:SSZ`；旧库／导入数据可能仍有带偏移或微秒的ISO字符串。业务日期`YYYY-MM-DD`含义不变，旧消息时间未知时允许空字符串；确切用途逐列说明。JSON对象／数组也是TEXT，不是SQLite独立JSON类型。

### 1. `characters` — 角色配置

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `id` | TEXT | 否 | 1 | 无 | 角色ID；document.id中也重复保存。 |
| `document` | TEXT | 是 | 0 | 无 | JSON主体；内部字段见本表下方说明。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

document内部（Character；全部当前模型字段）：

| JSON字段 | 内容与用途 |
|---|---|
| id | 角色ID，与外层重复 |
| name | 角色显示名称 |
| personality | 性格 |
| background | 背景经历 |
| relationship | 与用户的关系设定 |
| speaking_style | 说话风格 |
| system_prompt | 角色系统提示词 |
| persona | 人物描述／人设内容 |
| user_name | 角色称呼用户的名称 |
| preset_id | 提示词预设ID，可空，引用独立JSON配置 |
| lorebook_id | 提示词世界书ID，可空，引用独立JSON配置 |
| llm_profile_id | 聊天模型Profile ID，可空 |
| tts_profile_id | TTS Profile ID，可空 |

### 2. `conversations` — 会话目录

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `id` | TEXT | 否 | 1 | 无 | 稳定记录ID；由后端生成或使用调用方请求ID，具体规则见各表说明。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `name` | TEXT | 是 | 0 | 无 | 用户命名或后端生成的会话名称。 |
| `created_at` | TEXT | 是 | 0 | 无 | 后端创建时间；用于排序／审计，不是业务事件发生时间。 |
| `updated_at` | TEXT | 是 | 0 | 无 | 最近会话活动时间；会话列表排序依据。 |
| `timezone` | TEXT | 是 | 0 | 无 | IANA时区；显示时间、安静时段、日期筛选依据。 |
| `heartbeat` | TEXT | 是 | 0 | 无 | HeartbeatSettings JSON配置，详见下方。 |
| `next_heartbeat_at` | TEXT | 否 | 0 | 无 | 下次Heartbeat检查／触发时间；允许NULL。 |
| `parent_conversation_id` | TEXT | 否 | 0 | 无 | 分支的来源会话ID；应用层关联，无SQLite外键。普通新会话为NULL。 |
| `branch_message_id` | TEXT | 否 | 0 | 无 | 原会话中选择的分支点消息ID；只作来源标记，无SQLite外键。 |

SQLite外键：`character_id` → `characters.id`；删除动作 `NO ACTION`。

分支复制选中消息前缀，生成新的会话及消息身份；原会话继续保留，之后两边编辑／聊天各自独立。删除父会话不会删除分支，只清除分支的父会话／分支点标记。附件仍继承原上传时间；记忆材料可用消息origin_id识别复制来源。

heartbeat内部：enabled开关、interval_minutes检查间隔、cooldown_minutes发消息冷却、max_messages_per_day每日上限、quiet_enabled安静时段开关、quiet_start起始小时、quiet_end结束小时。均为会话级配置，不是额外SQLite列。

### 3. `messages` — 原始聊天消息

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `sequence` | INTEGER | 否 | 1 | 无 | 保留原自增序号；会话历史排序依据。 |
| `id` | TEXT | 是 | 0 | 无 | 唯一消息身份，正文不保存副本。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属会话。 |
| `request_id` | TEXT | 否 | 0 | 无 | 请求关联，允许NULL；API用此关联读取用量。 |
| `role` | TEXT | 是 | 0 | 无 | user／assistant；正文不保存副本。 |
| `document` | TEXT | 是 | 0 | 无 | 精简正文JSON。 |
| `origin_id` | TEXT | 否 | 0 | 无 | 首次创建的消息身份；分支副本沿用，防秒级时间下误去重。应用层关系，不建外键，原会话删除后仍可保留来源标识。 |

SQLite外键：conversation_id → conversations.id，NO ACTION。唯一约束(id)、(conversation_id,request_id,role)；索引(conversation_id,sequence)。

正文仅保存content、timestamp、source，以及有实际引用时的sources；content为空时可代表纯图片，timestamp为空表示旧记录时间未知，二者属于必要信息。时间为秒级UTC `YYYY-MM-DDTHH:MM:SSZ`。不保存id、request_id、role、timezone、local_datetime、usage或Base64图片；无意义空键／数组／NULL省略。

API从实体列恢复消息身份、角色和请求关联；用量从requests读取，分支副本可通过origin_id追到原请求。图片通过images读取，image_count为动态附件数量，内容删除后UI显示“图片已过期”；以上均不在正文存副本。兼容Python字段timezone／local_datetime不序列化，显示和本地日期筛选使用会话时区。

### 4. `requests` — 请求与重试记录

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `id` | TEXT | 否 | 1 | 无 | 调用方请求ID；同ID重试用于结果重放／去重。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `fingerprint` | BLOB | 是 | 0 | 无 | 对会话、输入、时区、来源、搜索模式、附件及重发／重生成目标等计算的完整SHA256（32字节）；防同ID不同内容，不截断。 |
| `source` | TEXT | 是 | 0 | 无 | 请求来源，如web／heartbeat。 |
| `status` | TEXT | 是 | 0 | 无 | running／complete／error；恢复时失败也用error。 |
| `started_at` | TEXT | 是 | 0 | 无 | 后端任务／请求开始时间。 |
| `finished_at` | TEXT | 否 | 0 | 无 | 后端完成／失败结束时间；未完成时可空。 |
| `error` | TEXT | 否 | 0 | 无 | 错误文本；不是聊天正文。 |
| `usage` | TEXT | 否 | 0 | 无 | 主模型TokenUsage JSON；无值可NULL。 |
| `extra_usage` | TEXT | 否 | 0 | 无 | 辅助模型调用JSON数组，如搜索决策、技能及设备调用；与主usage分开。 |
| `debug` | TEXT | 否 | 0 | 无 | 独立实录JSON；每会话最近20条有实录且已结束请求，运行中不清理；图片只有说明／引用。 |
| `attempt` | INTEGER | 是 | 0 | `1` | 每次重试递增版本，防同秒重试的旧任务迟到回写。 |
| `fingerprint_version` | INTEGER | 是 | 0 | `1` | 未经重派生的历史指纹为1；新请求及21条经核验重派生的历史操作显式写2，重生成／重发用稳定附件来源身份参与摘要，过期不改变指纹。 |
| `debug_order` | INTEGER | 否 | 0 | 无 | 完成实录的递增顺序；同秒或旧ID重试也能正确保留最近20条。 |
| `execution` | TEXT | 是 | 0 | `'{}'` | 最小执行元数据；不含正文、用量、完整上下文或工具结果快照。 |


SQLite外键：`conversation_id` → `conversations.id`；删除动作 `NO ACTION`。

其他约束／索引：索引 `(conversation_id,status)`。

execution内部（不同请求可能缺项）：

| JSON字段 | 内容与用途 |
|---|---|
| reply_message_id | 已完成回复的实体ID；重放通过messages读取当前正文 |
| action | Heartbeat等动作判定，用于状态展示与去重 |
| emotion_change | 本轮情绪应用状态及变化，用于当前变化展示 |
| latency_seconds | 请求耗时 |
| device_effect | claimed／accepted及动作名、尝试号；迁移中无法核实的历史失败记录用legacy_unverified。失败重试不重复执行已领取或无法确认的设备动作 |
| autonomy | 封存外出的最小状态／run_id／错误；不搬迁完整执行结果 |

旧result在删除前只提取以上必要信息及memory_action_keys。完成重放、失败重新拼装及断线重连均不使用debug；没有永久上下文快照。用量仅在usage／extra_usage保存。resends.content仅保存待提交编辑内容，成功后清空。

独立debug列内部（仅供测试，最新20条，图片仅说明）：

| JSON路径 | 内容与用途 |
|---|---|
| llm_messages | 实际发送上下文数组：每段role、content与图片说明；不保存Base64副本，包含人设、预设、记忆和历史 |
| llm_raw | 模型原始输出；可含清洗前协议和工具内容 |
| normalized_reply | 处理后的回复正文副本 |
| tts_input | 处理后的TTS输入文本副本 |
| search | 搜索调试信息，不作为重试输入 |
| prompt_trace | 拼接审计：预设／世界书／历史选择／记忆召回／技能／状态等 |
| prompt_trace.final_messages | 最终上下文的另一份副本；与llm_messages高度重复 |
| prompt_trace.history | 历史层数／时间筛选及所选消息ID等 |
| prompt_trace.role_memory、vector_memory | 注入和召回的记忆ID、分数等 |
| prompt_trace.role_emotion | 当前十二情绪状态；旧debug可能仍有companion_state历史字段，当前代码不再生成或读取它作为输入 |
| prompt_trace.skills | 技能调用与返回结果；格式随调用变化 |
| prompt_trace其他项 | schema_version、preset、lorebook、prompt_order、macro_expansions、markers、lorebook_activation、in_chat、disabled_or_unsent、prompt_tokens等 |

整个debug一起过期，运行中请求不清理。error请求可能只存latency_seconds与部分debug。usage内部为input_tokens／cached_tokens／output_tokens；extra_usage为数组，项通常含purpose和usage，具体调用可能增加辅助信息。

### 5. `regenerations` — 重新生成关联

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `request_id` | TEXT | 否 | 1 | 无 | 对应请求ID。 |
| `message_id` | TEXT | 是 | 0 | 无 | 被替换／被编辑的原消息ID；仅应用层关联messages.id，无SQLite消息外键。 |

SQLite外键：`request_id` → `requests.id`；删除动作 `NO ACTION`。

### 6. `resends` — 编辑重发关联

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `request_id` | TEXT | 否 | 1 | 无 | 对应请求ID。 |
| `message_id` | TEXT | 是 | 0 | 无 | 被替换／被编辑的原消息ID；仅应用层关联messages.id，无SQLite消息外键。 |
| `content` | TEXT | 是 | 0 | 无 | 待提交的新正文；运行中／失败时保留以便完成或重试，成功写回messages后置为空字符串，不长期留正文副本。 |

SQLite外键：`request_id` → `requests.id`；删除动作 `NO ACTION`。

全部用户消息可单纯编辑保存，不调用模型、不改写后续回复；仅最新用户消息可用新请求ID重发，仅最新AI回复可用新请求ID重生成，且其后不能已有更新的用户消息。上下文不含待替换回复；成功替换、失败保留，生成中拒绝冲突修改。regenerations／resends为执行关联，不是另一份完整会话。

### 7. `settings` — 数据库内配置

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `key` | TEXT | 否 | 1 | 无 | 配置／迁移标记名称；详见下方键列表。 |
| `document` | TEXT | 是 | 0 | 无 | 按key保存JSON对象、映射或布尔值；可包含敏感配置。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

document按key解释；默认配置未保存时也可能没有对应行：

| key | document内容 | 当前作用 |
|---|---|---|
| legacy_imported | JSON布尔值 | 旧JSON会话导入完成标记，防重复导入 |
| role_memory_character_v2 | JSON布尔值 | 角色共享及旧约定删除的一次性迁移标记 |
| role_memory | 角色记忆设置对象 | 日记策略、模型、向量和自动日记设置；当前提示词独立存Markdown |
| system_memory | 系统记忆设置对象 | 自动填表开关、窗口、批次间隔、绑定与模型；prompt独立存Markdown |
| system_memory_auto_starts | 绑定ID→时间的映射 | 自动填表首次起点；进度还参考system_memory_batches |
| role_emotion_settings | 十二情绪设置对象 | 冷却、模型、联系动机及chat_prompt／assessment_prompt；summary_prompt独立存Markdown |
| search | 搜索设置对象，可含api_key | 搜索供应商、请求格式、认证和结果解析 |
| autonomy | 已封存自主外出设置对象，可含凭据 | 历史配置兼容，封存时关闭自动运行 |
| storage_identity_aliases | 新身份→旧身份映射 | 仅供迁移后旧请求完整SHA256比较；不是角色正文或永久上下文 |
| storage_legacy_requests | 仍需旧身份指纹比较的请求ID数组 | 与上述逆映射一起保持旧请求去重语义 |

成品快照实际有8个key：legacy_imported、role_memory_character_v2、role_memory、role_emotion_settings、search、autonomy、storage_identity_aliases、storage_legacy_requests。system_memory及system_memory_auto_starts在此快照尚无行，未保存时使用代码默认值。

配置对象字段名清单见下方；字典子键可变，不是SQLite固定列。引用Profile时部分旧内嵌密钥会清空，但旧配置仍可能有密钥。

| 配置JSON路径 | 当前数据库保存的字段名（API提示词字段另列） |
|---|---|
| `role_memory` | `policies`、`presets`、`vector`、`profiles_migrated`、`embedding_profile_id`、`rerank_profile_id`、`hot_token_limit`、`diary_enabled`、`diary_hour`、`timezone` |
| `role_memory.policies.<kind>` | `enabled`、`scope`、`default_mode`、`auto_cold_days` |
| `role_memory.presets.<kind>` | `history_limit`、`include_notes`、`include_events`、`llm`、`llm_profile_id`、`follow_conversation`、`temperature` |
| `role_memory.presets.<kind>.llm` | `id`、`name`、`provider_type`、`base_url`、`api_key`、`model`、`purpose` |
| `role_memory.vector` | `enabled`、`api_url`、`api_key`、`model`、`threshold`、`max_results`、`context_depth`、`separator`、`rerank_enabled`、`rerank_url`、`rerank_key`、`rerank_model` |
| `system_memory` | `enabled`、`interval_minutes`、`delay_seconds`、`scope`、`llm_profile_id` |
| `role_emotion_settings` | `enabled`、`idle_minutes`、`summary_enabled`、`llm_profile_id`、`contact_llm_profile_id`、`history_limit`、`chat_prompt`、`assessment_prompt`、`state_hours`、`step_per_hour`、`recovery_per_hour`、`longing_per_hour`、`motive_threshold`、`no_action_minutes`、`contact_weight`、`worry_weight`、`retreat_weight`、`allow_silence` |
| `search` | `enabled`、`provider`、`endpoint`、`api_key`、`max_results`、`search_depth`、`request_method`、`request_template`、`auth_header`、`auth_prefix`、`results_path`、`title_path`、`url_path`、`content_path`、`extra_body` |
| `autonomy` | `enabled`、`provider`、`endpoint`、`api_key`、`destinations`、`llm_profile_id`、`public_personality`、`interests`、`automatic`、`allow_replies`、`proxy_url`、`allow_fake_ip`、`conversation_ids`、`interval_minutes`、`daily_limit`、`max_steps`、`output_budget`、`quiet_start`、`quiet_end` |
| `autonomy.destinations[]` | `id`、`name`、`provider`、`endpoint`、`api_key`、`mcp_url`、`mcp_url_set` |

参数意义：policies为各记忆类型开关／绑定／冷热策略；presets持久化生成参数与LLM设置，提示词从文件注入API；vector为Embedding和Rerank设置；hot_token_limit为常驻预算；diary_enabled／diary_hour／timezone为自动日记计划。system_memory的interval_minutes是总结窗口，delay_seconds是批次请求间隔；与requests.debug的20条数量保存策略互不关联。role_emotion_settings包含冷却、模型、演算速度、联系权重及聊天／手动评估文本；情绪管家文本从文件读取。search请求／结果映射字段由所选供应商决定；autonomy及其目的地属于封存配置。

提示词字段与保存位置：

| API／历史JSON字段 | 当前读取与保存位置 | 成品快照及兼容情况 |
|---|---|---|
| role_memory.presets.diary.prompt | app/memory/prompts/diary.md | 成品仍有旧文本，当前读取以文件为准；保存时删除数据库prompt／requirements／instant_prompt键 |
| role_memory.presets.activity.prompt、event.prompt | app/memory/prompts/activity.md、event.md | 封存类型仍保留配置／文件；不等于聊天技能允许写事件 |
| role_memory.presets.diary.instant_prompt | app/memory/prompts/diary_instant.md | 独立即时日记生成文本；当前API仍返回，数据库不保存 |
| 日记合并提示词（非settings字段） | app/memory/prompts/diary_merge.md | 分段合并阶段读取，无SQL副本 |
| system_memory.prompt | app/memory/prompts/system.md | API包含prompt，保存时写文件并从数据库对象排除prompt |
| role_emotion_settings.summary_prompt | app/memory/prompts/emotion_summary.md | 成品仍有旧文本；当前API从文件补齐，保存时排除该键 |
| role_emotion_settings.chat_prompt、assessment_prompt | settings.document | 仍由EmotionSettings管理；默认未写入的字段不代表不存在 |
| 聊天主动日记技能／活动反思技能 | app/skills/definitions/diary-write/SKILL.md、reflect/SKILL.md | 与独立生成的Markdown不同；reflect封存，技能网页无保存接口 |

当前模型已无requirements字段；旧成品的requirements是历史残留，不是新增SQL列或当前生效提示词。提示词文件化本身不改变SQL实体列；当前四表结构为197实体列＋4虚拟列。部署需携带当前app/memory/prompts和app/skills文件，不能仅复制SQLite后假设这些文本仍由数据库提供。

### 8. `diaries` — 角色日记

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `memory_id` | TEXT | 否 | 1 | 无 | 稳定记忆ID；应用层关联来源／向量／标签，不随正文编辑改变。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `scope` | TEXT | 是 | 0 | 无 | 绑定范围：character角色共享，conversation会话私有；当前默认角色共享。 |
| `content` | TEXT | 是 | 0 | 无 | 记录正文；由用户、模型或导入内容产生。 |
| `keywords` | TEXT | 是 | 0 | `'[]'` | 检索关键词JSON字符串数组；区别于标签，默认空数组。 |
| `injection_mode` | TEXT | 是 | 0 | 无 | 使用策略：auto按规则，hot常驻，cold检索；不是单独迁移到另一张表。 |
| `created_at` | TEXT | 是 | 0 | 无 | 后端创建时间；用于排序／审计，不是业务事件发生时间。 |
| `updated_at` | TEXT | 是 | 0 | 无 | 后端最近写入／修改时间；用于排序、过期判断或并发校验。 |
| `diary_date` | TEXT | 否 | 0 | 无 | 业务日记日期YYYY-MM-DD；允许空的历史兼容字段。 |
| `timezone` | TEXT | 是 | 0 | `'Asia/Shanghai'` | 日记所属时区；用于日期与转冷判断。 |
| `entry_type` | TEXT | 是 | 0 | `'daily_summary'` | daily_summary每日总结；chat_entry即时／选时间段／聊天技能日记。 |
| `title` | TEXT | 是 | 0 | `''` | 标题；日记为主题，外部切片为导入标题。 |
| `unresolved_hooks` | TEXT | 是 | 0 | `'[]'` | 未结话题JSON字符串数组；可由模型生成，缺省空数组。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

其他约束／索引：索引 `(character_id,conversation_id)`。

CHECK约束：scope仅character／conversation；injection_mode仅auto／hot／cold。

正文是角色第一人称相处日记；独立生成取原始显示时间范围，不经过应用上下文过滤。tags不直接存日记列，通过event_tags＋diary_event_tags关联；来源在memory_sources，向量在memory_vectors。diary_date是业务日期，created_at／updated_at是写入审计时间。当前日记没有occurred_at列。

### 9. 系统记忆四张物理表

#### `system_summary`

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `sequence` | INTEGER | 否 | 1 | 无 | 唯一持久行身份，自增整数；无第二个系统记忆ID。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色，共享绑定；无scope字段。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 首次来源会话；删除来源会话不删除记忆。 |
| `range_start` | TEXT | 是 | 0 | 无 | 来源材料窗口开始，后台填写。 |
| `range_end` | TEXT | 是 | 0 | 无 | 来源材料窗口结束，后台填写。 |
| `content` | TEXT | 是 | 0 | '' | 总结／约定概述。 |
| `tag` | TEXT | 是 | 0 | '' | 聊天总结标签文本。 |
| `mode` | TEXT | 是 | 0 | 'hot' | hot直接注入／cold检索，无auto。 |
| `vector` | BLOB | 否 | 0 | 无 | Float64小端BLOB数组；未就绪NULL，不使用JSON正文或切片表。 |
| `vector_signature` | TEXT | 是 | 0 | '' | Embedding配置签名，防止新模型读取旧向量。 |
| `vectorized` | INTEGER | 否 | 0 | 无 | VIRTUAL派生列：vector IS NOT NULL，0／1；不重复保存状态。 |

#### `system_people`

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `sequence` | INTEGER | 否 | 1 | 无 | 唯一持久行身份，自增整数；无第二个系统记忆ID。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色，共享绑定；无scope字段。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 首次来源会话；删除来源会话不删除记忆。 |
| `range_start` | TEXT | 是 | 0 | 无 | 来源材料窗口开始，后台填写。 |
| `range_end` | TEXT | 是 | 0 | 无 | 来源材料窗口结束，后台填写。 |
| `name` | TEXT | 是 | 0 | '' | 人物姓名／物品名称。 |
| `relationship` | TEXT | 是 | 0 | '' | 人物与用户关系，刷新。 |
| `history` | TEXT | 是 | 0 | '' | 历史事件文本，增量追加。 |
| `impression` | TEXT | 是 | 0 | '' | 用户印象，刷新。 |
| `mode` | TEXT | 是 | 0 | 'hot' | hot直接注入／cold检索，无auto。 |
| `vector` | BLOB | 否 | 0 | 无 | Float64小端BLOB数组；未就绪NULL，不使用JSON正文或切片表。 |
| `vector_signature` | TEXT | 是 | 0 | '' | Embedding配置签名，防止新模型读取旧向量。 |
| `vectorized` | INTEGER | 否 | 0 | 无 | VIRTUAL派生列：vector IS NOT NULL，0／1；不重复保存状态。 |

#### `system_items`

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `sequence` | INTEGER | 否 | 1 | 无 | 唯一持久行身份，自增整数；无第二个系统记忆ID。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色，共享绑定；无scope字段。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 首次来源会话；删除来源会话不删除记忆。 |
| `range_start` | TEXT | 是 | 0 | 无 | 来源材料窗口开始，后台填写。 |
| `range_end` | TEXT | 是 | 0 | 无 | 来源材料窗口结束，后台填写。 |
| `name` | TEXT | 是 | 0 | '' | 人物姓名／物品名称。 |
| `description` | TEXT | 是 | 0 | '' | 物品描述，刷新。 |
| `location` | TEXT | 是 | 0 | '' | 物品位置，刷新。 |
| `mode` | TEXT | 是 | 0 | 'hot' | hot直接注入／cold检索，无auto。 |
| `vector` | BLOB | 否 | 0 | 无 | Float64小端BLOB数组；未就绪NULL，不使用JSON正文或切片表。 |
| `vector_signature` | TEXT | 是 | 0 | '' | Embedding配置签名，防止新模型读取旧向量。 |
| `vectorized` | INTEGER | 否 | 0 | 无 | VIRTUAL派生列：vector IS NOT NULL，0／1；不重复保存状态。 |

#### `system_agreements`

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `sequence` | INTEGER | 否 | 1 | 无 | 唯一持久行身份，自增整数；无第二个系统记忆ID。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色，共享绑定；无scope字段。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 首次来源会话；删除来源会话不删除记忆。 |
| `range_start` | TEXT | 是 | 0 | 无 | 来源材料窗口开始，后台填写。 |
| `range_end` | TEXT | 是 | 0 | 无 | 来源材料窗口结束，后台填写。 |
| `content` | TEXT | 是 | 0 | '' | 总结／约定概述。 |
| `mode` | TEXT | 是 | 0 | 'hot' | hot直接注入／cold检索，无auto。 |
| `vector` | BLOB | 否 | 0 | 无 | Float64小端BLOB数组；未就绪NULL，不使用JSON正文或切片表。 |
| `vector_signature` | TEXT | 是 | 0 | '' | Embedding配置签名，防止新模型读取旧向量。 |
| `vectorized` | INTEGER | 否 | 0 | 无 | VIRTUAL派生列：vector IS NOT NULL，0／1；不重复保存状态。 |

四表无随机id、document、kind、scope、生成／更新时间及其他表的无关业务列；索引各为(character_id,range_start)，mode检查hot／cold，vector检查BLOB非空且字节数为8的倍数。角色与来源会话由应用校验，未添加会话级联删除外键。人物／物品刷新保留首次来源窗口，旧会话私有系统记录迁为角色共享。

SQL的vectorized只推导向量是否存在；API／网页还检查当前模型签名是否一致。冷记录按整行直接加入向量候选，不存在“没切片所以没进候选”的中间环节。转冷失败保留原状态，编辑清除向量并转热；向量停用／签名变更导致不可用时回到直接注入。最终召回仍受阈值、Top N与Rerank影响。

接口id如person:1是类型＋序号的计算定位值，不持久化；不同表的序号重复不会串表。system_memory_batches的摘要任务键仍用于批次幂等，与记忆行身份不同。

### 10. `system_memory_batches` — 系统填表批次

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `id` | TEXT | 否 | 1 | 无 | 绑定、窗口起止及消息摘要组合的SHA256去重键。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `range_start` | TEXT | 是 | 0 | 无 | 本批原始消息筛选起点。 |
| `range_end` | TEXT | 是 | 0 | 无 | 本批筛选终点，同时作为自动填表推进依据。 |
| `status` | TEXT | 是 | 0 | 无 | running／done／empty／error；done和empty均计入已处理范围。 |
| `error` | TEXT | 是 | 0 | `''` | 批次错误文本；代码截取至1000字符。 |
| `scope` | TEXT | 是 | 0 | `'character'` | 绑定范围：character角色共享，conversation会话私有；当前默认角色共享。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

记录已处理窗口，而不是每次完整LLM请求。完成／空窗口用于去重和下次自动填表起点；running在应用恢复时标为error。当前手动追溯总进度还在进程内存，不在本表增加进度JSON；失败错误有保存。

### 11. `external_memory_chunks` — 外部世界书切片

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `memory_id` | TEXT | 否 | 1 | 无 | 稳定记忆ID；应用层关联来源／向量／标签，不随正文编辑改变。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `scope` | TEXT | 是 | 0 | 无 | 绑定范围：character角色共享，conversation会话私有；当前默认角色共享。 |
| `content` | TEXT | 是 | 0 | 无 | 记录正文；由用户、模型或导入内容产生。 |
| `keywords` | TEXT | 是 | 0 | `'[]'` | 检索关键词JSON字符串数组；区别于标签，默认空数组。 |
| `injection_mode` | TEXT | 是 | 0 | 无 | 使用策略：auto按规则，hot常驻，cold检索；不是单独迁移到另一张表。 |
| `occurred_at` | TEXT | 否 | 0 | 无 | 导入时记录的时间；历史命名保留，并非书中事件发生时间。 |
| `created_at` | TEXT | 是 | 0 | 无 | 后端创建时间；用于排序／审计，不是业务事件发生时间。 |
| `updated_at` | TEXT | 是 | 0 | 无 | 后端最近写入／修改时间；用于排序、过期判断或并发校验。 |
| `title` | TEXT | 是 | 0 | `''` | 标题；日记为主题，外部切片为导入标题。 |
| `tags` | TEXT | 是 | 0 | `'[]'` | 外部书名称等标签JSON字符串数组；不写入event_tags关系表。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

其他约束／索引：索引 `(character_id,conversation_id)`。

CHECK约束：scope仅character／conversation；injection_mode仅auto／hot／cold。

content来自用户导入／编辑；tags与keywords为各自独立JSON数组。向量在memory_vectors。界面只允许外部切片冷检索，SQL的injection_mode通用检查仍容许auto／hot／cold；UI限制与数据库约束不同。提示词世界书wrx_lorebooks.json是另一套配置，见第一部分末尾。

### 12. `event_tags` — 角色标签字典

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `tag_id` | TEXT | 否 | 1 | 无 | 稳定标签ID。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `name` | TEXT | 是 | 0 | 无 | 标签名称；同角色内唯一。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

其他约束／索引：唯一约束 `(character_id,name)`。

### 13. `diary_event_tags` — 日记与标签关系

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `diary_id` | TEXT | 是 | 1 | 无 | 关联diaries.memory_id；日记删除时级联删除关系。 |
| `tag_id` | TEXT | 是 | 2 | 无 | 关联event_tags.tag_id。 |

SQLite外键：`tag_id` → `event_tags.tag_id`；删除动作 `NO ACTION`；`diary_id` → `diaries.memory_id`；删除动作 `CASCADE`。

### 14. `memory_sources` — 记忆来源关系

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `memory_id` | TEXT | 是 | 1 | 无 | 稳定记忆ID；应用层关联来源／向量／标签，不随正文编辑改变。 |
| `source_id` | TEXT | 是 | 2 | 无 | 来源ID；可能是原始消息或活动记录ID，无SQLite外键，删除会话后来源仍可作为引用保留。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

### 15. `memory_vectors` — 旧体系记忆向量

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `memory_id` | TEXT | 否 | 1 | 无 | 稳定记忆ID；应用层关联来源／向量／标签，不随正文编辑改变。 |
| `vector` | TEXT | 否 | 0 | 无 | Embedding浮点数组的JSON；未索引／失效时为NULL。 |
| `model_signature` | TEXT | 是 | 0 | 无 | Embedding地址／模型配置签名；用于判断向量是否匹配当前模型。 |
| `index_state` | TEXT | 是 | 0 | 无 | pending／ready／error；现有写入主要使用pending／ready。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

CHECK约束：index_state仅pending／ready／error。

### 16. `memory_jobs` — 日记等生成任务

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `id` | TEXT | 否 | 1 | 无 | 生成任务去重键；自动日记按绑定／日期，手动任务含范围及消息材料摘要。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `status` | TEXT | 是 | 0 | 无 | running／done／empty／error／deleted；不是旧事件的unknown状态。 |
| `updated_at` | TEXT | 是 | 0 | 无 | 任务最新更新；还用于判定running任务是否占用／过期。 |
| `document` | TEXT | 是 | 0 | 无 | JSON主体；内部字段见本表下方说明。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

document内部：

| JSON字段 | 内容与用途 |
|---|---|
| entry_type | daily_summary／chat_entry等生成类型 |
| start、end | 原始材料筛选的带时区边界 |
| source_ids | 被选消息ID数组 |
| record_ids | 成功生成的记忆ID数组 |
| usage | 各成功阶段用量汇总 |
| raw | 最终生成输出字符串；与日记正文可能重复 |
| calls | 分段、重试和合并审计数组；项含stage、status，成功项还含usage与output |
| error | 失败／取消错误说明，失败时可有 |

calls[].output会再保存各阶段解析结果（如title、content、tags、unresolved_hooks），与raw及最终diaries有副本关系。已写入任务删除日记后可标为deleted。当前数量清理只针对requests.debug，未清理这里的raw／calls。

### 17. `diary_hooks` — 最新未结话题缓存

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `conversation_id` | TEXT | 否 | 1 | 无 | 来源会话ID；每会话只保存一行。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `date` | TEXT | 是 | 0 | 无 | 该缓存来自的每日总结业务日期，不是创建时间。 |
| `scope` | TEXT | 是 | 0 | 无 | 绑定范围：character角色共享，conversation会话私有；当前默认角色共享。 |
| `document` | TEXT | 是 | 0 | 无 | 未结话题JSON字符串数组，不是JSON对象。 |

SQLite外键：`conversation_id` → `conversations.id`；删除动作 `CASCADE`。

document为未结话题字符串数组。diaries.unresolved_hooks存每篇历史；这里缓存最新每日总结内容以供后续提示词使用。新日期才覆盖旧日期；角色共享读取会合并多个来源会话的缓存。删除日记会重建相关缓存。

### 18. `role_emotions` — 十二情绪当前状态

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `conversation_id` | TEXT | 否 | 1 | 无 | 当前情绪归属会话；每会话一行。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `document` | TEXT | 是 | 0 | 无 | JSON主体；内部字段见本表下方说明。 |

SQLite外键：`conversation_id` → `conversations.id`；删除动作 `CASCADE`。

document内部：

| JSON字段 | 内容与用途 |
|---|---|
| values | 十二情绪名→0–100数值；爱意、欣喜、期待、害羞、吃醋、委屈、生气、内疚、低落、思念、担忧、精力 |
| directions | 管家短期变化策略；情绪名→direction（up／down／hold）、degree、until |
| epoch | 当前静止周期键，关联emotion_summaries的去重 |
| revision | 情绪修订号，避免迟到模型输出写回旧状态 |
| calculated_at | 最近演算时间，避免重复推进同一时间段 |
| phase | 冷却中／会话中／等待聊天 |
| character_id、conversation_id | 归属ID，与外层重复 |
| motives | 联系、关心、修复、分享的计算分数 |
| desire_to_act | 上述动机的最高分 |
| threshold | 主动联系阈值，来自设置副本 |

精力由时钟计算，其余情绪可由模型set／add，后台冷却也会更新。这是当前状态持久化与演算游标，不能把整个document简单视为日志。

### 19. `emotion_logs` — 情绪诊断流水

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `id` | INTEGER | 否 | 1 | 无 | 全库递增日志ID；清理时按ID保留各会话最新200条。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `document` | TEXT | 是 | 0 | 无 | JSON主体；内部字段见本表下方说明。 |

SQLite外键：`conversation_id` → `conversations.id`；删除动作 `CASCADE`。

document是按事件变化的诊断对象，可包含：at写入时间、source来源（clock／web／heartbeat／manager／assessment等）、before／after情绪数值、phase状态阶段、status执行结果、warning无效输出说明、usage调用用量、raw管家原始输出。各事件不要求包含所有字段；clock日志主要保存前后数值。7天清理读document.at，每会话上限按外层id排序。

### 20. `emotion_summaries` — 情绪管家总结批次

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `conversation_id` | TEXT | 是 | 1 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `epoch` | TEXT | 是 | 2 | 无 | 聊天静止周期键，通常为最后非Heartbeat消息ID与时间拼接；与会话ID组成主键。 |
| `status` | TEXT | 是 | 0 | 无 | running／done／stale／interrupted／error；stale表示结果不再匹配当前状态。 |
| `document` | TEXT | 是 | 0 | 无 | JSON主体；内部字段见本表下方说明。 |

SQLite外键：`conversation_id` → `conversations.id`；删除动作 `CASCADE`。

document可包含at时间、raw管家原始JSON输出、usage TokenUsage、status结果状态、error错误说明。raw内通常为states数组，每项emotion、direction、degree。此表既保存总结输出，也阻止同静止周期重复请求；不是用户对话摘要，不等同system_summary。状态可能同时存在于列和JSON中。

### 21. `ai_notes` — 自主活动笔记

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `memory_id` | TEXT | 否 | 1 | 无 | 稳定记忆ID；应用层关联来源／向量／标签，不随正文编辑改变。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `scope` | TEXT | 是 | 0 | 无 | 绑定范围：character角色共享，conversation会话私有；当前默认角色共享。 |
| `content` | TEXT | 是 | 0 | 无 | 记录正文；由用户、模型或导入内容产生。 |
| `keywords` | TEXT | 是 | 0 | `'[]'` | 检索关键词JSON字符串数组；区别于标签，默认空数组。 |
| `injection_mode` | TEXT | 是 | 0 | 无 | 使用策略：auto按规则，hot常驻，cold检索；不是单独迁移到另一张表。 |
| `occurred_at` | TEXT | 否 | 0 | 无 | 实际活动时间；与创建笔记时间不同。 |
| `created_at` | TEXT | 是 | 0 | 无 | 后端创建时间；用于排序／审计，不是业务事件发生时间。 |
| `updated_at` | TEXT | 是 | 0 | 无 | 后端最近写入／修改时间；用于排序、过期判断或并发校验。 |
| `activity_id` | TEXT | 否 | 0 | 无 | 真实活动运行ID；应用层关联activity_runs.id，无SQLite外键。 |
| `activity_type` | TEXT | 是 | 0 | `''` | 活动类别；兼容字段，通常默认空。 |
| `activity_content` | TEXT | 是 | 0 | `''` | 执行器记录的实际活动内容。 |
| `execution_result` | TEXT | 是 | 0 | `'{}'` | 执行器提供的实际结果JSON，默认空对象。 |
| `note_status` | TEXT | 是 | 0 | `'pending'` | pending／done／error，旧执行器还可能写facts_only。 |
| `note_error` | TEXT | 是 | 0 | `''` | 随笔生成错误；事实执行成功与随笔生成失败可并存。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

其他约束／索引：索引 `(character_id,conversation_id)`。

CHECK约束：scope仅character／conversation；injection_mode仅auto／hot／cold。

自主外出已封存，不运行新的自动活动。保留旧执行器及历史笔记生成代码。execution_result是可变结果对象，旧执行器常含evidence数组；活动内容和结果可能与activity_runs.document重复。正文、来源、向量仍按旧记忆体系存储。

### 22. `shared_records` — 旧重要事件／约定

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `memory_id` | TEXT | 否 | 1 | 无 | 稳定记忆ID；应用层关联来源／向量／标签，不随正文编辑改变。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `scope` | TEXT | 是 | 0 | 无 | 绑定范围：character角色共享，conversation会话私有；当前默认角色共享。 |
| `content` | TEXT | 是 | 0 | 无 | 记录正文；由用户、模型或导入内容产生。 |
| `keywords` | TEXT | 是 | 0 | `'[]'` | 检索关键词JSON字符串数组；区别于标签，默认空数组。 |
| `injection_mode` | TEXT | 是 | 0 | 无 | 使用策略：auto按规则，hot常驻，cold检索；不是单独迁移到另一张表。 |
| `occurred_at` | TEXT | 否 | 0 | 无 | 材料有依据的事件发生时间；允许NULL。 |
| `created_at` | TEXT | 是 | 0 | 无 | 后端创建时间；用于排序／审计，不是业务事件发生时间。 |
| `updated_at` | TEXT | 是 | 0 | 无 | 后端最近写入／修改时间；用于排序、过期判断或并发校验。 |
| `event_tag_id` | TEXT | 是 | 0 | 无 | 唯一事件标签ID；有外键event_tags.tag_id。 |
| `record_type` | TEXT | 是 | 0 | `'milestone'` | 旧事件类别milestone／agreement／hook；SQL默认milestone。 |
| `status` | TEXT | 是 | 0 | `'unknown'` | 旧状态pending／in_progress／completed／cancelled／unknown；默认unknown，暂无自动完成判定。 |
| `due_at` | TEXT | 否 | 0 | 无 | 旧约定／事件期限；允许NULL，旧UI未自动判定。 |

SQLite外键：`event_tag_id` → `event_tags.tag_id`；删除动作 `NO ACTION`。

其他约束／索引：索引 `(character_id,conversation_id)`。

CHECK约束：scope仅character／conversation；injection_mode仅auto／hot／cold。

新约定在system_agreements，不是此表。旧agreement已由一次性迁移清除，本次快照剩2条milestone。旧事件界面／注入关闭，但兼容保存／读取、标签外键与来源／向量关系仍存在。record_type／status／due_at有预留性质；当前没有自动分类或自动状态推进。

### 23. `activity_runs` — 自主外出执行记录

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `id` | TEXT | 否 | 1 | 无 | 稳定记录ID；由后端生成或使用调用方请求ID，具体规则见各表说明。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属／来源会话ID；角色共享记忆也保留来源会话。 |
| `character_id` | TEXT | 是 | 0 | 无 | 所属角色ID；很多记忆表只在应用层校验，没有SQLite外键。 |
| `started_at` | TEXT | 是 | 0 | 无 | 后端任务／请求开始时间。 |
| `status` | TEXT | 是 | 0 | 无 | 执行／记录状态；本表使用的状态值见下方。 |
| `document` | TEXT | 是 | 0 | 无 | JSON主体；内部字段见本表下方说明。 |

SQLite外键：`conversation_id` → `conversations.id`；删除动作 `CASCADE`。

其他约束／索引：索引 `(conversation_id,started_at)`。

document内部主要字段：id、conversation_id、character_id、started_at、status（与列重复）、finished_at、provider供应商、trigger手动／Heartbeat来源、steps执行步骤、evidence真实外部结果、notes已写笔记ID、error错误。steps／evidence含动作、参数、目的地、时间、返回结果等可变对象，旧活动可能保存网页／社区内容。目前封存，启动只把旧running归档为interrupted。

### 24. `sqlite_sequence` — SQLite内部自增序列

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `name` | 未声明 | 否 | 0 | 无 | 使用AUTOINCREMENT的表名。 |
| `seq` | 未声明 | 否 | 0 | 无 | 该表自增序列计数；自动维护，不是业务时间。 |

SQLite外键：无；字段中出现角色／会话／消息ID不代表已建数据库外键。

此表由AUTOINCREMENT自动产生，列在PRAGMA中没有声明固定类型；name运行时为文本，seq为整数。不会作为模型输入，也没有自定义创建语句。

### 25. `images` — 图片独立存储

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `id` | TEXT | 否 | 1 | 无 | 随机附件身份。 |
| `message_id` | TEXT | 是 | 0 | 无 | 所属消息，外键messages.id，ON DELETE CASCADE。 |
| `conversation_id` | TEXT | 是 | 0 | 无 | 所属会话，外键conversations.id，NO ACTION。 |
| `uploaded_at` | TEXT | 是 | 0 | 无 | 原始上传UTC秒时间；重试／分支不重新计时。 |
| `mime_type` | TEXT | 是 | 0 | 无 | 图片媒体类型。 |
| `content` | BLOB | 否 | 0 | 无 | 实际二进制；过3小时设NULL，附件行保留。 |
| `origin_id` | TEXT | 是 | 0 | 无 | 分支沿用附件来源身份；用于稳定重发指纹。 |

SQLite外键：message_id → messages.id（ON DELETE CASCADE）；conversation_id → conversations.id（NO ACTION）。索引：(message_id)、(uploaded_at)。origin_id是应用层附件来源标识，无SQLite外键。

| 场景 | 是否向模型发送附件 |
|---|---|
| 首次请求、普通追问、最新AI重生成 | 原上传超过5分钟或所属会话在该消息后新增5条用户消息，任一达到停止注入；5分钟整仍可发送 |
| 原图片请求实际失败后重试 | 原上传3小时内且内容尚在，只允许恢复该用户消息自身附件；其他历史图片仍遵循普通窗口 |
| 最新用户消息编辑后重发 | 同上，自身附件最长3小时，不延长原上传时间 |
| 日记、总结 | 不发送图片，只提供正文材料 |
| 分支 | 复制附件关联／内容，origin_id及上传时间保持；计数按分支会话的前缀与后续用户消息计算 |

重试、原地重发和重生成不新增用户消息计数。3小时整停止图片读取；后台启动／每分钟清理将content设NULL，保留附件行供image_count生成“图片已过期”标记。会话仍有running请求时暂缓物理清理，避免破坏正在发送的附件；已过期重试需明确重新上传。请求debug不保留可绕过窗口的Base64图片副本；删除日记不留恢复快照。

### 26. `memory_action_keys` — 技能写入幂等关系

| 字段 | SQLite类型 | 非空 | 主键序位 | SQL默认值 | 数据内容与作用 |
|---|---|---|---:|---|---|
| `request_id` | TEXT | 是 | 1 | 无 | 原请求身份。 |
| `action_index` | INTEGER | 是 | 2 | 无 | 同一请求中的动作序号；不是随机身份。 |
| `memory_id` | TEXT | 是 | 0 | 无 | 该动作写入的随机记忆身份。 |

复合主键(request_id,action_index)；无SQLite外键，因记忆实体分布在多表。与记忆写入和请求完成处于同一事务，代替把材料SHA256当作记忆实体身份；不会额外调用模型。

### 用户模块持久化

源码归app/user/store.py和models.py，沿用同一个宿主SQLite，不按角色或会话分库。

- settings.global_user_profile：name、core、entries(tag/keywords/content)、summary_enabled、llm_profile_id、summary_hour、summary_prompt、revision；revision保护并发整合。
- user_profile_candidates：id INTEGER自增主键，request_id TEXT、action_index INTEGER、document TEXT非空，status TEXT非空默认pending；(request_id,action_index)唯一。document包含标签、关键词、正文及来源时间／角色／会话，仅用于追溯；资料全局共享。状态pending／reviewed／dismissed。
- user_profile_jobs：date TEXT主键，status TEXT和document TEXT非空；date为北京时间整理目标日。状态running／done／stale／error／interrupted，document记录用量、时间或错误。

本轮只移动代码归属，表名、字段、API与数据路径不变，没有对正式库执行迁移。

### 随机身份、摘要与时间约定

内部随机身份统一16个安全随机Base62字符，分4组，每组4字、横杠分隔，共19字符；生成器使用secrets，浏览器使用crypto.getRandomValues并拒绝偏差抽样，碰撞重试。保留固定协议名／默认角色default、外部供应商资源标识、整数序号、自增主键及sqlite_sequence。导入资料原供应商编号留在metadata或raw_fields，内部切片／条目身份独立生成。历史映射位于部署副本相邻data-identity-map.json；settings.storage_identity_aliases和storage_legacy_requests仅用于保持原完整SHA256的旧请求比较语义。

普通持久化日期时间为UTC秒级Z格式，日记日期YYYY-MM-DD原义不变。请求attempt、情绪revision、消息origin_id、debug_order分别承担并发、状态更新、分支来源和实录排序，不能靠秒级时间唯一性判断。其他摘要／复合键及情绪日志待决建议见docs/archive/reports/STORAGE_COMPACTION_REPORT.md。

### 核对来源

建表与迁移：app/chat/store.py、app/memory/schema.py、app/memory/role.py、app/memory/system.py、app/character/state.py、app/autonomy/service.py。JSON模型和写入：app/models.py、app/chat/core.py、app/character/state.py及上述模块。清理策略：app/chat/maintenance.py、app/chat/images.py。存储与迁移：app/chat/storage_format.py、app/chat/request_metadata.py、scripts/compact_deployment_data.py。提示词文件化：app/memory/prompt_files.py、role.py的stored_settings、app/memory/system_routes.py、app/character/routes.py及docs/modules/memory/PROMPTS.md。

此前只读核对旧服务器成品26张表的173列：列顺序、类型、显式非空、主键序位及SQL默认值逐项一致，表概览行数逐表一致；SQLite完整性ok、外键检查无错误。外键、唯一约束和索引参照迁移快照PRAGMA及建表源码。本次文档列的是当前真实结构；后续字段删改需要同时调整对应读写、迁移和JSON模型。

十二情绪开启时聊天／Heartbeat使用role_emotions；关闭时上下文charStatus为空，Heartbeat只标记enabled=false并依据角色设定、实际聊天、时间和现有调度设置判断联系，不提供旧版思念／担忧／精力曲线、随机噪声或阈值。现有state API仍读取十二情绪实现，未删新情绪功能。

本次新增核查：本机精简副本29表／197实体列＋4虚拟列，PRAGMA完整性ok、外键无错误；五条系统记忆迁移逐行核对内容、来源、时间段及向量，旧合表删除。其他字段结构与此前精简成品一致，表行数已按本机新副本更新。
