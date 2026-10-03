# 应用内技能与执行协议

更新：2026-10-04。这里描述WRX应用自己的技能，和Codex客户端技能不同。

## 生效目录

app/skills/runtime.py从app/skills/definitions/<name>/SKILL.md发现技能。当前普通聊天仅开放memory-read和diary-write；explore／reflect封存，event-write已停用。API目录和read_skill均校验允许列表，不能绕过目录直接读取停用技能。网页目前只读，没有逐项启用开关；待办见根TODO。

定义frontmatter含name和description，小写字母／数字／短横线目录名最多64字符。新增说明不自动新增执行能力，后端仍需实现白名单。

## 当前能力

| 调用 | 用途 |
|---|---|
| read_skill | 按需读取允许技能正文 |
| search_memory | 搜当前角色可见的日记、活动、外部书、系统四表；不依赖Embedding，最多5项摘要 |
| read_memory | 按计算或稳定ID读完整内容与来源，检查角色／作用域 |
| append_diary_entry | 新增chat_entry即时日记，不覆盖每日总结 |

save_shared_event不在写入白名单，旧event-write文件仅保留兼容证据，不进入聊天。客观事实与约定通过系统四表独立填表任务维护。

## 模型协议与事务

共享调用格式在app/skills/PROTOCOL.md：

```xml
<app_call name="read_skill">{"name":"diary-write"}</app_call>
```

目录与共享协议进入普通聊天，技能正文按需读取。runtime.stream处理读取调用及有限轮次；write_actions仅解析白名单写入；commit与请求成功、来源写入及memory_action_keys幂等关系位于同一SQLite事务。可见正文清除内部调用块，用户消息不会被当作指令执行。取消或失败不提交半成品；重生成保护必须同时检查chat/core和runtime.commit。

Toy是独立原生设备工具，在app/tools/toy/skill，设备就绪后门控注入，不进入普通技能目录；见[正式设备说明](../modules/tools/ROLE_TOOLS.md)。

修改技能协议时同步runtime、chat/core、定义文件和tests/skills；修改持久来源时同步数据库字段、请求重放及重生成测试。
