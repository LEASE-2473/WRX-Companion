# Extension 开发与接入指南

更新：2026-10-05。契约版本 1；描述当前实现。模型不使用原生 tools／tool_calls，应用之间使用本机 HTTP。

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
  "has_panel": true,
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

启动探测最多约数秒，失败停止本次创建的进程。调用／关闭等待上限60秒，返回 JSON 最大64 KiB；超时不自动重试。HTTP 非2xx会显示失败；“请求已接收”不代表物理设备已完成动作。

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
