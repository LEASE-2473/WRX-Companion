# Toy Extension 正式接入

更新：2026-10-05。

业务应用已迁到 extensions/toy，独立监听127.0.0.1:8767。入口 service.py 从自己的 extension.json 读取端口；BLE、参数校验、经典模式和DIY都在扩展内。不导入陪伴 app 模块。

侧栏“扩展与技能”先启用，再按需启动／打开面板。扫描与连接仍由用户手动操作。收起保留运行；关闭取消DIY、尝试STOP、断开并退出。关闭失败显示错误；停用同时撤销模型调用。宿主只管理自己启动的进程，不复用未知端口服务。

模型直接收到启用扩展的 Skill 和运行状态快照，在同一回复正文后输出 toy_call XML；不发送原生tools字段，不为了动作确认补写模型请求。未连接或未就绪时执行器拒绝动作。重生成／编辑重发只允许声明的只读动作；设备连接变化通过 generation 拒绝旧回复。

toy 的 controller 保留参数校验、DIY队列、写入确认、外部接管和取消逻辑。service负责HTTP与BLE。resources保存面板、模式和内部参数定义；这些定义不会作为tools字段发送给LLM。

新设备记录在 extensions/toy/data/records，子进程日志在 data/extensions/toy/service.log。原 data/toy 记录保留原位，不自动搬迁或删除。官方示例依赖根requirements的bleak；第三方扩展可使用自己的环境。

主仓库不包含toy源码；需要设备功能时另行安装完整extensions/toy。app/tools/toy仅保留旧Python导入兼容；旧角色工具启停接口为通用管理器薄包装，新网页统一走/apps/toy/。

当前验证只使用隔离HTTP与模拟BLE对象；真实扫描、连接和物理动作需用户验收。停止写入确认不代表物理测量结果。

完整接入规范见[Extension开发指南](../../extensions/DEVELOPER_GUIDE.md)。
