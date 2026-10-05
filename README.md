# WRX Companion

基于 FastAPI 的多角色文字陪伴应用，支持流式聊天、图片附件、会话分支、逐条 TTS、联网搜索和后台主动联系。当前版本为 2.0.0-alpha。

## 在另一台 Windows 电脑部署

安装 Python 3.11 或更高版本（推荐 3.12）和 Git，然后执行：

```powershell
git clone https://github.com/LEASE-2473/WRX-Companion.git
cd WRX-Companion
.\start_companion.bat
```

启动脚本自动创建虚拟环境并安装依赖，打开 http://127.0.0.1:2473 。文字聊天需在「模型与语音」配置 LLM 地址、Key 和模型；朗读另需 TTS 配置。

`start_companion.bat` 是唯一启动脚本，会创建虚拟环境、首次安装依赖并启动应用。

也可以手动启动（Windows）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 2473
```

macOS / Linux 创建虚拟环境后使用 `.venv/bin/python` 执行相同 pip / uvicorn 命令。

## 迁移已有角色、预设和聊天

公开仓库不包含 `data/`、API Key、聊天数据库或本机虚拟环境。新部署首次启动会生成默认数据，不能直接恢复旧电脑的自定义配置。

要延续现有数据，先停止两台电脑的后端，通过可信的私有方式复制旧电脑的整个 `data/` 文件夹到新电脑项目根目录，再启动。完整复制包括 SQLite 数据库及可能存在的 WAL / SHM 文件；不要在运行中只复制数据库主文件。该目录包含敏感配置和聊天，请勿上传公开仓库。仅复制代码无需搬运 `.venv/`。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node tests/ui/provider_ui_test.cjs
node tests/ui/reply_format_test.cjs
```

测试使用离线模拟供应商，不代表真实 LLM / 搜索 / TTS 联调已完成。界面和功能说明见 [使用指南](docs/COMPANION_GUIDE.md)。

服务目前没有鉴权，启动默认仅监听本机；公网部署需要另行配置鉴权、HTTPS 和访问控制。已支持角色日记、系统四表、外部世界书与冷热记忆；手机系统通知尚未实现，自主外出功能当前停用。

本地开发的项目上下文、变更记录、规划、讨论及审计文档不随公开版本发布。应用技能与数据库说明分别见 [技能说明](docs/reference/SKILLS.md) 和 [数据库字段](docs/reference/DATABASE_FIELDS.md)。

## 角色工具

蓝牙应用已迁到 `extensions/toy/`，toy由独立仓库管理，主项目下载不包含toy；安装参见 [扩展目录说明](extensions/README.md)。侧栏「扩展与技能」启用后按需启动，用户手动扫描与连接；关闭应用结束播放并退出后台。聊天使用正文 XML，不要求供应商支持原生工具调用。扩展开发见 [接入指南](docs/extensions/DEVELOPER_GUIDE.md)，设备说明见 [Toy](docs/modules/tools/ROLE_TOOLS.md)。

## 项目目录

应用按功能分包，入口保持 `app.main:app`。后端、前端、测试及文档的职责与迁移映射见 [目录索引](docs/PROJECT_STRUCTURE.md)。

## 维护与文件位置

完整导航见[docs/README.md](docs/README.md)，逐文件用途见[docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)，跨模块修改见[docs/MAINTENANCE.md](docs/MAINTENANCE.md)。正式运行资源全部随app分发，七份任务提示词在app/memory/prompts；私人数据仍在data。实验台在experiments，历史说明在docs/archive。
