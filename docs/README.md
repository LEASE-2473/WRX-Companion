# 文档导航

更新：2026-10-04。这里是当前维护说明的唯一导航入口。程序会执行／读取的Markdown留在app；普通说明统一在docs。

## 从这里开始

- [整个项目的目录与文件用途](PROJECT_STRUCTURE.md)：包含全部app源码／静态资源／运行提示词的逐文件索引，以及测试、脚本、数据、研究和备份的位置。
- [当前使用指南](COMPANION_GUIDE.md)：启动、聊天、记忆、情绪、语音、搜索和设备工具。
- [跨模块修改规则](MAINTENANCE.md)：修改哪些文件时必须同步哪些模块和验证。
- [当前项目上下文](../PROJECT_CONTEXT.md)：项目当前状态和关键约定。
- [变更记录](../CHANGELOG.md)：只追加已完成修改，不用于替代当前说明。
- [当前待办](../TODO.md)：尚未完成的功能。

## 模块说明

| 功能 | 当前说明 |
|---|---|
| 聊天、历史、分支、图片、请求重试、Heartbeat | [chat](modules/chat/README.md) |
| 日记、冷热记忆、来源与删除 | [角色记忆](modules/memory/ROLE_MEMORY.md) |
| 系统四表、追溯、自动总结、外部世界书 | [系统记忆](modules/memory/SYSTEM_MEMORY.md) |
| 可编辑运行提示词与文件映射 | [提示词](modules/memory/PROMPTS.md) |
| 十二情绪与管家 | [character](modules/character/README.md) |
| 预设、宏与提示词世界书 | [prompting](modules/prompting/README.md) |
| 模型、STT、TTS、用途Profile与usage | [providers](modules/providers/README.md) |
| 录音、实时识别和播放 | [voice](modules/voice/README.md) |
| 全局运行设置 | [settings](modules/settings/README.md) |
| 联网搜索 | [search](modules/search/README.md) |
| 应用技能与调用协议 | [技能参考](reference/SKILLS.md) |
| 角色设备工具 | [Toy正式接入](modules/tools/ROLE_TOOLS.md) |
| SQLite与JSON字段 | [数据库字段](reference/DATABASE_FIELDS.md) |

## 操作、实验与历史

- [数据库迁移与部署](operations/DATABASE_MIGRATION.md)、[部署副本清单](operations/DEPLOYMENT_SNAPSHOTS.md)。
- [独立情绪实验台](experiments/EMOTION_LAB.md)：代码在experiments，不接入正式应用。
- [当前未来规划](planning/README.md)：自主外出保留且停用，技能管理尚未实现。
- [归档索引](archive/README.md)：旧说明、审计、研究、讨论与旧代码，仅作为历史证据。

## 文件状态

modules、reference和operations描述现行实现；planning只描述未完成或封存方向；archive保留当时的原文，可能包含已经失效的路径和规则，不作为施工指令。旧说明与当前说明冲突时，以当前源码及现行说明为准。
