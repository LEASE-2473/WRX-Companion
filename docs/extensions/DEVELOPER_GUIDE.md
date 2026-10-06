# Extension 开发与接入指南

更新：2026-10-05。契约版本 1；描述当前实现。模型不使用原生 tools／tool_calls，应用之间使用本机 HTTP。

## 文档用途与交付目标

本文件是给独立应用开发者及其开发 Agent 的自包含接入规范。开发环境不需要陪伴项目源码，也不需要访问 toy 私有仓库。只需本文件即可开发协议版本1的扩展；最终宿主联调仍需要用户安装并运行 WRX Companion。下面的本地验证只能证明扩展端契约，不能替代模型实际输出或宿主界面验收。

WRX Companion 是运行在用户电脑上的陪伴聊天宿主，默认网页地址 http://127.0.0.1:2473/。扩展是同一电脑上由宿主启动的独立 HTTP 服务；模型不直接访问它。宿主将扩展 Skill 放进聊天上下文，模型回复正常文字及一个 XML 标签，宿主隐藏标签、解析其中的 JSON，再通过 HTTP 请求扩展。扩展执行动作并返回结果，宿主在界面显示，不自动发第二次模型请求。XML 是结构化动作声明，不是可执行源代码。

扩展可以有网页面板，也可以只有后台服务；当前协议两者都必须提供本机 HTTP 端口。无需额外开放公网端口。扩展不得依赖宿主 Python 包、数据库结构或未在本文定义的内部接口；协议不提供聊天历史、角色对象、数据库读写或模型调用服务。如业务需要这些能力，应先另行设计契约，不能猜测宿主内部结构。

交付给用户的目录必须包含 extension.json、Skill、启动程序和安装 README；有第三方依赖时还应包含依赖清单及安装命令。README写清运行环境、依赖安装、端口修改、面板操作、私人数据位置和停止行为。所有文件使用 UTF-8；不要把密钥、数据库、日志、虚拟环境或真实用户数据作为示例交付。Git仓库完全可选，宿主只扫描文件。

## 最小目录

```text
extensions/hello/
  extension.json
  SKILL.md
  main.py
  data/                 # 扩展自行管理的私人数据
```

每个扩展是独立应用，可以使用自己的语言、解释器、依赖和数据库。无需导入陪伴的 app 模块。宿主只维护发现、启停、代理、正文标签识别和请求保护。外层 Git 默认忽略第三方扩展；主仓库只保留 extensions/README.md；toy 也由独立仓库管理。无需初始化或提交 Git 即可开发。

## extension.json

```json
{
  "schema_version": 1,
  "id": "hello",
  "name": "问候示例",
  "icon": "🧩",
  "version": "1.0.0",
  "description": "最小独立 HTTP 应用",
  "entry_cmd": ["{python}", "main.py"],
  "internal_port": 8123,
  "has_panel": false,
  "skill_path": "SKILL.md",
  "invocation": {
    "tag": "hello_call",
    "endpoint": "/api/invoke",
    "read_only_actions": ["state"]
  },
  "shutdown_path": "/api/shutdown"
}
```

- ID 必须与目录名一致：小写英文开头，后续可用数字和短横线，最多64字符。
- tag 必须唯一：小写英文开头，后续可用数字和下划线，最多64字符。不能使用宿主 app_call 或情绪协议标签。
- internal_port 为1024–65535。扩展负责声明与实际监听一致。宿主检查与2473以及其他已发现扩展的重复，启动时报告外部占用；不接管其他程序。
- entry_cmd 是参数数组，不经过 Shell。工作目录固定为扩展根目录。{python} 替换为宿主正在使用的解释器；独立环境可以写自己的解释器绝对路径。引用的 .py 文件和 Skill 必须存在且不能越过扩展目录。
- skill_path 是扩展内相对文件路径，最多64 KiB。启用扩展的说明直接进入普通网页聊天，无需先读 Skill。Heartbeat 与语音入口不开放扩展调用。
- read_only_actions 是真实只读动作，扩展开发者负责正确标记；重生成／编辑重发和已经领取动作的失败重试只允许这些动作。
- endpoint 与 shutdown_path 是扩展内路径，不能包含查询参数、反斜线或父路径。未知 JSON 字段会被拒绝。

首次扫描只校验声明，不启动程序、不连接设备、不测试业务功能。修改端口时同步修改应用监听与 manifest，再点击“重新扫描”；已运行实例先关闭再启动。宿主不会替扩展纠正错误门牌号。

## HTTP 契约

扩展只监听127.0.0.1。宿主启动时提供环境变量 WRX_EXTENSION_TOKEN；所有宿主请求携带 X-Extension-Token，扩展必须校验。此令牌是本机进程之间的访问约束，不是系统沙箱。

| 接口 | 行为 |
|---|---|
| GET /api/health | 快速返回 JSON，例如 {"status":"ready"}；不能做扫描或业务写入 |
| POST /api/invoke | 收到 {"action":"…","args":{…}}；扩展校验动作及参数后执行，返回 JSON |
| POST /api/shutdown | 完成业务关闭后返回 JSON，并退出 HTTP 进程 |
| GET / | 面板页面；has_panel=false 时可不提供 |

启动探测最多50轮（慢失败可能接近20秒），失败停止本次创建的进程。调用／关闭等待上限60秒，返回 JSON 最大64 KiB；超时不自动重试。HTTP 非2xx会显示失败；“请求已接收”不代表物理设备已完成动作。

有设备连接等状态代次的扩展可在 health 返回 generation，调用时宿主会携带 X-Extension-Generation；扩展在执行前校验，避免旧回复控制新连接。toy 已实现这一检查。health 还可以返回最小业务状态用于下轮模型快照；不要返回密钥或无关私人数据，因为这份快照会发送给用户配置的模型。

## SKILL.md 与模型输出

```markdown
# 问候应用
只有需要记录问候时才使用。正常聊天正文之后附加：
<hello_call>{"action":"greet","args":{"text":"你好"}}</hello_call>
text 必须是1–100字字符串。查询状态使用 action=state、args={}。
一次回复最多一个扩展调用；必须有正常正文，不能提前宣称执行成功。
```

标签及参数约定由扩展自己定义并在 Skill 教给模型。外壳固定为 action 字符串和 args 对象；宿主不理解业务参数，不执行任意 Python、Shell 或 SQL。

正文流式显示，XML完整块、未闭合块及残缺前缀均隐藏。只有流完整结束且正文有效后才执行；调用块最多32 KiB，一轮最多一个扩展调用。日记 app_call 可以与正文、扩展调用同轮输出。模型不得为了确认动作再输出读取调用；执行结果通过网页事件显示，不自动续请求。必须先读取数据再回答的记忆读取仍可能产生模型续轮，不能把“一次输出正文与动作”理解为查询结果已经在同轮被模型看到。

## 页面与资源路径

网页访问 /apps/hello/，宿主转发到内部 http://127.0.0.1:8123/。页面使用相对路径：

```javascript
fetch('./api/state', {
  method: 'POST',
  headers: {'Content-Type':'application/json', 'X-Extension-Panel':'1'},
  body: JSON.stringify({})
});
```

CSS、JS、图片也使用相对路径，例如 ./assets/style.css。不要写 /api/state、localhost:8123 或其他根绝对资源路径，否则远程浏览器会访问错误位置。宿主不重写任意 HTML／JavaScript，不开放调用及关闭端点的网页代理。代理支持GET、POST、PUT、PATCH、DELETE，单个请求体最多1 MiB；不支持WebSocket、SSE长连接、Cookie转发或自动重写重定向。当前官方 toy 面板使用普通 HTTP 轮询。

复用主界面的柔和背景、圆角卡片及清晰按钮；可在 iframe 内保留应用自己的布局。宿主扩展大厅沿用既有样式，不要求第三方依赖宿主 CSS。

## 可运行的最小后端

将下面内容保存为 main.py，与前述 manifest 和 Skill 放在同一目录；仅使用 Python 标准库。

```python
import json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

manifest = json.loads(Path('extension.json').read_text(encoding='utf-8'))
token = os.environ['WRX_EXTENSION_TOKEN']

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get('X-Extension-Token') != token:
            return self.reply(403, {'error':'拒绝访问'})
        self.reply(200 if self.path == '/api/health' else 404,
                   {'status':'ready'} if self.path == '/api/health' else {})

    def do_POST(self):
        if self.headers.get('X-Extension-Token') != token:
            return self.reply(403, {'error':'拒绝访问'})
        if self.path == '/api/shutdown':
            self.reply(200, {'closed':True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path != '/api/invoke':
            return self.reply(404, {})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32768: raise ValueError('大小错误')
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict) or set(value) != {'action','args'}:
                raise ValueError('字段错误')
            if value['action'] == 'state' and value['args'] == {}:
                return self.reply(200, {'status':'ready'})
            args = value['args']
            if value['action'] != 'greet' or not isinstance(args,dict) or set(args) != {'text'}:
                raise ValueError('未知动作或参数')
            if not isinstance(args['text'],str) or not 1 <= len(args['text']) <= 100:
                raise ValueError('text必须为1–100字')
            self.reply(200, {'accepted':True,'text':args['text']})
        except (ValueError, TypeError, KeyError) as exc:
            self.reply(400, {'error':str(exc)})

server = ThreadingHTTPServer(('127.0.0.1', manifest['internal_port']), Handler)
try: server.serve_forever()
finally: server.server_close()
```

这个示例没有面板，应把 manifest 的 has_panel 改为 false。在宿主“扩展与技能”里重新扫描、启用即可；启动或模型调用时拉起，不依赖独立项目的 Git 状态。

## 接入验收与边界

先检查文件规范，再用隔离数据验证启动、HTTP调用、正文隐藏和关闭；设备验收由扩展开发者另行进行。安装独立toy后，可在它的extension.json、service.py与skill/SKILL.md查看官方示例；安装入口见[扩展目录说明](../../extensions/README.md)。

停用撤销调用；关闭应用撤销生成中调用，但扩展仍保持启用，之后可以再次按需启动。宿主只关闭自己启动的进程。外部副作用领取记录在请求 execution 内；超时或取消后的结果可能不确定，不保证恰好一次，更不能保证断电或崩溃时物理停止。扩展必须实现自己的业务幂等、权限与退出清理。扩展是本机可信代码，不应安装未知来源程序；宿主不提供操作系统级沙箱。

## 开发 Agent 的实施流程（没有宿主代码也适用）

1. 确定扩展 ID、唯一 XML 标签、监听端口和用户需要的动作；为每个动作列出参数类型、必填项、范围、失败条件、是否有副作用以及响应结构。
2. 编写 manifest。无面板设置 has_panel=false；有面板实现 GET /，把业务面板接口与 /api/invoke、/api/health、关闭接口分开。不要将模型调用端点同时用作面板业务端点。
3. 实现本文的启动环境和 HTTP 契约，业务调用必须经过自己的参数校验。实现健康接口、关闭清理及必要的业务幂等；不要启动后自动扫描、连接设备或产生业务副作用。
4. 写 Skill，明确何时调用、何时不调用、所有动作与参数、一个正确示例及失败时不能宣称成功。不要要求模型调用原生 tools，也不要要求模型在同一回复里知道尚未执行的结果。
5. 按下一节在独立环境启动与验证。无需宿主源码，也无需模型账户；验证失败必须先修复扩展。
6. 交付完整目录和 README。用户将目录放入宿主 extensions/<id>/，安装扩展依赖，网页“扩展与技能”选择扩展页并重新扫描、启用、启动；有面板再打开面板。
7. 由用户在普通网页聊天中触发明确动作，确认正文正常、XML隐藏、结果显示；关闭应用和停用分别验收。不要用真实设备动作测试文件规范。

用于交给 Agent 的任务模板：

> 你只能读取本接入指南，无法读取 WRX Companion 源码。请开发／改造应用为协议版本1的独立 extension。业务需求：[填写]。平台及语言：[填写]。提供完整目录、依赖安装说明、manifest、Skill、健康／调用／关闭HTTP接口，以及独立契约验证步骤；有面板时使用同源代理相对路径。不得导入宿主模块，不使用原生 tool_calls，不运行模型生成的源代码。明确实际验证与尚待用户宿主联调的事项，不能把未验证的功能写成已通过。

## 将已有应用改造成扩展

已有后端可直接增加契约接口，或由独立适配进程包装它的本地 API／库。业务参数转换放在适配层，宿主仍只理解 action 和 args。已有应用只能通过文件或本地调用操作时，也可以让适配进程接收宿主 HTTP 后再进行本地访问。

宿主只启动 entry_cmd 对应的进程，不自动附着到已经运行的外部服务。若旧应用已占用 manifest 端口，宿主会拒绝启动；可以为适配进程选择另一个端口，并由适配进程自行连接已有服务。这两个端口用途不同，manifest 只填写宿主连接的适配进程端口。适配进程关闭时只能清理自己拥有的资源，不应关闭用户独立启动的旧应用。

若旧应用需要同时启动多个进程，entry_cmd 启动一个负责管理它们的入口；该入口负责健康状态、子进程故障、关闭和清理。宿主不递归替扩展管理其业务进程。不要用已启动的外部进程充当宿主拥有的实例。

已有网页中根绝对路径、固定 localhost URL、WebSocket、Cookie登录或重定向不能假设在 iframe 代理下仍可用。应改为相对资源路径、普通HTTP接口及应用自身明确的认证方案；不兼容的功能需要扩展自己改造。没有完成面板适配时设置 has_panel=false，并提供后台能力。

## 独立启动与契约验证

示例后端可以在没有宿主的目录运行。使用 Python 3.12；示例仅依赖标准库。生产中宿主会注入 WRX_EXTENSION_TOKEN；独立开发时由开发者设置测试令牌，所有请求都使用相同令牌。不要把测试令牌当生产常量，也不要无令牌自动放行。

在扩展目录打开第一个 PowerShell 窗口：

```powershell
$env:WRX_EXTENSION_TOKEN = 'local-development-only'
python main.py
```

在第二个窗口执行（端口必须与 manifest 一致）：

```powershell
$extensionBase = 'http://127.0.0.1:8123'
$extensionHeaders = @{ 'X-Extension-Token' = 'local-development-only' }
Invoke-RestMethod "$extensionBase/api/health" -Headers $extensionHeaders
Invoke-RestMethod "$extensionBase/api/invoke" -Method Post -Headers $extensionHeaders -ContentType 'application/json' -Body '{"action":"greet","args":{"text":"hello"}}'
Invoke-RestMethod "$extensionBase/api/invoke" -Method Post -Headers $extensionHeaders -ContentType 'application/json' -Body '{"action":"state","args":{}}'
Invoke-RestMethod "$extensionBase/api/shutdown" -Method Post -Headers $extensionHeaders -ContentType 'application/json' -Body '{}'
```

预期依次得到 ready、accepted与text、ready、closed；随后第一个窗口进程结束。这里的英文示例避免Windows PowerShell版本间请求正文中文编码差异；生产HTTP JSON应使用UTF-8。

还应独立验证以下拒绝路径：不带令牌或错误令牌返回403；未知动作、缺少参数、错误类型和越界值返回4xx且无副作用；已占用端口时启动失败；关闭后端口不再监听。使用隔离数据与假设备。小示例使用 ValueError 参数校验，不代表已包含完整业务可靠性、持久化或设备安全方案。

有面板时，模拟宿主访问 GET / 时仍需令牌；直接浏览器访问内部端口会缺少令牌，这是预期行为。可用本地 HTTP 客户端检查 HTML、相对资源和业务接口；完整 iframe／同源代理验证留到宿主联调。代理只转发令牌与 Content-Type，不将 X-Extension-Panel 转给扩展；该标记是宿主检查非GET请求的依据。业务返回不要依赖宿主转发 Cookie、Location 或其他自定义响应头。

## 启动、状态与响应的精确定义

- 宿主以扩展目录为工作目录，entry_cmd 是直接进程参数，不做Shell命令解析；只有完全等于 {python} 的参数会被替换。其他变量或占位符不展开，PATH沿用宿主环境。依赖必须事先安装，宿主不会执行pip/npm安装。使用独立解释器时，应由用户在安装时配置本机路径。
- 声明中的 name、id、entry_cmd、internal_port、invocation 为必需；其余字段默认值见示例与规则。invocation中的tag必需，endpoint默认/api/invoke，read_only_actions默认空数组。推荐显式填写全部字段，不依赖JSON类型转换。当前版本不支持任意额外配置字段；自己的业务配置放另一个文件。
- 健康接口必须返回2xx且内容为合法JSON，建议返回对象 {"status":"ready"}。当前宿主不强制验证status值、扩展ID或协议字段；不要据此认为端口上的任意服务可复用。宿主通过自己启动的进程和每次启动令牌管理实例。启动探测最多50轮，每轮HTTP等待0.3秒、失败后等待0.1秒，可能接近20秒；提前退出则更早失败。不要在health做耗时初始化或设备扫描。
- generation为可选状态代次，建议字符串或整数；设备重连等令旧指令失效的状态变化应更新它。在已运行扩展的聊天准备阶段，宿主读取health作为状态快照并记住generation；首次尚未启动时快照是null。扩展若依赖状态才能调用，应在Skill中明确要求用户先启动／连接，而不是让模型猜状态。
- /api/invoke 的请求JSON只有action与args两项，宿主不发送角色ID、聊天记录、请求ID或通用幂等键。需要业务幂等时由扩展设计args字段并在Skill说明；不能依赖不存在的宿主字段。
- 响应为JSON，2xx表示HTTP层接收成功，界面将标记accepted；宿主不会依据JSON里的success=false自动改成失败。业务拒绝应返回合适的非2xx状态码；异步任务可返回任务ID和受理状态，在面板提供后续查询，不得声称物理动作已经完成。当前宿主对非2xx错误不保证展示完整业务JSON错误体。
- 关闭请求体为{}。先完成必要清理再返回2xx JSON，随后退出；宿主收到响应后最多再等待5秒，仍未退出可能终止进程。清理失败返回非2xx，宿主显示关闭未确认，不能把失败写成已安全停止。
- health／invoke／shutdown结果最多64 KiB，调用和关闭HTTP等待上限60秒。面板代理请求最多1 MiB、等待60秒；不要依赖无限响应或长连接。需要长任务时扩展自己采用任务受理＋轮询。
- XML必须使用无属性的完整标签 <hello_call>JSON</hello_call>；不要放在Markdown代码块或转义成HTML实体，不要使用多个调用块。JSON只有action字符串及args对象，不支持任意XML子节点。标签长度和保留名以本文规则为准。
- 宿主当前检查2473端口冲突，即使用户用其他端口启动宿主也不能把2473分给扩展。不同扩展重复端口或标签会在扫描时同时报错，停用也不能绕过声明冲突。

## 交付与验收清单

| 阶段 | 必须交付或确认 | 无宿主代码时能否验证 |
|---|---|---|
| 文件规范 | ID与目录一致、文件存在、唯一标签、端口范围、无额外manifest字段 | 可验证自身文件；与用户其他扩展冲突需宿主扫描 |
| 独立后端 | 测试令牌、health、合法／非法invoke、shutdown退出、依赖安装 | 可以 |
| 面板 | 相对资源、独立业务端点、非GET面板标记、代理限制适配 | 本地部分验证，最终代理需宿主 |
| Skill | 动作与参数完整、正文＋单个XML示例、不得提前宣称成功 | 可审阅；实际模型表现需宿主及用户模型 |
| 安装 | 将完整目录置于extensions/<id>/、安装依赖、扫描／启用／启动 | 由宿主用户验收 |
| 业务 | 隔离数据测试、任务结果、幂等与退出清理 | 扩展负责；真实设备单独验收 |

常见故障：扫描失败先检查manifest与文件路径；启动失败检查依赖、解释器、端口和宿主data/extensions/<id>/service.log；面板404检查has_panel和GET /；面板业务503检查相对路径与请求标记；模型没有输出标签检查扩展已启用、Skill是否明确以及是否使用普通网页聊天；动作未执行检查JSON外壳、单调用限制、正文完整性、重生成只读限制及状态代次。重新扫描只重新读取声明，不安装依赖，也不证明业务可用。
