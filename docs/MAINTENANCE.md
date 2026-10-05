# 项目维护与跨模块检查

更新：2026-10-04。修改代码前阅读根PROJECT_CONTEXT与CHANGELOG，再核对源代码。用户后续指令优先。本文描述维护约定，不替代项目AGENTS规则。

## 当前状态的单一来源

- 根PROJECT_CONTEXT只保留现状、关键边界和最新验证；历史过程写CHANGELOG。
- 模块说明集中在docs/modules；字段定义集中在docs/reference/DATABASE_FIELDS.md；迁移步骤集中在docs/operations。
- 不用“正文仍写旧行为，末尾追加覆盖规则”方式维护现行说明。替换正文的过期段落，必要时将旧文档原样归档。
- app中的SKILL.md、PROTOCOL.md和memory/prompts/*.md是运行资源，修改会影响模型请求。说明写在docs，不移动这些文件到archive。

## 修改影响表

| 改动 | 必须一起检查 |
|---|---|
| 聊天请求、编辑／重发／重生成 | chat/core、store、routes、request_metadata、images；static/chat；tests/chat |
| 上下文顺序、历史范围、预设宏 | chat/core、chat/history、prompting/compiler；memory热区／召回；character；上下文调试与tests/prompting |
| 日记／系统四表 | memory/role、system、schema、system_schema、各routes；skills/runtime；static/memory；字段说明；tests/memory |
| 记忆向量与Rerank | vector_store、role.recall／hot_context、system.vector_ready／hot_context；模型签名、外部世界书冷区与tests/memory |
| SQLite字段或身份 | 全部读写与迁移；scripts的两个部署迁移程序；请求重放、来源、分支、删除；字段说明与tests/integration |
| 角色／会话删除 | chat/store；diary_hooks、角色共享记忆、系统表来源、情绪、请求和图片；检查哪些数据保留 |
| 模型Profile／参数／用量 | providers、models、chat/core、角色记忆、系统记忆、情绪、语音；前端表单与Node回归 |
| 技能 | skills/runtime白名单与事务；定义和PROTOCOL；chat/core；来源引用、memory_action_keys、重生成保护 |
| 设备工具 | extensions/toy、app/extensions、tools/routes、chat/core；前端tools；连接代次、取消、实际动作标记、退出清理 |
| 静态脚本移动 | index.html加载顺序／缓存参数；共享状态、事件绑定、测试读取路径；结构检查和Node启动烟测 |
| 文件或说明移动 | docs/PROJECT_STRUCTURE文件清单、README入口、文档链接、.gitignore、相关测试路径 |

## 前端脚本约定

无构建器，经典脚本共享页面状态。shared/state先定义公共变量；settings提供设置辅助函数；voice绑定录音；companion提供会话与角色；chat-ui负责最终消息视图和文字发送。其余模块随后加载。禁止用同名全局函数覆盖旧实现实现升级；确需替换时修改唯一实现并删除失效版本。

## 验证

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B scripts/check_structure.py
Get-ChildItem app/static -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
Get-ChildItem tests/ui -Filter *.cjs | ForEach-Object { node $_.FullName }
node experiments/emotion-lab/test.cjs
```

pytest使用临时数据库、配置、技能和提示词；不调用真实模型或连接正式设备。涉及模型质量、Safari、麦克风和蓝牙的改动仍需实机验收。禁止把模拟通过写成实机通过。文件清单和文档链接由check_structure检查，新文件须登记用途。
