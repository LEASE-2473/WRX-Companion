# LLM、TTS、STT、Embedding与Rerank

更新：2026-10-04。运行目录为app/providers。

client.py实现OpenAI兼容LLM、火山STT、HTTP与豆包WebSocket TTS；profiles.py保存data/provider_profiles.json和请求快照；usage.py规范化真实供应商用量；diagnostics.py脱敏异常；routes.py管理Profile、模型列表及连接／调用测试。前端配置在static/settings/app.js，录音播放在static/voice。

五类Profile拥有独立模型结构、集合与API类型，LLM不再包含用途选择。旧llm_profiles中的embedding／rerank读取时自动迁入各自集合，保留ID、Key与记忆绑定；保存后写入schema_version=2。聊天及情绪任务只能从llm_profiles选择；角色记忆可选独立Profile，系统填表留空沿用日记任务模型。角色也可指定聊天和TTS Profile。不要隐式把缺失Profile当作配置成功。

查询模型和检查LLM连接是GET /models；Embedding与Rerank使用独立模型查询逻辑，API URL可填服务根、/v1或完整/embeddings、/rerank接口，模型列表URL支持单独指定；本地无鉴权向量服务允许Key留空，列表不可用时可手动填写模型。真实向量测试分别POST /embeddings、/rerank，不调用聊天接口；真实调用测试、Embedding和TTS会使用相应供应商，不由离线回归代替。读取配置隐藏Key，保存留空保留旧Key。温度0有效，未填保持供应商默认；usage缺失为未知，不能用估算充账单。

Embedding／Rerank HTTP适配在memory/vector_store，因为共享角色记忆召回；所有异常接口都应使用diagnostics脱敏。类型／参数／用量改动需同步models、chat、memory、character、voice以及供应商Node回归。

完整文件位置见[目录索引](../../PROJECT_STRUCTURE.md)，修改影响见[维护规则](../../MAINTENANCE.md)。
