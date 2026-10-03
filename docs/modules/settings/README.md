# 全局设置与旧向量兼容边界

更新：2026-10-04。运行目录为app/settings。

settings/store.py管理data/wrx_runtime_settings.json和冻结快照；routes.py组合读取/api/settings并保存全局历史选择。当前历史模式、最近条数或起始时间为全局设置。前端供应商、预设、世界书与设置在static/settings/app.js。

页面共享状态在static/shared/state.js；聊天实际行为在static/chat，语音在static/voice。不要在设置文件重新定义聊天函数覆盖它们。

## 旧JSON向量工具

memory/vector_store保留独立data/vector_memory.json资料库CRUD，vector_routes保留/api/vector-memory兼容接口。首页保留旧vectorPanel DOM和兼容处理，但没有正常入口；当前主聊天召回只使用角色SQLite记忆与系统四表。仅在旧工具中导入／向量化，不代表资料已加入角色聊天。

此兼容接口未删除，以免破坏已有外部调用；没有重新接入聊天，也没有自动迁移旧JSON资料。需要停用或重新接入时独立确认数据与API使用者，更新tests/integration/api_routes.json和相关说明。

JSON配置损坏时当前加载器存在返回默认值的兼容行为，不应把默认返回当作配置已正确恢复；恢复私人文件前先备份。

完整文件位置见[目录索引](../../PROJECT_STRUCTURE.md)，修改影响见[维护规则](../../MAINTENANCE.md)。
