## 2026-10-01 — 本地提交与 GitHub 公开发布

- 用户目标：将当前 2.0 项目提交到独立公开 GitHub 仓库，供另一台电脑部署。
- 修改：纳入当前全部 2.0 源码、界面、测试及文档；新增 README 的克隆、启动和停服数据迁移说明；保留既有 WRX 历史，配置当前 GitHub 账户的仓库级 noreply 身份和 origin。
- 文件：当前 Git 工作区全部已修改及未跟踪的 app、tests、docs、requirements、启动脚本、规划文档，新增 `README.md`，更新 `PROJECT_CONTEXT.md`、`CHANGELOG.md`。`data/`、虚拟环境及缓存不上传。
- 验证：pytest 60 passed，1 条既有 TestClient/httpx 弃用警告；compileall、pip check、三个 JS 语法检查、provider_ui_test.cjs、reply_format_test.cjs 通过；git diff --check 通过。扫描待发布文本和三次历史提交，匹配项仅为测试假 Key，未发现真实密钥。
- 未完成与风险：新电脑实际启动及真实供应商联调未执行；公开代码不含本机自定义预设、角色或聊天，需私下迁移 data；服务无鉴权，不应直接暴露公网。推送结果以 GitHub 远程核验为准。

# 变更记录

## 2026-10-01 — 支持图片附件与视觉对话

- 用户目标：对话发送图片，使用已配置视觉 LLM 理解图片。
- 修改：新增图片选择、输入框粘贴、预览与移除、图片消息展示；允许纯图片输入，前后端限制每轮 4 张／每张 5 MB，PNG／JPEG／WebP／GIF；服务端校验 data URL、Base64、体积与格式签名。图片随消息 JSON 持久化，当前／历史编译保留图片，Provider 使用 text／image_url 数组；幂等指纹包含附件，重新生成、编辑重发及分支保留图片。搜索判断只读取附件数量；读取过程中禁止发送，跨会话不串入图片，发送失败保留草稿。
- 文件：`app/models.py`、`app/providers.py`、`app/prompt_compiler.py`、`app/companion_core.py`、`app/companion_store.py`、`app/companion_routes.py`、`app/static/index.html`、`app/static/chat-ui.js`、`app/static/chat-ui.css`、`tests/test_images.py`、`docs/images/image-attachment-preview.png`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：pytest 60 passed，1 条既有 TestClient 弃用警告；新增回归覆盖纯图发送、持久化／读回、图片历史、重新生成与分支／编辑附件、幂等与冲突、非法附件、模拟供应商 HTTP 请求实际 image_url 内容。node --check chat-ui.js 与既有 reply_format_test.cjs 通过，compileall app 通过。独立浏览器页面确认图片按钮、选择附件后缩略图与移除按钮可见，点击移除后图片节点为 0；保存截图，未发送消息，临时页关闭。
- 未完成与风险：未调用真实视觉 LLM；要求供应商支持 OpenAI-compatible image_url 的 Base64 data URL。图片随原始消息与请求记录保存，会增加数据库／网络体积；本地文本 token 估算未包含图片 token，真实 usage 仍由供应商提供。旧历史不变，无提交／推送。

## 2026-10-01 — 精简聊天顶部控件

- 用户目标：删除顶部 Idle 显示和无意义的 Heartbeat 入口。
- 修改：删除顶部状态节点与重复的主动联系按钮；status 更新函数容忍节点不存在，避免发送／播放期间空节点异常；左侧主动联系入口及功能保留。
- 文件：`app/static/index.html`、`app/static/app.js`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：`node --check app/static/app.js`、`node --check app/static/chat-ui.js` 通过；Python 静态断言与本机 2473 实际 HTTP 页面检查确认顶部控件移除且左侧入口保留。
- 未完成与风险：未做浏览器视觉验收、未调用模型；已打开页面需刷新载入新 HTML／JS。

## 2026-10-01 — 移除预设语音模式约束并确认 TTS 过滤

- 用户目标：不再需要实时语音模式，文字回复允许分块，转 TTS 时由后端清理标记。
- 修改：删除统一自检的语音模式项与文字格式末尾语音分支，重排自检编号；默认预设禁用 Voice Output 条目及顺序项，保留旧代码与条目供以后选择。
- 文件：`data/wrx_prompt_presets.json`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：`.venv\Scripts\python.exe -` 配置 Pydantic 校验及 normalize_voice_reply 实际断言通过；确认粗体清理与 `<|next_message|>` 替换换行。源码确认逐条朗读接口在 synthesize 前调用该函数。
- 未完成与风险：未调用真实 TTS；旧实时语音代码未删除，当前默认预设不再针对其约束输出。无需新增过滤实现。

## 2026-10-01 — 合并回复自检并移至历史之后

- 用户目标：所有自检合并一个可拖动条目，置于 Chat History 后，优先保证模型注意力。
- 修改：从 DateTime 与文字回复格式抽出自检段，新增启用的 system 条目「回复自检」（replySelfCheck），统一时间消息头、文字分块、语音与最终正文检查；prompt_order 放在 chatHistory 后。原规则、正反例、时间理解及正常排版例外保留。
- 文件：`data/wrx_prompt_presets.json`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：`.venv\Scripts\python.exe -` 完整 Pydantic 配置校验与 web／voice 实际编译断言通过；最终消息为统一自检 system，前一条为本轮 user 及时间后缀，自检仅出现一次，原两条自检段已移除。
- 未完成与风险：未调用真实模型验证注意力或缓存命中；自检仍为提示词约束。历史后条目无法形成跨变化历史的稳定缓存前缀，具体命中由供应商决定；条目可由用户拖动调整。

## 2026-10-01 — 强化日常聊天分块规范

- 用户目标：日常回复不再用空行冒充分开发送，明确使用 `<|next_message|>` 并在输出前自检。
- 修改：仅改默认预设 textReplyFormat 内容；日常单气泡连续一段，需要多段发送时必须用分隔符；加入截图对应的合并／拆块正反例，禁止以“一条消息不用拆”解释空行多段，要求反馈后直接纠正；保留列表、代码、诗歌与详细说明正常排版及语音不使用标记约定。
- 文件：`data/wrx_prompt_presets.json`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：`.venv\Scripts\python.exe -` 完整 Pydantic 配置校验、web／voice 编译断言均通过，并确认配置只有目标条目内容改变；`node tests/reply_format_test.cjs` 分块、所有标记分片隐藏与用户正文保留检查通过。
- 未完成与风险：未调用真实模型；提示词约束仍依赖模型遵守，没有新增程序过滤或改写历史。固定预设变更会改变缓存前缀；仍允许自然的一条短回复，不强制每轮拆块。

## 2026-10-01 — 用具体示例与内部自检约束时间标签输出

- 用户目标：保留 overview 规定的历史正文时间注入与真实时间感，只在预设中强调禁止自行生成消息时间头，并要求发现错误时删除重写。
- 修改：仅增强「WRX 最小默认预设」DateTime 内容；加入 ISO／普通日期／角色消息头／服务器时间／连续分块五组错误与正确示例，要求理解间隔与跨日关系，在生成前及发送前内部自检，删除消息头并重写后才输出；正常回答时间、用户要求的日志与时间戳引用仍允许。保留条目 ID、顺序、参数及所有时间注入代码。
- 文件：`data/wrx_prompt_presets.json`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：通过 `.venv\Scripts\python.exe -` 执行 Pydantic 全配置校验及 web／voice 实际提示词编译断言；两路径均包含完整新规则，本轮服务器时间后缀保持不变。
- 未完成与风险：未调用真实模型；预设自检属于模型指令，无法保证模型每次遵守，也不代表程序可以控制或验证模型内部思维链。没有程序过滤、自动重试或历史消息改写。新增固定规则会改变缓存前缀。

## 2026-10-01 — 精简底栏与默认折叠联网来源

- 用户目标：底栏紧凑单行，左自动保存、中 Input／Cache／Output、右发送快捷键；不展示历史用量明细；联网来源折叠。
- 修改：删除前端历史用量组件与查询逻辑，保留最新回复三项实际用量，后端记录不变；footer 使用三列 Grid；来源包裹默认关闭 details，摘要为 [联网搜索]。
- 文件：`app/static/index.html`、`app/static/chat-ui.js`、`app/static/chat-ui.css`、`docs/images/compact-footer-search.png`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：node --check app/static/chat-ui.js 通过；真实页面确认底栏三项从左到右且同一行（纵坐标差约 0.5px）；来源初始不可见，点击展开后可见。截图保存，临时浏览器页已关闭，未调用模型。
- 未完成与风险：手机极窄屏未单独验证；自动总结／模型记忆写入仅讨论方案，仍按原约定延期，没有实施记忆或 skill 执行系统。

## 2026-10-01 — 用量移至输入区与重新生成外置

- 用户目标：提高沉浸感，将消息下用量和明细移到输入框下方，「重新生成」与朗读／音色并排。
- 修改：消息节点移除用量与请求明细；输入区下方显示最新回复用量，折叠列表按新到旧查看各轮回复／主动消息与额外搜索判断用量，保留原请求懒加载逻辑。原地重新生成外置，分支生成仍在更多内。
- 文件：`app/static/index.html`、`app/static/chat-ui.js`、`app/static/chat-ui.css`、`docs/images/immersive-usage-footer.png`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：node --check app/static/chat-ui.js 通过；真实页面独立浏览器确认聊天区用量／请求节点数为 0，底部最新一轮显示且展开成功读取回复及搜索判断用量，重新生成位于操作栏直接按钮；保存截图。未发送消息或调用真实模型，临时页已关闭。
- 未完成与风险：未另行验证手机视口；保留 footer 换行适配及明细列表高度限制，本次无后端数据修改。

## 2026-10-01 — 删除会话与原地重新生成

- 用户目标：对话列表支持删除，AI 消息菜单新增「重新生成」，保留分支再生成。
- 修改：列表独立删除按钮与永久删除确认；后端事务删除关联消息、请求及再生成映射，拒绝忙碌会话，子分支保留并解除父关联。原地再生成沿用共享 Core，仅编译目标回复之前的上下文，不追加用户消息，成功后替换同 ID／同顺序回复及 usage；失败保留旧文和后续消息。请求幂等与租约继续有效，新增 SQLite regenerations 表，普通请求 fingerprint 保持兼容。
- 文件：`app/companion_store.py`、`app/companion_core.py`、`app/companion_routes.py`、`app/static/chat-ui.js`、`app/static/chat-ui.css`、`tests/test_regenerate_delete.py`、`docs/images/conversation-actions.png`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：pytest 57 passed，1 条既有弃用警告；node --check app/static/chat-ui.js 通过；新增回归覆盖旧轮回复替换、后续不变、上下文不含目标及后续、请求回放、失败保留、忙碌删除拒绝、分支保留。独立浏览器确认两条会话的删除按钮及 AI「重新生成」可见，未删除真实数据或发起付费生成，临时页关闭。
- 未完成与风险：真实供应商再生成未调用；删除不可恢复，应用提供确认。重写旧轮不会自动改写后续回复，后续内容可能仍引用旧回复；要保持独立发展可使用既有分支功能。Heartbeat 消息无用户输入，不提供该入口。

## 2026-10-01 — 修正搜索参数按 Provider 显示

- 用户目标：豆包配置中不应出现 Tavily 搜索深度。
- 修改：加载配置与切换 Provider 时更新可见字段；Tavily 只显示深度，豆包只显示额外参数，自定义 HTTP 只显示请求模板／鉴权／响应映射，SearXNG 隐藏这些专属字段；补充 hidden 样式避免通用 label 网格覆盖隐藏状态。
- 文件：`app/static/index.html`、`app/static/companion.js`、`app/static/chat-ui.css`、`docs/images/search-provider-fields-fixed.png`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：node --check app/static/companion.js 通过；独立浏览器页确认已有豆包配置加载后隐藏深度，切到 Tavily 显示深度、切到自定义显示 HTTP 控件并隐藏豆包参数，切回豆包截图验证。未保存配置或触发接口，临时页已关闭。
- 未完成与风险：无；本次为字段可见性修正，未改变已保存配置与搜索请求协议。

## 2026-10-01 — 开放联网搜索协议与豆包 Custom 适配

- 用户目标：解决搜索 Provider 仅限 Tavily／SearXNG，接入用户提供的火山方案并允许自定义。
- 依据：读取 https://docs.volcengine.com/docs/Networkedsearch/Networkedsearch-2?lang=zh 的已渲染官方文档（更新时间 2026-09-21）；API Key POST 地址、Query／SearchType／Count、Result.WebResults、Summary／Content 与业务错误结构。
- 修改：新增豆包 Custom Bearer 适配，优先摘要再正文；Query 限 100 字，Count 使用应用来源数；额外 JSON 支持 Filter／TimeRange／QueryControl 等。新增自定义 GET／POST、递归请求模板、Key 请求头及前缀、点分隔响应映射；保留原有两种服务。配置页面完整读写新增字段，保留 Key 留空语义且不回读 Key。未修改当前实际搜索设置。
- 文件：`app/models.py`、`app/search.py`、`app/static/index.html`、`app/static/companion.js`、`tests/test_search_custom.py`、`docs/images/search-configurable.png`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：pytest 54 passed，1 条既有弃用警告；node --check app/static/companion.js 与 compileall -q app 通过。新增模拟 HTTP 测试覆盖豆包／自定义两种方法、中文和引号模板、鉴权、响应映射、业务错误／零结果、配置持久化与 Key 隐藏／保留。独立浏览器页验证 Provider 切换填地址及所有配置控件，未点击保存或测试，已关闭临时页。
- 未完成与风险：未调用真实 API；本次豆包实现为 Custom 文搜文 API Key 路线，不包含 TOP AK/SK 签名、Global、图片和独立问答 Agent。自定义支持字典点路径，不包含任意脚本或完整 JSONPath；仍限制最多 10 个来源。额外模板应填写请求参数，凭据使用独立 Key 字段。

## 2026-10-01 — 整理默认预设并支持连续消息分块

- 用户目标：整体优化「WRX 最小默认预设」，同时实现前端特殊消息分隔符支持。
- 预设修改：保留肥鱼语气与人物约定，减少刻意跑题、重复、反问、固定套路；默认短句单段，详细技术讨论允许展开；时间标签只作元数据。文字格式声明 `<|next_message|>` 可选分隔通常 1–3 条，语音不用标记；固定规则在历史前，保留用户既有顺序调整、ID、启用状态与参数。
- 实现：独立消息块渲染，普通换行不拆消息；流式隐藏不完整标记；复制使用空行代替标记，朗读过滤完整标记。保持一轮一条数据库记录，共享用量与操作，保留原始回复供上下文与调试使用。
- 文件：`data/wrx_prompt_presets.json`、`app/static/chat-ui.js`、`app/static/chat-ui.css`、`app/pipeline.py`、`tests/reply_format_test.cjs`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：预设 Pydantic 校验与实际文字／语音编译检查通过；`node --check app/static/chat-ui.js` 通过；`node tests/reply_format_test.cjs` 验证两块渲染、标记所有流式分片隐藏、用户文本不拆分；Python 断言朗读完整标记过滤通过；`.venv\Scripts\python.exe -m pytest -q`：49 passed，1 条既有弃用警告。
- 未完成与风险：未调用真实模型或做本次浏览器视觉验收；分块共用整轮操作，暂无单块编辑／朗读。语音预设禁止分隔符，语音流式 TTS 未新增跨片段协议解析。预设变更会使旧前缀缓存需要重新建立，历史原文仍可能影响模型风格。无提交或推送。

## 2026-10-01 — 将动态时间移至本轮 user 末尾

- 用户目标：移除开头每轮变化的 system 时间，尽量保留预设、世界书、角色与历史上下文的缓存前缀；保持历史策略不变。
- 修改：删除 Core 头部时间消息；编译器新增可选本轮 user 后缀，将服务器当前时间与时区附在当前正文后。后缀不参与世界书关键词扫描，不修改数据库原始消息，遵循既有预设顺序与深度注入。
- 文件：`app/companion_core.py`、`app/prompt_compiler.py`、`tests/test_companion.py`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：`.venv\Scripts\python.exe -m pytest -q`：49 passed，1 条既有弃用警告；`.venv\Scripts\python.exe -m compileall -q app` 通过。新增 web／voice／heartbeat 三路径回归，确认时间变化仅改变本轮 user 后缀、之前消息逐条一致，调试消息同源，原始正文不变。
- 未完成与风险：未调用真实供应商测量缓存命中；旧请求调试记录保留旧格式，新请求采用新格式。实际缓存仍由供应商规则及完整前缀一致性决定；既有历史截取与时间标签本次不调整。

## 2026-10-01 — 修复聊天输入框窄栏布局

- 用户目标：修复聊天文字输入被挤在左侧、提前换行的问题。
- 原因与修改：textarea 未指定宽度，沿用浏览器默认列宽；补充块级显示、100% 宽度、最大宽度和 border-box，label 允许收缩，输入文字使用正常字重。
- 文件：`app/static/chat-ui.css`、`docs/images/composer-width-fixed.png`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：真实 2473 页面刷新后 DOM 测量输入框与父容器均为 618px、字重 400；独立浏览器页验证中文长句及显式换行，截图确认铺满宽度、工具栏位置正常。仅填写临时测试草稿，未发送消息，验证页已关闭。
- 未完成与风险：本次仅修复输入框样式，无后端行为修改；未另行验证手机视口，宽度使用相对容器比例。无新增已知风险。

## 2026-10-01 — 修复新建 Provider 拉取模型失败

- 用户目标：解决初步测试中 DeepSeek 拉取模型报 Profile 不存在的问题。
- 原因：新 Profile 只保存在浏览器内存，拉取／测试直接请求后端 ID，未提交当前表单；后端又将 Profile 缺失误报为网络鉴权失败。
- 修改：拉取模型、各 Provider 测试先保存当前表单再调用；保存并启用复用同一保存函数。保存测试配置不显式切换已有启用 Profile；首次保存仍沿用存储层默认启用行为。后端缺失 Profile 返回配置阶段失败。
- 文件：`app/static/app.js`、`app/main.py`、`tests/test_provider_setup.py`、`tests/provider_ui_test.cjs`、`PROJECT_CONTEXT.md`、`CHANGELOG.md`。
- 验证：`node tests/provider_ui_test.cjs` 通过，验证提交当前 Key 后再拉取／测试的调用顺序；`.venv\Scripts\python.exe -m pytest -q`：46 passed，1 条既有弃用警告；`node --check app/static/app.js`、`python -m compileall -q app` 通过。离线回归覆盖缺失 Profile 分阶段报告、无 Model 拉取、Key 隐藏与留空保留、已有启用 Profile 保持。
- 未完成与风险：未调用用户真实 DeepSeek 接口，真实网络与鉴权需要页面重试确认；刷新页面会清除未保存表单，应先复制尚未保存的配置。没有提交或推送。

## 2026-10-01 — 统一文字核心、固定功能新增与参考／主界面纠偏

- 用户目标：只暂缓 Memory，实施多 Character、统一服务端会话、Input/Cache/Output、Web Search、Heartbeat／主动消息；按 overview/plan 研究参考项目；2.0 以文字聊天为主，支持消息操作及逐条复刻音色朗读。
- 执行偏差与修正：前段施工跳过参考源码研究、沿用语音主界面；本次明确承认并修正。实际读取 SillyTavern、RECTDEV/Serenity、Chatbox 固定版本源码，记录版本、路径、采用机制与不采用的会话策略。原 overview 保持原文，plan 顶部真实进度重新更新。
- 核心修改：新增 SQLite 事务存储和 CompanionCore；服务端拥有原始消息，保留真实时间与时区，多角色会话／Persona／预设／世界书／LLM 绑定；文字、语音、Heartbeat 共用生成入口，文本不依赖 STT/TTS。幂等请求、失败重试、同会话互斥、过期回收及租约防止重复／迟到覆盖。
- 用量／搜索：读取流式最终和非流式真实 usage，缺失显示 —；兼容不接受 stream_options 的供应商。新增 Tavily／SearXNG 和 AUTO／ON／OFF，搜索来源入库，额外决策调用用量单独记录，搜索失败不假称查证。
- 主动联系：后端调度、数据库领取、NO_ACTION／SEND_MESSAGE、冷却／静默／日上限；主动正文作为正常 assistant 消息进入后续上下文。手机系统通知通道尚未实现。
- 界面与消息：独立文字聊天布局，角色／会话侧栏、顺序消息、底部输入；编辑／重新发送／重新生成／分支／复制、返回父会话；事务复制历史前缀、新消息 ID、编号分支，原会话保留且分支默认不复制 Heartbeat。人工编辑回复不伪造 usage。
- 语音：回复内朗读／单次音色选择、Character 默认 TTS 绑定，复用 WRX TTS；单独清理朗读文本，朗读接口不重跑 LLM、不改聊天，识别音频格式并返回可读失败。保留辅助录音入口，主聊天空格不触发录音；停止自动预热麦克风。
- 修改文件：新增 `app/companion_store.py`、`companion_core.py`、`companion_routes.py`、`heartbeat.py`、`search.py`、`usage.py`、`app/static/companion.js`、`chat-ui.js`、`chat-ui.css`、`start_companion.bat`、`tests/conftest.py`、`test_companion.py`、`test_message_actions.py`、`ui_preview.py`、`docs/REFERENCE_RESEARCH.md`、`COMPANION_GUIDE.md`、`images/chat-ui-offline-preview.jpg`；修改 `app/main.py`、`models.py`、`config.py`、`pipeline.py`、`prompt_compiler.py`、`providers.py`、`app/static/app.js`、`index.html`、`styles.css`、`requirements.txt`、`start_voice_agent.bat`、`IMPLEMENTATION_PLAN.md`、`PROJECT_CONTEXT.md`、本日志。
- 自动验证：`.venv\Scripts\python.exe -m pytest -q`：44 passed（4.45s），1 条 Starlette TestClient/httpx 弃用警告；`python -m compileall -q app tests` 通过；三个 JavaScript 文件分别 `node --check` 通过；`python -m pip check` 无依赖冲突；`git diff --check` 通过（仅 CRLF 提示）；`git remote -v` 为空。未执行提交或推送。
- 浏览器验证：隔离临时数据库、模拟模型／搜索／TTS 的 2474 预览；验证文字发送及刷新保存、新角色与默认音色、Input/Cache/Output／来源、分支重新生成、AI 编辑、空会话、逐条朗读、Heartbeat 设置／立即检查与主动消息。控制台未观察到 error/warn。保存主界面截图；截图中的回复和用量为离线模拟。未导入密钥、未调用付费接口。
- 未完成：总结／向量记忆及独立 Vector Memory 审计按用户要求暂缓；真实 API、搜索、麦克风、复刻音色联调；云端部署、鉴权、PWA／iOS Web Push、微信。不能将本次模拟检查标为原计划完整第一／第二阶段验收。
- 风险与建议：当前完整会话加载及 SQLite 适合现阶段，长期规模／跨主机和分页后续评估；配置仍用原 JSON；前端保留被文字 UI 替代的旧函数，后续可清理。API 未提供公网鉴权，启动默认仅本机；下一步在用户验收后补真实服务与通知通道，不擅自实施 Memory、论坛／外卖。

## 2026-10-01 — 接管 WRX GitHub 基线与 2.0 初步审计

- 用户目标：在温柔乡陪伴计划 2.0 主工作区引入 GitHub WRX，用于本地核对和后续扩展，不更改上游；建立独立的中文连续性文档。
- 主要修改：克隆基线 `96fb793a2fa22866e7f37982c8b02ebf8462af92`，整理代码至主工作区根目录，保留历史、移除 origin、设置仓库级 LEASE 身份。创建隔离 .venv 并安装 requirements；添加核心路径审计及离线基线检查，记录多角色/预设与 iOS 推送的新需求。
- 修改文件：新增 `PROJECT_CONTEXT.md`、`CHANGELOG.md`、`docs/WRX_AUDIT.md`、`tests/test_baseline.py`；在 `IMPLEMENTATION_PLAN.md` 顶部追加真实进度。`PROJECT_OVERVIEW.md` 保持原文；`app/`、requirements 和启动脚本保持上游原样。
- 验证：`.venv\Scripts\python.exe -m pytest -q`：6 passed，1 条 Starlette TestClient/httpx 弃用警告；`.venv\Scripts\python.exe -m compileall -q app`：通过；`node --check app/static/app.js`：通过。安装 requirements 成功。没有真实 API 调用。
- 未完成：独立 Vector Memory/参考项目审计、正式底座决策及功能开发；真实语音、复刻音色与 iOS 通知联调。
- 最终核对：`git diff --exit-code HEAD -- app requirements.txt start_voice_agent.bat .gitignore` 通过，确认业务代码与上游基线一致；`git remote -v` 为空；`git diff --check` 通过；`.venv\Scripts\python.exe -m pip check` 无依赖冲突。Python 实测为 3.12.14。
- 已知风险与后续：浏览器全量覆盖保存、全局角色配置缺乏隔离、JSON 向量库规模限制、rerank top_n 数量校验问题、无云端鉴权；详见审计。先做服务端统一会话核心。未提交、未推送、未修改原工作区。
