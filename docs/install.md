# 安装、登记与可恢复部署

本项目不包含游戏或命令方块。请分别从README上游链接获取SCAPI 1.9.3.2-MP和命令方块4.1.8。正式验收使用固定官方源码构建，AI兼容包不是等价的官方验收基线；其他环境须自行核对实际版本和加载结果。

## 安装

在Windows解压Release ZIP，运行 `tools/install.ps1`。指定 `-Python <python.exe>`、`-Venv <目录>`可使用自己的解释器与虚拟环境。Release安装仅从随附wheels离线安装两个配套包，先验证SHA256SUMS；脚本不修改全局环境。源码安装会使用pip获取构建依赖。运行 `scapi-mcp --help` 检查统一入口；保留 `sc-bridge`、`sc-mcp` 旧入口。

MCP客户端配置示例（替换绝对路径）：

```json
{"mcpServers":{"survivalcraft":{"command":"C:/SCAPI-MCP/.venv/Scripts/scapi-mcp.exe","args":["--config","C:/SCAPI-MCP/config/lab.local.json","serve"]}}}
```

stdout只输出MCP JSON-RPC。构建、部署和维护命令是独立CLI操作，不在MCP stdio中调用。

## 首次登记

1. 用游戏界面建立独立SC MCP LAB存档，确认实际存档目录与名称，保存并回到菜单。不要默认登记其他世界。
2. 复制config/example.json为lab.local.json；路径相对于配置文件。填写game_dir、独立runtime_dir、artifacts_dir、backups_dir及target.directory（如app:/doc/Worlds/WorldN）。world_token使用新UUID的32位十六进制值；保持validated=false。这些数据只存本地。
3. 关闭明确的游戏实例，运行部署命令。部署核验Project.xml中的名称，创建token标记；已有不同标记时拒绝覆盖。独立导入副本需显式核验来源，不能按名称继承授权。
4. 重新启动游戏，读取status/world-info。保存并卸载目标世界后，通过统一CLI的export-backup取得原生.scworld包；核验包能导入独立副本，计算SHA-256。把备份路径与校验值写入本地配置，再设validated=true。关闭实例后重新部署配置。
5. 加载目标，确认实际身份；本地单人通过isolate-local核验。只有身份、模式、备份及能力均通过的操作可写入，不能把错误或未加载数据当作空气。

## 部署与恢复

```powershell
scapi-mcp --config config/lab.local.json deploy --packages packages --commandblock-package <已取得的4.1.8.scmod>
scapi-mcp --config config/lab.local.json status
scapi-mcp --config config/lab.local.json restore <部署返回的deployment.json>
```

Release的packages目录只含自有sc-agentbridge-0.5.0.scmod。外部命令方块经参数提供；源码构建输出目录则同时包含官方依赖和自有Mod，可不传该参数。版本及包名必须匹配；同包名旧包全部备份后替换，不能双版本同时加载。版本匹配不证明外部包与固定源码构建等价。

部署前关闭所登记实例，禁止按进程名称批量关闭。部署记录保存在backups_dir/deployments，包含目标、原件、前后摘要；恢复比较部署后摘要，外部变化或备份损坏会拒绝恢复。此入口恢复部署文件，不是世界操作回滚。

大任务状态、事件、截图、模板和操作快照均留在配置指定目录。不可回退能力不自动重试；响应丢失先查询持久operation_id。完整风险及字段语义见桥接操作文档。
