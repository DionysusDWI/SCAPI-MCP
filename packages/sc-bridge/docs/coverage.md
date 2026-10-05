# 登记命令覆盖与边界

本表与 sc_bridge/commands.py 为关闭式入口。未登记的命令方块名称和子类型不能经通用工具绕过。

0.5.0新增8条非建筑修改路径及事件/操作API，风险与恢复矩阵见 [operations.md](operations.md)。登记路径已通过LAB验收，专用工具与通用入口共用身份、审计、执行和回读。生物点击已关闭；生物属性采用一次性原生API，旧建筑比较恢复承诺不变。

| 命令名＋子类型 | 参数与影响 | 后端 | 完成／恢复 |
|---|---|---|---|
| place/default | position、value；单格 | 官方 place/default | 回读；局部比较恢复 |
| fill、clear、replace / region | 范围、value/match；百万格内 | 原生调度＋官方放置 | 分批落盘和回读；局部比较恢复 |
| copy、move / region | 范围、destination、rotation、mirror | 完整快照＋登记的方向变换 | 来源全部先读，重叠安全；局部比较恢复 |
| geometry / line、cuboid、sphere、cylinder、cone | 范围、value、hollow | 原生几何＋官方放置 | 实心／空心；局部比较恢复 |
| resource / container、sign、memory、truth_table、furniture | position、value、resource | 原生资源＋官方放置 | 资源回读、重载及模板验证；局部比较恢复 |
| command_config/blockexist | position、query_position、value | 官方条件配置 | 仅无副作用查询配置；局部比较恢复 |
| condition/blockexist | position、value | 原生读取 | matches、actual；无修改 |
| observe / teleport、heading、camera | 位置、角度或目标 | 原生玩家／相机 | 同步完成；无方块恢复任务 |
| observe / measure、screenshot | 范围或无参数 | 原生测量／图像 | 数值或产物引用 |

登记方向变换普通 Cube、Slab、Stairs、Wood、Door、Ladder、Trapdoor、AttachedSign、PostedSign、FenceGate、Dispenser、Torch、Furniture。其他定向类型明确拒绝。家具镜像变换设计内容，旋转调整方向。复杂电路可原样复制；未支持的旋转镜像拒绝，不丢附加数据。

实测状态以 workspace/reports/scapi-mcp-0.2.md 与本次证据为准。lab_verified 只覆盖报告中的测试夹具，不意味着所有方块与组合均已验证。尚需独立确认的边界包括全部方向性子类组合与远端玩家会话；首版拒绝网络状态和分屏写入。

流体、会坍塌的方块和火药桶在地形写入／区域快照时返回 UNREGISTERED_PHYSICS；库存物品和家具内部静态体素可保存。这些物理行为不受局部比较恢复保证，首版不开放仅能完整备份恢复的命令路径。测试世界须使用静态环境并关闭天气：Living 环境在百万格高空施工中生成积雪，实际触发了 CAS 冲突和恢复拒绝；证据与独立清理记录保留。施工还使用原生 TerrainUpdater 互斥，避免光照后台写回与施工竞争。

4 ms 是调度预算；每帧最多4096格、按实测自适应降低批量。单个原生调用和 GC 无法抢占，报告保留超过预算的长尾，不能声称绝对实时保证。
