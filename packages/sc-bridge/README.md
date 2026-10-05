# sc-bridge 0.5.0 · protocol 3

0.5.0实现审计非建筑操作、事件流、环境/玩家/库存修改及原生方块交互；接口与风险矩阵见 [非建筑操作契约](docs/operations.md)。生物点击关闭；生物属性API已实现并通过LAB验收，包含非致死健康、速度、攻击与防御的一次性修改。统一安装、构建、部署与MCP入口见仓库根README。0.2.0–0.4.0冻结原件保留。

建筑0.2.0已完成实验验收并冻结。0.3.0新增世界环境、玩家状态、库存分页、光照和登记条件的只读能力，接口及验证见 docs/nonbuilding.md；保持原建筑执行与恢复逻辑。

面向 SCAPI 1.9.3.2-MP 的本地单人游戏桥。C# 适配 Mod 是唯一队列主机；Python 包提供结构化客户端。命令方块 4.1.8 的 place/default 执行放置，原生 API 负责资源、任务、核验和恢复。JS 仅保留游戏引导与诊断；sc_bridge/legacy/ 中的 v2 主机不得部署为新入口。

## 构建与部署

使用工作区内 Python 环境和 .NET 10.0.401 SDK，不修改全局环境。在工作区根目录运行：

    runtime/tooling/venv/Scripts/python -m sc_bridge --config workspace/config/mcp-lab.local.json build
    runtime/tooling/venv/Scripts/python -m sc_bridge --config workspace/config/mcp-lab.local.json deploy-native
    runtime/tooling/venv/Scripts/python -m sc_bridge --config workspace/config/mcp-lab.local.json restore-native backups/deployments/<id>/deployment.json

部署和回退前关闭准确的开发实例。记录保存原件、SHA-256 和恢复方法；回退比较当前文件与备份校验值。旧协议记录仍用 restore-deployment。禁止同时加载同包名的两个 Mod。输出在 artifacts/sc-bridge/build/packages/。

官方命令方块固定为 f5bc2ef2c106db28a45d118a9a45387f5fec7c56，API 固定为 97e29b3e1a5bdc39799bab8f6ba36cf22dd39239；构建拒绝已修改的上游受控源码。适配器引用实际游戏程序集，构建记录包括其校验值。官方源码按原项目依赖构建，包中补齐 Tomlyn.dll。原 AI 兼容包保留在部署备份中，不替代官方验收。

当前安装含 CompatNet，官方命令方块的内存相关兼容路径使用它。适配层另提供仅作用于登记世界的家具回收修复，避免 API 1.9.3.2 将闲置设计置空后再次读取编号导致保存失败。上游源码保持只读。

## 使用与边界

Bridge(Config.load(path)) 保留六个基础用途，新增建筑、资源、模板、定位观测和任务接口。见 [接口说明](docs/api.md)、[覆盖矩阵](docs/coverage.md)。MCP 复用安装的桥接包。

配置路径相对于配置文件。目标含实际目录、名称、唯一 world_token、验证状态与完整备份校验值；部署写入对应世界身份标记。默认开发目标为 SC MCP LAB，生产目标配置不自动变更。每次加载后操作员通过 isolate-local 关闭 MP 自动服务器；远端会话、多人、分屏及未知网络状态拒绝写入。

坐标为世界绝对整数坐标，区域包含端点。普通读取最多 4096 格，直接比较修改最多 64 格。异步任务区域体积最多 1,000,000，大结果分页或文件引用。未加载区块不会当作空气；prepare_region 最多等待30秒检查已有区块，不触发地形生成。施工遇到未加载区块等待最多10秒后暂停，重新预检或显式继续，不自动重放。

流程：预检 → 等待 ready → 显式 submit → 查询进度 → 必要时取消、恢复或继续。预检捕获方块与资源数据，过期或源数据改变时拒绝执行。每批先后台持久化快照，落盘后在游戏线程比较、修改和回读。使用 4 ms 调度预算，自适应批量上限 4096；单个游戏 API 和 GC 无法被抢占，必须保留真实长尾测量，预算不是绝对实时保证。

取消保留完成部分；重启不自动重放。新建筑任务保存带校验值的完整计划，resume_job 显式核对未完成部分，ready 后仍需提交。历史任务没有完整计划时只能恢复。恢复先检查全部冲突，不覆盖其他修改。

.scblueprint 保存版本、依赖、相对坐标、资源内容和校验值，家具按内容映射编号。恢复快照绑定原世界，两者不可互换。瞬时电路信号和计时相位不保证逐帧恢复；未知资源及未登记变换明确拒绝。

## 验证

普通自动化：python -m unittest discover -s packages/sc-bridge/tests -v。
真实游戏测试显式设置 SC_LIVE_TEST_CONFIG 或 SC_FAULT_TEST_CONFIG；百万格另需 SC_MILLION_TEST_CONFIG。测试检查 test_only、名称、实际目录及身份。tests/lifecycle_acceptance.py 分阶段验证保存重载、跨世界编号差异和备份加载。

证据在 artifacts/sc-bridge/mcp-lab/，状态见 workspace/reports/scapi-mcp-0.2.md。未验收边界不得作为 Arch Agent 可靠能力。

0.4.0新增 entity_query 与 pickable_query：仅活动对象，短时不可变快照分页，游标绑定客户端和世界会话。不得用观察编号授权修改；接口见 sc-bridge/docs/entities.md。
