# 协议 3 与接口

包版本0.3.0；建筑基线0.2.0已冻结，新增只读接口见 nonbuilding.md。请求 UUID、协议、主机启动身份、到期时间、操作及参数与目标身份同时校验。目标包含世界会话、目录、名称、登记 token、玩家索引与名称。响应匹配 UUID 和启动身份。超时后先查记录，不重新发送修改。

| 组 | 工具 | 约定 |
|---|---|---|
| 基础 | status、world_info、players | 实际版本、加载状态、世界和玩家 |
| 读取 | read_region、read_region_page、resource_query | 包含空气；未加载报错；每页最多4096格 |
| 发现 | capabilities、materials | 登记路径、后端、验收状态、材料属性 |
| 施工 | fill、clear、replace、copy、move、geometry | 异步预检，显式提交 |
| 资源 | resource_write、command_config | 完整资源；命令配置仅登记 blockexist/default 条件 |
| 通用 | command | 登记名称、子类型和结构化参数，无自由 DSL |
| 模板 | template_export、template_inspect、template_import | 导出任务、包检查、导入预检 |
| 观测 | measure、region_statistics、prepare_region、teleport、heading、camera、screenshot、condition | 统计为异步文件结果；角度单位度 |
| 任务 | preflight、submit、job_status、cancel_job、resume_job、restore_job、interrupted_jobs | 取消、显式继续和比较恢复 |
| 小修改 | modify_cells、restore_operation | 最多64格 expected/value，保留旧用途 |

坐标为三整数，Y为0..255，X/Z为±1,000,000。范围 minimum/maximum 包含端点，体积最多百万格；搬移同时约束来源与目标联合影响格数。rotation 为 Y轴0/90/180/270，mirror 为none/x/z。几何含 line/cuboid/sphere/cylinder/cone，hollow 为布尔值；非等宽边界会形成椭圆截面。

container 保存实际槽位、值和数量；库存家具附设计内容；furnace 含 fire_time/heat。sign 保存四行文本、四个 PackedValue 颜色和 URL。memory/truth_table 保存持久配置。furniture 保存 XML 设计链，字段和类型严格登记，分辨率限2..64。TerrainUseCount 是世界共享计数，由游戏按实际使用维护，源世界全局计数不能直接写入目标世界。

状态：scanning、persisting_plan、loading_template、loading_restore、loading_resume、validating_source、waiting_region、ready、running、exporting、completed、cancelled、paused、restored。ready 后120秒内提交；变化或过期重新预检。ready 的 preflight 返回实际影响包围盒、预计修改量、资源类型、所需新增家具设计数、恢复等级与阻断列表。失败时 error 给出阻断原因。

prepare_region 的 timeout_seconds 为0..30，默认立即检查；绑定同一世界会话，返回 ready、missing_chunks、timed_out、wait_seconds、generation_requested=false。施工遇到未加载区块进入 waiting_region，已有区块未在10秒内完成加载则以 REGION_TIMEOUT 暂停；不分配新地形。读取扫描重新开始，未完成快照不用于执行。paused 不自行重试。取消在批次边界生效，保留日志。继续核对完整计划校验及全部相关当前值；恢复拒绝冲突。

错误包括 NO_WORLD、WRONG_WORLD、IDENTITY_MISMATCH、MULTIPLAYER_DISABLED、REGION_NOT_LOADED、INCOMPATIBLE_VERSION、STALE_BOOT、EXPIRED_REQUEST、STALE_PLAN、CONFLICT、RESTORE_CONFLICT、RESOURCE_CAPACITY、UNKNOWN_RESOURCE、UNSUPPORTED_TRANSFORM、MISSING_DEPENDENCY、TEMPLATE_CHECKSUM、PLAN_CHECKSUM、TIMEOUT。

内部有限测试夹具、世界生命周期、原生打包及隔离入口不作为公共 MCP 工具。任意脚本、命令文本、递归、任意文件操作、世界删除和综合生存操作不开放。
