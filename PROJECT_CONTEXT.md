# WRX Companion — 当前项目上下文

更新日期：2026-10-01（Asia/Shanghai）。记录实际实现和验收范围。

## 目标与用户最新约定

建设文字聊天为主的多角色 Companion，保留预设、世界书和 WRX 复刻音色／语音能力，当前产品只需文字聊天、逐条 TTS 朗读与 Heartbeat；用户明确不再需要实时 STT→LLM→TTS 语音模式，旧链路代码暂留。用户目前明确暂缓总结、向量记忆与新知识库存储方案；原始聊天持久化照常实现。不同 Character 的会话隔离。

2026-10-01 用户纠正：2.0 不沿用 WRX 的语音主界面；聊天类似 SillyTavern／Chatbox，AI 回复可逐条配置音色、点击播放，消息可编辑、重新发送、重新生成及创建分支。原 overview/plan 仍为设计依据，最新用户授权优先；手机通知可采用 iOS Web Push，微信不阻塞。

## 根目录与来源

- 唯一项目根目录：`D:\LEASE AI Project\温柔乡陪伴计划 2.0`。
- GitHub WRX 基线：`96fb793a2fa22866e7f37982c8b02ebf8462af92`，来自 https://github.com/LEASE-2473/WRX-Voice-Agent。
- 本地保留 WRX 历史；本次用户授权提交并公开发布到 https://github.com/LEASE-2473/WRX-Companion，origin 指向该独立仓库。仓库级身份改为 LEASE-2473 / 130589390+LEASE-2473@users.noreply.github.com；不修改全局身份。`data/` 与密钥保持忽略，新电脑恢复自定义配置需私下迁移整个 data 目录。
- 根目录无 AGENTS.md，使用用户给定的中文连续性文档规则。

## 技术栈与目录

Python 3.12.14、FastAPI / Uvicorn / Pydantic、httpx / websockets；原生 HTML/CSS/JavaScript、SSE、WebSocket、Web Audio，无前端构建器。测试 pytest；IANA 时区使用 zoneinfo + tzdata。

- `app/companion_store.py`：SQLite WAL 事务存储角色、会话、原始消息、请求、搜索配置、Heartbeat 设置和分支关系。数据库 `data/companion.sqlite3`，测试可用 `WRX_DB_PATH` 隔离。
- `app/companion_core.py`：共享上下文、角色／Persona／预设／世界书绑定、真实时间、搜索决策、生成、usage、消息落库，统一文字／语音／主动事件。
- `app/companion_routes.py`：Character、会话、文字 SSE、分支／编辑、逐条 TTS、请求用量、搜索与 Heartbeat API。
- `app/heartbeat.py`：后端生命周期调度，SQLite 领取下一次检查，不依赖浏览器。关页仍运行；停止后端则暂停。
- `app/search.py`：可配置 Tavily / SearXNG / 豆包搜索 Custom（API Key）/ 自定义 HTTP（GET／POST、JSON 模板、鉴权头、响应字段路径），AUTO／ON／OFF，保留查询来源。搜索面板按 Provider 显示专属参数，豆包不显示 Tavily 深度或自定义 HTTP 字段。
- `app/usage.py`：真实供应商 Input／Cache／Output 标准化，缺失为 None；搜索判断额外调用单独记录。
- `app/main.py`：既有配置、STT／语音路由与生命周期接线；语音进入同一 Core。
- `app/providers.py`：复用火山 STT、OpenAI-compatible LLM、HTTP／豆包 WebSocket TTS；流式读取最终 usage，并处理不支持 stream_options 的端点。
- `app/prompt_compiler.py`：纯上下文编译；角色／用户由 charDefinitions／userDefinitions 注入，保留常驻／关键词／深度世界书与预设排序。
- `app/static/index.html`、`chat-ui.js/css`：文字主界面、角色／会话侧栏、底部输入、逐条消息操作与朗读。聊天输入框显式占满容器宽度，使用正常字重，避免浏览器默认列宽造成左侧窄栏。`app.js`、`companion.js` 保留配置编辑器、语音与状态接线，后续可清理其中被新主界面替换的旧函数。
- Provider、预设、世界书、运行设置仍保留 WRX JSON 配置。拉取模型／测试连接先保存页面当前 Profile 配置；拉取列表无需填写 Model，缺失 Profile 归为配置错误。原 `conversation_store.py` 不再是正式 API 的会话写入入口。
- `tests/`：离线 API、并发／幂等、迁移、搜索／usage、Heartbeat、语音和分支／TTS 检查；`ui_preview.py` 提供隔离模拟界面，不用于正式聊天。
- `docs/WRX_AUDIT.md` 保留初始审计；`docs/REFERENCE_RESEARCH.md` 为源码参考与采用依据；`docs/COMPANION_GUIDE.md` 为当前使用方式。

## 运行与验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 2473
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app
node --check app/static/app.js
node --check app/static/companion.js
node --check app/static/chat-ui.js
```

可双击 `start_companion.bat`，进入本机 2473 端口；兼容原启动脚本。启动脚本使用 reload 开发模式；正式服务需要另行部署。文字仅需 LLM；逐条朗读额外需要 TTS；麦克风模式需要 STT、LLM、TTS。没有导入密钥或调用付费模型。当前自动检查 60 passed，1 条 TestClient/httpx 弃用警告；compileall、三个 JS 语法检查、pip check、git diff --check 均通过。浏览器已验收文字、角色、分支／编辑／朗读、主动消息的模拟流程，截图在 `docs/images/chat-ui-offline-preview.jpg`。

## 关键设计与真实状态

- 聊天顶部移除 Idle 状态徽章与重复 Heartbeat 按钮，主动联系设置从左侧入口进入。聊天正文不展示用量行／请求明细；输入框下方单行按「消息数／自动保存｜Input／Cache／Output｜发送快捷键」排列，不提供历史用量前端展示，详细用量继续保存在后端。联网来源默认折叠为 [联网搜索]。「重新生成」与朗读、音色并排，分支生成仍在更多菜单。
- 当前本机「WRX 最小默认预设」已整理聊天节奏、陪伴与事实边界、时间元数据和文字回复格式；默认预设禁用旧 Voice Output，文字格式和统一自检不再包含语音模式分支。文字回复规范明确日常气泡内禁止换行／空行分段，分开发必须使用 `<|next_message|>`，包含合并／拆块正反例；列表、代码、诗歌与详细说明保留正常排版例外。文字支持 `<|next_message|>` 分块：同一轮共用元信息、用量、编辑和朗读；流式隐藏标记片段、复制与朗读过滤标记，原始内容保留。固定格式规则与示例在历史之前；所有内部自检合并为独立「回复自检」system 条目，默认位于 Chat History 后（实际编译在历史和本轮 user 时间后缀之后），可在编辑器拖动调整。
- 动态服务器时间只附加到本轮 user 正文末尾，不再在提示词开头插入 system 时间；不参与世界书激活、不写入原始正文，保留预设／角色／历史的稳定前缀。历史条目的既有时间标签与截取策略保持不变。
- 对话支持选图与输入框粘贴图片、待发送预览／移除、只发图片或图文一起发送；每轮最多 4 张，每张 5 MB，支持 PNG／JPEG／WebP／GIF。图片作为 data URL 随 SQLite 消息 JSON 保存，历史、原地重新生成、编辑重发与分支保留附件；Provider 转为 OpenAI-compatible text／image_url 内容数组。时间注入与文本世界书扫描保留，搜索判断只接收附件数量，不把图片编码作为文字发送。
- 服务端追加消息，客户端不能提交全量历史覆盖数据库。每条新消息保存 ID、UTC、timezone、local datetime、source、usage；旧 JSON 仅一次迁移，未知消息时间不伪造。
- 请求 ID 幂等、同会话单次生成、异常重试不重复用户消息；浏览器断开不取消已提交生成。过期请求回收及尝试租约防止迟到回复覆盖重试。
- 原始正文保留；TTS 单独清理 Markdown，朗读接口不调用 LLM、不改消息与用量。支持角色默认 TTS 和单次音色选择，识别 WAV／MP3／OGG／FLAC。
- 会话列表提供删除（确认后永久删除，忙碌时拒绝，子分支保留并解除关联）；AI 菜单「重新生成」原地替换同 ID 回复，仅使用该轮之前上下文，成功后事务替换，失败保留原文及后续消息。重新生成使用独立请求与用量记录。
- 编辑用户消息与重新生成到分支会复制之前历史并在新分支发送；编辑 AI 回复只保存人工文本，不沿用旧 usage。原会话保留，分支默认关闭 Heartbeat。
- Heartbeat 进入相同 Core，模型选择 NO_ACTION / SEND_MESSAGE；后者进入正式会话及后续上下文。忙碌／冷却／静默／日上限在模型调用前检查。
- 采用原计划 Option B 的渐进形式：新增 Core 与 SQLite，复用 WRX Provider／编译器／语音适配器，独立重做主界面。研究 SillyTavern 的注入、前缀分支和消息朗读；Serenity 的后台调度及主动联系；Chatbox 的确认 usage 与估算区分。版本和路径见参考研究。

## 未完成与已知限制

- 总结／向量记忆与独立 Vector Memory 审计按用户要求暂缓；旧向量工具保留但当前 Core 不读取、不自动写入。
- 尚无 PWA／iOS Web Push、微信、云端部署与鉴权。主动消息已进入聊天历史并由开着的页面轮询读取；这不等于手机系统弹窗已完成。
- 真实 LLM、搜索、复刻音色和麦克风链路需用户配置后联调；目前自动测试与浏览器验收使用模拟服务。
- 当前上下文限制为最近 N 条旧消息；时间范围／Token Budget 策略尚未扩展。没有迁移酒馆 Swipe、多模型候选、递归世界书等完整兼容体系。
- 图片需要实际供应商支持 OpenAI-compatible image_url／data URL 视觉请求；未调用真实视觉模型。图片编码随历史和请求记录保存，增加数据库与请求体积；本地文本 token 估算不包含图片 token，底栏仍使用供应商返回的实际 usage。
- SQLite 为当前服务端存储方案，跨主机部署、持久任务队列、分页和长期大规模历史需要后续评估；页面目前加载完整会话。
- requirements 使用范围而非锁文件；TestClient/httpx 弃用警告仍存在，未影响测试。

## 公开仓库与跨电脑启动

`README.md` 提供 Python 环境安装、克隆、启动、离线测试与私有数据迁移步骤。公开代码不包含本机聊天、角色配置或自定义预设；新电脑可生成默认配置，也可停服后私下复制 data。2026-10-01 发布前再次验证：60 项 pytest 通过（1 条既有弃用警告），Python 编译、pip check、三个 JS 语法检查及两个 Node 回归脚本通过；历史三次提交及待发布文件凭据模式扫描未发现真实密钥。

项目正式名称为 `WRX Companion`，公开仓库名为 `WRX-Companion`；页面标题与侧栏品牌同步更新。本地目录沿用现有路径，默认角色「温柔乡」为角色名称，保留已有数据。
