# SCAPI-MCP

为 Survivalcraft API 1.9.3.2-MP 提供本地 Agent 游戏操作接口。Python MCP通过标准输入输出通信，由C#适配Mod在游戏线程执行；复用命令方块4.1.8与原生API。版本 **0.5.0**，桥接协议 **3**。

## 能力

- 世界、玩家、材料、区域、库存、生物与掉落物查询，测量、相机和截图。
- 异步建筑施工、资源复制、可移植模板、快照和比较恢复，区域上限100万格。
- 事件订阅与历史；环境/气候、玩家属性与覆盖、库存编辑/转移、登记方块交互。
- 生物非致死健康、移动速度、攻击力和攻击抗性的一次性API修改，不点击生物。

仅支持明确登记的本地单人世界。写入先预检、再确认风险；不可回退操作仍有身份校验、审计和回读。超时或重启先查记录，禁止自动重放。不开放任意脚本、文件操作、世界删除或GUI点击自动化。完整范围见[操作契约](packages/sc-bridge/docs/operations.md)和[版本验收](docs/acceptance-0.5.md)。

## 安装与接入

需要Windows、Python≥3.10（实测3.14）、SCAPI 1.9.3.2-MP及命令方块4.1.8。从本仓库Release下载完整安装包并解压：

```powershell
./tools/install.ps1
```

脚本创建本地虚拟环境并安装两个配套Python包；不会修改全局环境或启动游戏。从源码安装也使用该脚本，需可用的Python构建依赖下载源。

复制 `config/example.json` 为自己的 `*.local.json`，填写游戏目录、独立运行目录和实际世界身份。模板默认未验证，禁止直接写入。备份和登记步骤见[安装部署](docs/install.md)。关闭已登记游戏后部署：

```powershell
./.venv/Scripts/scapi-mcp --config config/lab.local.json deploy --packages packages --commandblock-package <外部命令方块包>
./.venv/Scripts/scapi-mcp --config config/lab.local.json serve
```

MCP客户端使用上述 `scapi-mcp` 程序，参数为 `--config`、配置绝对路径、`serve`；工作目录指向解压目录。部署会保存原件与恢复记录，回退使用 `restore <deployment.json>`。

仓库内的 `packages/sc-bridge` 包含桥接客户端与游戏适配源码；`packages/sc-mcp`依赖安装后的桥接包。构建说明见[开发文档](docs/development.md)，无需把仓库放入游戏文件夹。

## 上游与许可

- [Survivalcraft API源码与发布](https://cnb.cool/trk34Organization/SurvivalcraftApi/-/releases)
- [SCAPI命令方块源码](https://gitee.com/SC-SPM/SC-CommandBlock)
- [游戏与Mod制作参考](https://docs.scwk.net/)

本项目Release不附带上游源码、游戏程序集、上游Mod、存档或个人配置。依赖按各自许可获取和使用。本版本自有代码暂不授予开源许可；不撤销远端历史中已经授予的许可，详见[权利与来源说明](NOTICE.md)。
