# 数据库迁移、部署与回滚

更新：2026-10-04。代码与数据必须匹配。详细副本状态见[DEPLOYMENT_SNAPSHOTS](DEPLOYMENT_SNAPSHOTS.md)，字段见[DATABASE_FIELDS](../reference/DATABASE_FIELDS.md)。

## 当前指定服务器成品

remote service prepared/20261004-no-legacy-state/data：29表／197实体列＋4虚拟列，数据库2,281,472字节，1012消息、516请求。四张system_表为空；无旧合表／旧状态／旧分支关系／日记恢复表。四份JSON与SQLite应一起部署。

20261004-system-four-tables基于本机297消息，是不同数据源，不能覆盖服务器。其他含final／ready的目录是中间快照，名称不代表当前适用。既有缺失来源和已清除实录不能恢复。

## 最新数据迁移

如果服务器在快照后产生了新聊天，先停服并取得最新完整data。源目录和输出目录独立，输出目录必须不存在。

```powershell
.\.venv\Scripts\python.exe scripts/compact_deployment_data.py --source-dir "remote service prepared/20261004/data" --output-dir "remote service prepared/新的批次/data"
```

compact只读源库，在副本上迁移身份及JSON引用、请求元数据、图片、分支与系统四表，清理并VACUUM，输出报告和映射。更早旧结构可先用prepare_deployment_data.py生成中间副本，它不代替最终compact。

初始化也支持旧结构迁移，但不等于已经执行离线体积精简。数据库完整性、字段数、来源关系和文件大小应分别核对。

## 停服替换

1. 停止后端，私下备份服务器最新完整data及匹配代码。
2. 核对副本同级data-report.json、data-identity-map.json和data-fingerprint-proofs.json。
3. 部署完整app、requirements.txt和启动脚本；运行提示词现在随app/memory/prompts部署，保留自定义内容。角色配置和聊天数据仍在data。
4. 一起替换完整data，不混用旧身份JSON或WAL／SHM。运行中的SQLite不能只复制主文件；取得一致快照需停服关闭连接或SQLite备份API。
5. 启动后端、刷新网页并清理旧身份的本地选择／待发送请求，勿自动重发旧缓存。
6. 测试正文、时区、记忆、分支、编辑重发／重生成、图片提示与退出；模型及设备另做真实验收。
7. 回滚时停服，并一起恢复旧代码与完整旧data，不能让旧代码读取新schema。

服务默认单worker、回环地址，无业务鉴权；公网部署需另行实现。工具后台按需启动，不因部署或读取设置自动连接蓝牙。

## 保存与清理约定

正文只存messages；requests保存执行关联、usage与独立debug。debug只用于诊断，每会话最多20条结束实录；情绪日志每会话200条／7天，策略在启动及后台每分钟执行，不能把静态规则当作已清理证明。

图片普通注入5分钟／后续5条用户消息窗口；自身失败重试和最新用户编辑重发最长3小时。物理清理保留附件标记，正在生成会话暂缓。删除日记不保存恢复副本。系统四表按角色共享，来源会话只作追溯。
