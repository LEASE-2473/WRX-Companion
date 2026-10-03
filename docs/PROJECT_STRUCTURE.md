# 当前项目目录与逐文件用途

更新：2026-10-04。此索引以实际文件生成；历史迁移说明在docs/archive。

编辑用途表`docs/reference/FILE_PURPOSES.json`后运行`python scripts/update_structure_index.py`。
`python scripts/check_structure.py`检查运行文件登记、索引同步及现行文档链接。

## 根目录

| 位置 | 用途 |
|---|---|
| app/ | 正式程序及全部必需静态资源、技能和任务提示词 |
| data/ | 私人SQLite、JSON配置、设备记录与本机备份；不公开上传 |
| docs/ | 当前说明、操作指南、未来规划、历史归档 |
| experiments/emotion-lab/ | 独立离线实验，不参与正式聊天 |
| tests/ | 按业务区域分组的离线Python和Node回归 |
| scripts/ | 结构检查、目录索引生成、离线数据迁移 |
| Toy connection/ | 本地设备研究程序、采集与解包资料；正式应用不依赖；说明已归docs/archive/research/toy |
| remote service backup/ | 原服务器私人备份，保留原位置 |
| remote service prepared/ | 迁移源、中间副本与指定成品；详见operations/DEPLOYMENT_SNAPSHOTS |
| .venv/、.pytest_cache/、__pycache__/、.git/ | 环境、生成缓存和既有版本管理元数据，不是业务模块 |

## 根目录文件

| 文件 | 用途 |
|---|---|
| [.gitignore](../.gitignore) | 私人数据／环境／研究／本地历史资料忽略约定 |
| [CHANGELOG.md](../CHANGELOG.md) | 按任务追加的中文变更历史 |
| [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) | 中文当前状态、核心约定与最新验证 |
| [pytest.ini](../pytest.ini) | 仅收集tests目录的测试配置 |
| [README.md](../README.md) | 项目介绍、部署与文档导航入口 |
| [requirements.txt](../requirements.txt) | 主应用及设备工具统一Python依赖 |
| [start_companion.bat](../start_companion.bat) | 唯一启动入口；创建环境、安装依赖并启动2473 FastAPI应用 |
| [TODO.md](../TODO.md) | 尚未实现的当前待办 |

## app：按功能区域的全部运行文件

入口为app.main:app；不再依赖根prompts目录。__init__.py用于Python包标记，不能按空文件判定为历史残留。

### (入口与公共模型)

| 文件 | 用途 |
|---|---|
| [app/__init__.py](../app/__init__.py) | Python包入口／模块分区标记 |
| [app/config.py](../app/config.py) | 项目根、运行数据、静态与技能目录常量 |
| [app/lifecycle.py](../app/lifecycle.py) | 启动恢复、后台调度与退出清理 |
| [app/main.py](../app/main.py) | FastAPI装配、路由注册、静态资源挂载和首页 |
| [app/models.py](../app/models.py) | 跨模块Pydantic请求／响应／配置／消息模型 |

### autonomy

| 文件 | 用途 |
|---|---|
| [app/autonomy/__init__.py](../app/autonomy/__init__.py) | Python包入口／模块分区标记 |
| [app/autonomy/lutopia.py](../app/autonomy/lutopia.py) | 保留的Lutopia社区适配，当前不启用 |
| [app/autonomy/routes.py](../app/autonomy/routes.py) | 封存外出设置／历史兼容接口，不恢复自动外出 |
| [app/autonomy/service.py](../app/autonomy/service.py) | 封存自主外出服务、历史记录和旧任务中断归档 |

### character

| 文件 | 用途 |
|---|---|
| [app/character/__init__.py](../app/character/__init__.py) | Python包入口／模块分区标记 |
| [app/character/routes.py](../app/character/routes.py) | 情绪设置、状态查看、手动评估与管家接口 |
| [app/character/state.py](../app/character/state.py) | 十二情绪持久状态、模型更新／手动评估、冷却管家及联系动机 |

### chat

| 文件 | 用途 |
|---|---|
| [app/chat/__init__.py](../app/chat/__init__.py) | Python包入口／模块分区标记 |
| [app/chat/core.py](../app/chat/core.py) | 聊天上下文、模型流、搜索、技能／设备、完成／失败事务编排 |
| [app/chat/heartbeat.py](../app/chat/heartbeat.py) | 主动联系调度、间隔／静默／每日上限与冷却 |
| [app/chat/history.py](../app/chat/history.py) | 按条数或起始时间选择普通聊天历史，不裁剪数据库正文 |
| [app/chat/images.py](../app/chat/images.py) | 图片附件BLOB、窗口判断、重试恢复和过期清理 |
| [app/chat/maintenance.py](../app/chat/maintenance.py) | 请求debug、图片与情绪日志定期清理 |
| [app/chat/request_metadata.py](../app/chat/request_metadata.py) | 最小请求执行关联、设备动作标记与失败重放保护 |
| [app/chat/routes.py](../app/chat/routes.py) | 聊天HTTP／SSE、上下文调试、消息操作；搜索配置路由目前仍在这里 |
| [app/chat/storage_format.py](../app/chat/storage_format.py) | 消息正文序列化、请求结构及退役关系表迁移 |
| [app/chat/store.py](../app/chat/store.py) | 角色、会话、消息、请求幂等、编辑重发／重生成与分支SQLite事务 |

### common

| 文件 | 用途 |
|---|---|
| [app/common/__init__.py](../app/common/__init__.py) | Python包入口／模块分区标记 |
| [app/common/errors.py](../app/common/errors.py) | 统一API异常转换 |
| [app/common/identity.py](../app/common/identity.py) | 安全Base62实体身份与碰撞检查 |
| [app/common/time_format.py](../app/common/time_format.py) | UTC秒时间规范化与持久格式 |

### memory

| 文件 | 用途 |
|---|---|
| [app/memory/__init__.py](../app/memory/__init__.py) | Python包入口／模块分区标记 |
| [app/memory/prompt_files.py](../app/memory/prompt_files.py) | 统一读写memory/prompts中的七份运行提示词 |
| [app/memory/prompts/activity.md](../app/memory/prompts/activity.md) | 封存实际自主活动笔记提示词 |
| [app/memory/prompts/diary.md](../app/memory/prompts/diary.md) | 独立当日日记完整提示词 |
| [app/memory/prompts/diary_instant.md](../app/memory/prompts/diary_instant.md) | 独立指定时段日记完整提示词 |
| [app/memory/prompts/diary_merge.md](../app/memory/prompts/diary_merge.md) | 日记分段总结后合并提示词 |
| [app/memory/prompts/emotion_summary.md](../app/memory/prompts/emotion_summary.md) | 情绪冷却管家总结提示词 |
| [app/memory/prompts/event.md](../app/memory/prompts/event.md) | 旧事件配置兼容提示词；生成已停用，配置模型仍读取 |
| [app/memory/prompts/system.md](../app/memory/prompts/system.md) | 系统四表自动／追溯填表完整提示词；保留用户最新文本 |
| [app/memory/role.py](../app/memory/role.py) | 角色日记、来源、冷热、任务配置、向量整合与独立调度 |
| [app/memory/role_routes.py](../app/memory/role_routes.py) | 角色日记、记忆设置、冷热、外部资料导入与连接测试API |
| [app/memory/schema.py](../app/memory/schema.py) | 角色记忆显式列、标签／来源／向量和旧结构迁移 |
| [app/memory/system.py](../app/memory/system.py) | 四类系统记忆、原始时间材料、追溯、自动填表、冷热与任务锁 |
| [app/memory/system_routes.py](../app/memory/system_routes.py) | 系统四表编辑、追溯／取消、进度与提示词设置API |
| [app/memory/system_schema.py](../app/memory/system_schema.py) | 系统四张物理表、序号定位、BLOB向量校验与兼容迁移 |
| [app/memory/vector_routes.py](../app/memory/vector_routes.py) | 旧独立JSON向量工具兼容API，不是当前聊天角色记忆入口 |
| [app/memory/vector_store.py](../app/memory/vector_store.py) | 共享Embedding／Rerank／相似度适配；同时保留旧JSON资料库管理 |

### prompting

| 文件 | 用途 |
|---|---|
| [app/prompting/__init__.py](../app/prompting/__init__.py) | Python包入口／模块分区标记 |
| [app/prompting/compiler.py](../app/prompting/compiler.py) | 预设、宏、世界书、深度注入与最终上下文顺序／trace |
| [app/prompting/lorebook_store.py](../app/prompting/lorebook_store.py) | 提示词世界书CRUD、导入与快照，存wrx_lorebooks.json |
| [app/prompting/preset_store.py](../app/prompting/preset_store.py) | 预设CRUD、导入、启用与请求快照，存wrx_prompt_presets.json |
| [app/prompting/routes.py](../app/prompting/routes.py) | 预设与提示词世界书HTTP管理接口 |

### providers

| 文件 | 用途 |
|---|---|
| [app/providers/__init__.py](../app/providers/__init__.py) | Python包入口／模块分区标记 |
| [app/providers/client.py](../app/providers/client.py) | LLM、火山STT、HTTP／豆包TTS供应商适配与流解析 |
| [app/providers/diagnostics.py](../app/providers/diagnostics.py) | 供应商异常文本清洗与密钥脱敏 |
| [app/providers/profiles.py](../app/providers/profiles.py) | 统一Profile持久化、用途校验、密钥脱敏与请求快照 |
| [app/providers/routes.py](../app/providers/routes.py) | 供应商Profile CRUD、模型列表、连接／真实调用测试API |
| [app/providers/usage.py](../app/providers/usage.py) | 供应商真实Token用量读取和累加；缺失不伪造 |

### search

| 文件 | 用途 |
|---|---|
| [app/search/__init__.py](../app/search/__init__.py) | Python包入口／模块分区标记 |
| [app/search/service.py](../app/search/service.py) | Tavily／SearXNG搜索适配，搜索结果及来源整理 |

### settings

| 文件 | 用途 |
|---|---|
| [app/settings/__init__.py](../app/settings/__init__.py) | Python包入口／模块分区标记 |
| [app/settings/routes.py](../app/settings/routes.py) | 组合设置读取及运行配置HTTP保存 |
| [app/settings/store.py](../app/settings/store.py) | 全局历史选择等运行配置JSON与快照 |

### skills

| 文件 | 用途 |
|---|---|
| [app/skills/__init__.py](../app/skills/__init__.py) | Python包入口／模块分区标记 |
| [app/skills/definitions/diary-write/SKILL.md](../app/skills/definitions/diary-write/SKILL.md) | AI自主即时日记的运行技能 |
| [app/skills/definitions/event-write/SKILL.md](../app/skills/definitions/event-write/SKILL.md) | 已停用旧事件技能，不进入允许目录 |
| [app/skills/definitions/explore/SKILL.md](../app/skills/definitions/explore/SKILL.md) | 封存外出技能，保留未来方向 |
| [app/skills/definitions/memory-read/SKILL.md](../app/skills/definitions/memory-read/SKILL.md) | 按需搜索／读取当前角色可见记忆的运行技能 |
| [app/skills/definitions/reflect/SKILL.md](../app/skills/definitions/reflect/SKILL.md) | 封存实际活动反思技能，保留未来方向 |
| [app/skills/PROTOCOL.md](../app/skills/PROTOCOL.md) | 普通聊天模型读取／写入的共享运行协议，不是维护说明 |
| [app/skills/routes.py](../app/skills/routes.py) | 当前允许技能目录／正文只读接口 |
| [app/skills/runtime.py](../app/skills/runtime.py) | 允许目录、按需读取、模型调用块、日记写入事务与幂等 |

### static

| 文件 | 用途 |
|---|---|
| [app/static/autonomy/autonomy.css](../app/static/autonomy/autonomy.css) | 封存外出界面样式 |
| [app/static/autonomy/autonomy.js](../app/static/autonomy/autonomy.js) | 封存外出历史／设置界面，不启用新活动 |
| [app/static/character/role-state.css](../app/static/character/role-state.css) | 情绪设置与状态面板样式 |
| [app/static/character/role-state.js](../app/static/character/role-state.js) | 十二情绪查看、编辑／手动评估与管家配置 |
| [app/static/chat/chat-ui.css](../app/static/chat/chat-ui.css) | 聊天气泡、编辑、附件和消息操作布局 |
| [app/static/chat/chat-ui.js](../app/static/chat/chat-ui.js) | 唯一文字发送与最终聊天视图；附件、编辑、分支、重发／重生成、逐条朗读 |
| [app/static/chat/companion.js](../app/static/chat/companion.js) | 角色／会话切换、服务端刷新、搜索／Heartbeat设置、SSE读取与基础消息节点 |
| [app/static/chat/context-debug.css](../app/static/chat/context-debug.css) | 上下文调试面板样式 |
| [app/static/chat/context-debug.js](../app/static/chat/context-debug.js) | 最终上下文模拟／真实实录查看 |
| [app/static/index.html](../app/static/index.html) | 正式首页DOM、面板与脚本加载顺序 |
| [app/static/memory/role-memory.css](../app/static/memory/role-memory.css) | 角色日记与常规记忆面板样式 |
| [app/static/memory/role-memory.js](../app/static/memory/role-memory.js) | 角色日记／常规热区／活动历史／向量与任务设置面板 |
| [app/static/memory/system-memory.css](../app/static/memory/system-memory.css) | 系统四表、横向表格与分页样式 |
| [app/static/memory/system-memory.js](../app/static/memory/system-memory.js) | 系统四表、追溯／自动填表、外部世界书管理 |
| [app/static/settings/app.js](../app/static/settings/app.js) | 供应商、预设、世界书、全局设置与旧JSON向量兼容界面 |
| [app/static/settings/settings-design.css](../app/static/settings/settings-design.css) | 供应商／预设／设置面板布局 |
| [app/static/shared/compact-ui.css](../app/static/shared/compact-ui.css) | 公共紧凑布局与移动端适配 |
| [app/static/shared/state.js](../app/static/shared/state.js) | 页面共享变量、身份生成与热键规范化；首先加载 |
| [app/static/shared/styles.css](../app/static/shared/styles.css) | 页面公共基础样式 |
| [app/static/tools/role-tools.css](../app/static/tools/role-tools.css) | 设备工具卡片与面板样式 |
| [app/static/tools/role-tools.js](../app/static/tools/role-tools.js) | 设备工具卡片、启动／关闭与面板生命周期 |
| [app/static/voice/voice-ui.js](../app/static/voice/voice-ui.js) | 麦克风采集、实时STT、语音请求、音频播放、录音控件与热键 |

### tools

| 文件 | 用途 |
|---|---|
| [app/tools/__init__.py](../app/tools/__init__.py) | Python包入口／模块分区标记 |
| [app/tools/routes.py](../app/tools/routes.py) | 角色工具卡片、按需服务和受令牌门控的同源面板代理 |
| [app/tools/toy/__init__.py](../app/tools/toy/__init__.py) | Python包入口／模块分区标记 |
| [app/tools/toy/controller.py](../app/tools/toy/controller.py) | 主应用设备子服务管理、Skill门控、原生工具、DIY序列与退出 |
| [app/tools/toy/protocol.py](../app/tools/toy/protocol.py) | 设备协议、通道与帧编码 |
| [app/tools/toy/records.py](../app/tools/toy/records.py) | 设备操作与播放运行记录，写data/toy |
| [app/tools/toy/resources/classic_modes.json](../app/tools/toy/resources/classic_modes.json) | 八种经典播放模式数据 |
| [app/tools/toy/resources/panel.html](../app/tools/toy/resources/panel.html) | 设备扫描、连接、经典模式和DIY控制面板 |
| [app/tools/toy/resources/tools.json](../app/tools/toy/resources/tools.json) | 设备原生工具定义与参数结构 |
| [app/tools/toy/service.py](../app/tools/toy/service.py) | 本机8767蓝牙HTTP服务，扫描／连接由用户操作 |
| [app/tools/toy/skill/SKILL.md](../app/tools/toy/skill/SKILL.md) | 设备就绪时向模型提供的正式设备运行技能 |

### voice

| 文件 | 用途 |
|---|---|
| [app/voice/__init__.py](../app/voice/__init__.py) | Python包入口／模块分区标记 |
| [app/voice/pipeline.py](../app/voice/pipeline.py) | 语音回复正文清洗、可朗读片段和异常描述 |
| [app/voice/routes.py](../app/voice/routes.py) | 实时STT WebSocket、语音请求SSE与单轮配置快照；正式聊天走chat/core |

## docs：现行说明

archive保存原文历史，可能含旧路径，详见[归档索引](archive/README.md)。planning仅表示未来／封存方向。

| 文件 | 用途 |
|---|---|
| [docs/COMPANION_GUIDE.md](../docs/COMPANION_GUIDE.md) | 当前版本使用与验收 |
| [docs/experiments/EMOTION_LAB.md](../docs/experiments/EMOTION_LAB.md) | 独立情绪实验台 |
| [docs/images/autonomy-archived.jpg](../docs/images/autonomy-archived.jpg) | 说明配图／参考资源 |
| [docs/images/chat-ui-offline-preview.jpg](../docs/images/chat-ui-offline-preview.jpg) | 说明配图／参考资源 |
| [docs/images/compact-footer-search.png](../docs/images/compact-footer-search.png) | 说明配图／参考资源 |
| [docs/images/composer-width-fixed.png](../docs/images/composer-width-fixed.png) | 说明配图／参考资源 |
| [docs/images/conversation-actions.png](../docs/images/conversation-actions.png) | 说明配图／参考资源 |
| [docs/images/image-attachment-preview.png](../docs/images/image-attachment-preview.png) | 说明配图／参考资源 |
| [docs/images/immersive-usage-footer.png](../docs/images/immersive-usage-footer.png) | 说明配图／参考资源 |
| [docs/images/search-configurable.png](../docs/images/search-configurable.png) | 说明配图／参考资源 |
| [docs/images/search-provider-fields-fixed.png](../docs/images/search-provider-fields-fixed.png) | 说明配图／参考资源 |
| [docs/images/system-memory-mobile.jpg](../docs/images/system-memory-mobile.jpg) | 说明配图／参考资源 |
| [docs/MAINTENANCE.md](../docs/MAINTENANCE.md) | 项目维护与跨模块检查 |
| [docs/modules/character/README.md](../docs/modules/character/README.md) | 十二情绪与冷却管家 |
| [docs/modules/chat/README.md](../docs/modules/chat/README.md) | 聊天、历史与Heartbeat |
| [docs/modules/memory/PROMPTS.md](../docs/modules/memory/PROMPTS.md) | 运行提示词文件与修改位置 |
| [docs/modules/memory/ROLE_MEMORY.md](../docs/modules/memory/ROLE_MEMORY.md) | 角色日记与记忆 |
| [docs/modules/memory/SYSTEM_MEMORY.md](../docs/modules/memory/SYSTEM_MEMORY.md) | 系统记忆与角色日记 |
| [docs/modules/prompting/README.md](../docs/modules/prompting/README.md) | 聊天预设、宏与提示词世界书 |
| [docs/modules/providers/README.md](../docs/modules/providers/README.md) | LLM、TTS、STT、Embedding与Rerank |
| [docs/modules/search/README.md](../docs/modules/search/README.md) | 联网搜索 |
| [docs/modules/settings/README.md](../docs/modules/settings/README.md) | 全局设置与旧向量兼容边界 |
| [docs/modules/tools/ROLE_TOOLS.md](../docs/modules/tools/ROLE_TOOLS.md) | 角色工具与模型调用 |
| [docs/modules/voice/README.md](../docs/modules/voice/README.md) | 辅助录音、STT与音频播放 |
| [docs/operations/DATABASE_MIGRATION.md](../docs/operations/DATABASE_MIGRATION.md) | 数据库迁移、部署与回滚 |
| [docs/operations/DEPLOYMENT_SNAPSHOTS.md](../docs/operations/DEPLOYMENT_SNAPSHOTS.md) | 现有数据与部署副本清单 |
| [docs/planning/autonomy/PHASE4_AUTONOMY.md](../docs/planning/autonomy/PHASE4_AUTONOMY.md) | 阶段 4：自主外出与活动笔记 |
| [docs/planning/README.md](../docs/planning/README.md) | 当前未来规划 |
| [docs/PROJECT_STRUCTURE.md](../docs/PROJECT_STRUCTURE.md) | 当前项目目录与逐文件用途 |
| [docs/README.md](../docs/README.md) | 文档导航 |
| [docs/reference/DATABASE_FIELDS.md](../docs/reference/DATABASE_FIELDS.md) | 数据库结构与字段人工审阅清单 |
| [docs/reference/FILE_PURPOSES.json](../docs/reference/FILE_PURPOSES.json) | 人工维护的运行文件用途表，新增或移动app文件必须同步 |
| [docs/reference/SKILLS.md](../docs/reference/SKILLS.md) | 应用内技能与执行协议 |

## tests：实际测试文件

默认仅收集tests，不运行研究目录设备脚本。

| 文件 | 用途 |
|---|---|
| [tests/__init__.py](../tests/__init__.py) | 测试包标记 |
| [tests/autonomy/__init__.py](../tests/autonomy/__init__.py) | 测试包标记 |
| [tests/autonomy/test_autonomy.py](../tests/autonomy/test_autonomy.py) | 封存外出兼容、历史读取与不自动执行回归 |
| [tests/character/__init__.py](../tests/character/__init__.py) | 测试包标记 |
| [tests/character/test_role_state.py](../tests/character/test_role_state.py) | 十二情绪、冷却评估、联系动机与Profile回归 |
| [tests/character/test_state_machine.py](../tests/character/test_state_machine.py) | 历史测试名保留；覆盖当前状态API与关闭情绪行为 |
| [tests/chat/__init__.py](../tests/chat/__init__.py) | 测试包标记 |
| [tests/chat/test_branch_storage.py](../tests/chat/test_branch_storage.py) | 独立分支来源、复制前缀与存储回归 |
| [tests/chat/test_companion.py](../tests/chat/test_companion.py) | 聊天Core、请求、持久化、供应商与流式综合回归 |
| [tests/chat/test_history_time.py](../tests/chat/test_history_time.py) | 历史起始时间、时区与预览回归 |
| [tests/chat/test_images.py](../tests/chat/test_images.py) | 附件注入窗口、失败恢复、分支与过期回归 |
| [tests/chat/test_maintenance.py](../tests/chat/test_maintenance.py) | debug与情绪日志保留、图片清理回归 |
| [tests/chat/test_message_actions.py](../tests/chat/test_message_actions.py) | 用户编辑、最新轮重发与生成冲突回归 |
| [tests/chat/test_regenerate_delete.py](../tests/chat/test_regenerate_delete.py) | AI重生成、角色／会话删除与隔离回归 |
| [tests/chat/test_request_replay.py](../tests/chat/test_request_replay.py) | 请求幂等重放、失败重试和设备动作保护回归 |
| [tests/chat/test_storage_compaction.py](../tests/chat/test_storage_compaction.py) | 正文精简、请求关联、身份、时间与分支迁移回归 |
| [tests/conftest.py](../tests/conftest.py) | 隔离正式库、JSON配置、技能及提示词的公共fixture |
| [tests/integration/__init__.py](../tests/integration/__init__.py) | 测试包标记 |
| [tests/integration/api_routes.json](../tests/integration/api_routes.json) | HTTP路由契约基线 |
| [tests/integration/test_baseline.py](../tests/integration/test_baseline.py) | 应用路由、会话、预设与向量适配基本回归 |
| [tests/integration/test_deployment_data.py](../tests/integration/test_deployment_data.py) | 旧结构离线部署副本生成、源数据保留回归 |
| [tests/integration/test_storage_migration.py](../tests/integration/test_storage_migration.py) | 身份／配置／存储精简迁移与内容一致性回归 |
| [tests/integration/test_structure.py](../tests/integration/test_structure.py) | HTTP契约、首页资源、跨工作目录与文档／目录索引回归 |
| [tests/memory/__init__.py](../tests/memory/__init__.py) | 测试包标记 |
| [tests/memory/test_audit_regressions.py](../tests/memory/test_audit_regressions.py) | 冷日记回退、向量异常脱敏与全部候选Rerank回归 |
| [tests/memory/test_diary_management.py](../tests/memory/test_diary_management.py) | 日记标题、编辑删除、未结话题与任务重生成回归 |
| [tests/memory/test_diary_ranges.py](../tests/memory/test_diary_ranges.py) | 独立日记完整时间材料、递归总结与合并回归 |
| [tests/memory/test_memory_schema.py](../tests/memory/test_memory_schema.py) | 显式记忆列、来源标签、向量及旧JSON结构迁移回归 |
| [tests/memory/test_prompt_files.py](../tests/memory/test_prompt_files.py) | 运行提示词读取、页面写回和SQLite不保存副本回归 |
| [tests/memory/test_role_memory.py](../tests/memory/test_role_memory.py) | 角色作用域、冷热、记忆配置与独立日记回归 |
| [tests/memory/test_system_four_tables.py](../tests/memory/test_system_four_tables.py) | 物理四表、自增序号、向量BLOB、旧表名迁移回归 |
| [tests/memory/test_system_memory.py](../tests/memory/test_system_memory.py) | 系统填表、追溯、自动窗口、冷记录与角色共享回归 |
| [tests/prompting/__init__.py](../tests/prompting/__init__.py) | 测试包标记 |
| [tests/prompting/test_status_macros.py](../tests/prompting/test_status_macros.py) | 情绪／时间宏、深度与最终上下文顺序回归 |
| [tests/providers/__init__.py](../tests/providers/__init__.py) | 测试包标记 |
| [tests/providers/test_provider_setup.py](../tests/providers/test_provider_setup.py) | 模型用途、连接测试／模型列表和配置回归 |
| [tests/providers/test_temperature.py](../tests/providers/test_temperature.py) | 温度零值／边界与供应商参数回归 |
| [tests/search/__init__.py](../tests/search/__init__.py) | 测试包标记 |
| [tests/search/test_search_custom.py](../tests/search/test_search_custom.py) | 联网搜索配置与来源适配回归 |
| [tests/skills/__init__.py](../tests/skills/__init__.py) | 测试包标记 |
| [tests/skills/test_chat_skills.py](../tests/skills/test_chat_skills.py) | 允许技能读取、调用解析、即时日记、事务和幂等回归 |
| [tests/tools/__init__.py](../tests/tools/__init__.py) | 测试包标记 |
| [tests/tools/test_role_tools.py](../tests/tools/test_role_tools.py) | 设备工具门控、DIY、连接代次、关闭与动作保护回归 |
| [tests/tools/test_toy_package.py](../tests/tools/test_toy_package.py) | 无研究目录依赖的设备子服务部署与资源回归 |
| [tests/ui/heartbeat_ui_test.cjs](../tests/ui/heartbeat_ui_test.cjs) | 心跳日志展开、用量耗时与安全文本显示回归 |
| [tests/ui/page_boot_test.cjs](../tests/ui/page_boot_test.cjs) | 按首页真实顺序执行脚本，检查函数唯一性、初始化依赖及控件绑定 |
| [tests/ui/provider_ui_test.cjs](../tests/ui/provider_ui_test.cjs) | 保存供应商草稿后查询模型／测试调用回归 |
| [tests/ui/reply_format_test.cjs](../tests/ui/reply_format_test.cjs) | 回复分块、内部标记拆片与用户原文保留回归 |
| [tests/ui/role_tools_ui_test.cjs](../tests/ui/role_tools_ui_test.cjs) | 设备面板加载、关闭和UI生命周期回归 |
| [tests/ui/temperature_ui_test.cjs](../tests/ui/temperature_ui_test.cjs) | 前端温度零值、非法输入及其他参数保留回归 |
| [tests/ui_preview.py](../tests/ui_preview.py) | 2474模拟模型／搜索／语音界面预览，不是正式服务 |

## scripts：维护入口

| 文件 | 用途 |
|---|---|
| [scripts/check_structure.py](../scripts/check_structure.py) | 只读检查本地导入、静态资源、运行用途登记、索引同步与现行文档链接 |
| [scripts/compact_deployment_data.py](../scripts/compact_deployment_data.py) | 只读源目录，生成身份／存储精简、系统四表迁移后的独立部署成品 |
| [scripts/prepare_deployment_data.py](../scripts/prepare_deployment_data.py) | 旧数据库前置结构迁移到独立副本 |
| [scripts/update_structure_index.py](../scripts/update_structure_index.py) | 按实际文件和FILE_PURPOSES生成逐文件目录说明；--check只读 |

## experiments：实验文件

| 文件 | 用途 |
|---|---|
| [experiments/emotion-lab/archive-v1.fragment.html](../experiments/emotion-lab/archive-v1.fragment.html) | 旧63变量实验源码，比较用 |
| [experiments/emotion-lab/archive-v1.html](../experiments/emotion-lab/archive-v1.html) | 旧63变量实验成品，比较用 |
| [experiments/emotion-lab/emotion-lab.fragment.html](../experiments/emotion-lab/emotion-lab.fragment.html) | 新版实验可编辑源，聊天内预览来源 |
| [experiments/emotion-lab/index.html](../experiments/emotion-lab/index.html) | 新版36变量独立实验成品，双击可打开 |
| [experiments/emotion-lab/test.cjs](../experiments/emotion-lab/test.cjs) | 36变量、问卷、隔离和恢复等离线回归 |

## 常见修改在哪里

| 目标 | 修改入口与关联 |
|---|---|
| 修改系统总结提示词 | app/memory/prompts/system.md；解析规则在memory/system与system_schema |
| 修改独立日记风格 | memory/prompts/diary或diary_instant；合并用diary_merge |
| 修改AI聊天自主日记 | skills/definitions/diary-write；写入由skills/runtime处理 |
| 修改聊天显示或消息操作 | static/chat/chat-ui；会话API在chat/routes与store |
| 修改模型／语音配置 | providers与static/settings/app；录音播放在static/voice |
| 修改冷热记忆／召回 | memory/role、system、vector_store；同步模型签名和失配回退 |
| 修改情绪／主动联系 | character/state、chat/heartbeat及chat/core；跨模块同步 |
| 修改设备能力 | tools/toy；技能、协议、执行和退出清理要一起核对 |
| 查数据库或部署版本 | docs/reference/DATABASE_FIELDS及docs/operations |
| 查旧讨论、研究或升级过程 | docs/archive；当前状态仍以PROJECT_CONTEXT和源码为准 |

跨模块修改清单见[MAINTENANCE](MAINTENANCE.md)。新增／移动文件时更新用途表、索引、引用和相关测试；不要再通过同名全局函数覆盖旧实现。
