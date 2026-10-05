# 独立构建与测试

仓库无需位于游戏目录。两个Python包及C#适配器源于统一仓库，旧独立项目目录不再维护。安装脚本从源码安装两包；Python≥3.10，当前实测3.14。

构建使用独立.NET SDK10.0.401，不改全局环境。准备未修改的SCAPI提交97e29b3e1a5bdc39799bab8f6ba36cf22dd39239和命令方块提交f5bc2ef2c106db28a45d118a9a45387f5fec7c56。SDK、NuGet缓存、上游副本、游戏与输出可位于不同目录：

```powershell
scapi-mcp --config config/lab.local.json build --source-root . --api-source <SCAPI源码目录> --commandblock-source <命令方块源码目录> --sdk <dotnet.exe> --tooling-dir <独立缓存目录> --output-dir <构建输出目录>
```

game_dir由配置明确指定，适配器引用实际游戏程序集；官方命令方块保留上游原有依赖，副本构建不修改参考原件。输出包含自有Mod、外部依赖包和build.json（固定提交、SDK、实际程序集及包摘要）。不把这些上游文件提交或发布为本项目产物。

```powershell
python -m unittest discover -s packages/sc-bridge/tests
python -m unittest discover -s packages/sc-mcp/tests
```

默认跳过真实游戏测试。仅显式LAB配置启用：SC_CREATURE_TEST_CONFIG、SC_OPERATION_TEST_CONFIG、SC_ENTITY_TEST_CONFIG、SC_LIVE_TEST_CONFIG、SC_MCP_LIVE_CONFIG；独立生存LAB使用SC_SURVIVAL_TEST_CONFIG。每套件先核验test_only、名称、token和实际世界。内部夹具不是MCP工具。

生物新增入口：entity_query读取native_id；creature_inspect重新核验并发放120秒目标句柄；creature_patch(target_id,fields)只预检，再operation_submit确认side_effects。字段为health .001–1、walk_speed 0–64、attack_power 0–10000、attack_resilience .001–10000。防御为有效值，适配器处理倍率并将倍率纳入比较。未知组件、死亡/移除目标、玩家、过期/跨客户端/跨会话句柄均拒绝。不点击生物，不持续覆盖。恢复可在同一启动/会话中比较直接字段，不跨重载复用句柄。

生物持久性按原生保存路径验证；walk_speed与attack_resilience不增加适配持久覆盖，health和attack_power也会受自然规则影响。健康自然变化可使计划失效，重新预检不等于自动重放操作。

发布检查使用干净目录：源安装、wheel离线安装、显式路径构建、MCP覆盖、部署与比较恢复。产物从发布提交重建，版本标记及摘要一致后才创建不可移动的标签。不得上传本地配置、世界、凭据或原始审计日志。
