# 联网搜索

更新：2026-10-04。运行目录为app/search。

search/service.py适配Tavily或支持JSON结果的SearXNG。配置API目前在chat/routes.py，模型判断与来源注入在chat/core.py；配置界面和每轮模式在static/chat/companion.js及chat-ui.js。

AUTO由模型判断，可能产生额外LLM调用；ON强制、OFF禁止。来源随回复保存，搜索失败明确告知，不允许把失败当作已查证。搜索判断usage与主回复usage分开记录。

图片计数、角色设定、上下文和搜索资料在Core编排，改接口不能只改search/service。回归在tests/search与tests/chat，真实搜索服务需另行验证。

完整文件位置见[目录索引](../../PROJECT_STRUCTURE.md)，修改影响见[维护规则](../../MAINTENANCE.md)。
