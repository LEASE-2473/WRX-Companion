# 安装与管理 Extension

这里放独立应用，每个扩展一个目录。主仓库仅保留本说明，不包含toy或其他扩展的代码、数据和Git历史。

## 安装

1. 从扩展开发者取得完整应用，把它放在extensions/<id>/；目录名必须与extension.json的id一致。
2. 安装扩展自己的依赖，检查启动命令及端口。
3. 在网页“扩展与技能 → 扩展”点击“重新扫描”，再启用、启动或打开面板。

只下载主项目也能正常使用陪伴功能；没有安装扩展时列表为空。每个扩展自行维护manifest、Skill、HTTP接口及私人数据。

## Toy

Toy是独立Git项目，安装到extensions/toy/。仓库为[WRX-Toy](https://github.com/LEASE-2473/WRX-Toy)，属于私人项目，只有获授权的GitHub账户能访问；普通主项目下载不包含它。获授权后可在主项目根目录执行 `git clone https://github.com/LEASE-2473/WRX-Toy.git extensions/toy`。它依赖bleak，默认端口8767，扫描与连接由用户手动操作。详见toy自己的README.md及主项目的[设备说明](../docs/modules/tools/ROLE_TOOLS.md)。

部署时只复制需要的扩展；不要把扩展的.git、私人data、日志或凭据发布到主仓库。

开发规范见[Extension开发指南](../docs/extensions/DEVELOPER_GUIDE.md)。
