# 0.5.0 非建筑操作与事件契约

协议仍为3，包与 C# 主机必须同为0.5.0。登记能力已通过对应LAB验收；未登记能力不得通过通用入口绕过。测试专用入口不进入 MCP，运行目标仅 SC MCP LAB 与独立副本；SSGC 授权不继承。

## 调用流程

专用工具返回预检，不立即修改。通用闭集路径也调用相同预检：`environment/patch`、`climate/patch`、`player/patch`、`player/override`、`inventory/edit`、`inventory/transfer`、`interact/block`。

1. `operation_preflight(action, parameters, player_index=0)` 或对应专用工具。异步气候扫描需查询至 `ready`。
2. 检查 `identity`、`affected_resources`、`execution_steps`、`risk`、`side_effects`、`persistence`、`backup_required`、`recovery`。预检有效期120秒。
3. `operation_submit(operation_id, accept_risk)`；确认值必须精确等于预检的 `state_change`、`side_effects` 或 `dangerous`。已授权实验世界无需逐次人工批准。
4. `operation_status` 查询持久记录。完成以 `completed`、实际 `after` 和回读为准；赋值成功不等于能力生效。
5. `operation_restore` 仅用于完成且可恢复的操作。`operation_cancel` 仅取消气候任务，在批次边界保留已完成部分。

提交绑定主机启动、世界会话、路径、名称、世界 token 和玩家；世界修改串行。库存两端同时验证，游戏线程执行原生回调。模式、季节和气候先保存、卸载、完整导出与校验，再受控加载同一登记世界。模式/季节修改后再次保存重载，确认库存组件及实际规则。备份/重载超时明确失败，不能换世界继续。

## 风险与恢复矩阵

| 能力 | 影响及副作用 | 恢复等级 | 完整备份 |
|---|---|---|---|
| 玩家一次性属性 | 原生生理状态、等级；自然漂移和伤害不撤销 | direct_fields；精确比较操作后值，冲突拒绝 | 不强制 |
| 玩家覆盖 save/enable/disable | 后续移动、攻击、防御；禁用释放仍归本覆盖所有的直接值 | none；禁用不是撤销历史效果 | 不强制 |
| 真实库存编辑/转移 | 原生槽位回调；转移完成时数量守恒，异常可能部分执行 | best_effort；逐步记录与比较补偿，恢复冲突拒绝 | 不强制 |
| 创造与真实库存互转 | 创造到真实为生成，真实到创造为销毁 | none | 不强制 |
| 门、活板门、开关 | 实际玩家视线/距离的原生交互；声音、电路等连锁不撤销 | direct_fields，仅直接方块状态 | 不强制 |
| 按钮、容器打开 | 按钮脉冲不可倒转；容器可能产生实体/战利品并打开界面 | none | 不强制 |
| 天气启停 | 原生渐变与后续天气行为 | none | 不强制 |
| 普通环境字段 | 原生设置、渲染、时刻；累计游戏时间不倒退 | direct_fields，仅配置字段 | 不强制 |
| 模式、季节 | 维护重载、库存组件/原生规则/生态行为改变 | none | 每次新建完整备份 |
| X/Z列气候 | 温湿度与后续植被/天气；取消保留已执行批次 | none；保留完整备份与批次快照 | 每次新建完整备份 |
| 事件观察 | 独立游标与日志；不消费命令方块缓存，不自动行动 | 不适用 | 不适用 |

普通操作同样先持久记录意图和修改前状态，再执行、回读并记录结果。不可回退不代表可以跳过身份、审计或重复执行。建筑现有快照、比较写入和恢复承诺不变。

## 参数与原生范围

- `player_patch`：level 为原生浮点等级，适配层开放1–100（100是本接口上限，并非原生字段的天然上限）；health .001–1；food/stamina/sleep/wetness 0–1；temperature 0–24。拒绝死亡玩家、健康归零、非有限数与越界。创造模式不接受原生不会保持的生理字段。
- 动态生理字段在实际执行帧捕获并落盘修改前值，防止自然更新使所有预检立即过期；身份、实体、模式、存活状态及稳定字段仍受预检比较约束。恢复不采用这种延迟绑定，必须精确比较操作后值。
- `player_override(mode, fields)`：walk_speed 0–64、attack_power 0–10000、attack_resilience .001–10000，使用当前原生实际单位。save 保存配置；enable 显式施加；disable 释放覆盖；query 查询配置、实际值和错误。配置绑定世界 token、玩家序号与名称。重启/重载不自动启用；保存原生攻击值时使用未覆盖基线，避免把启用状态泄漏进存档。其他 Mod 重新覆盖时停止本覆盖并报告冲突，不持续争抢字段。
- `environment_patch`：weather_enabled、environment_mode Living/Static、adventure_survival、time_of_day_mode Changing/Day/Night/Sunrise/Sunset、time_of_day [0,1)、rain/fog、RGBA天空/降水颜色、game_mode、season [0,1)、seasons_changing、simulation_factor .1–10、day_duration_seconds 60–86400。模式切换必须单独提交。时刻定位要求 Changing 模式，只调整时刻偏移，不回退累计游戏时间。
- 模拟倍率与昼夜长度为会话字段，重载恢复原生默认，不暗中保持或暂停模拟。世界设置、时刻偏移按原生存档持久化。天空/降水颜色使用命令方块登记渲染字段，经实测其原生 Save/Load 会保存；不承诺控制其他 Mod 的渲染。天气报告同时给出启停标志和实际强度，渐变不承诺瞬时完成。
- `climate_patch(minimum=[x,z], maximum=[x,z], temperature?, humidity?)`：端点包含、原生0–15，最多100万列、4096区块；不是玩家体温。扫描与施工不生成地形；已有区块未就绪有10秒上限，超时暂停且不自动续写。每帧扫描最多4096列/4ms，施工初始512列/批并按耗时降低，每批持久化原值、比较、写入、回读与保存后值。原生单次调用不可抢占，4ms不是绝对实时保证。
- `inventory_edit(target, mode, slots?, value?, count?, active_slot?)`：set/add/remove/clear；`target={kind:player}` 或 `{kind:container,position:[x,y,z]}`。set 槽位含 index/value/count，完整物品值不会降为方块内容编号。最多64个涉及槽位。容量不足预检拒绝，不自动掉落、消费、穿戴。创造库存只编辑开放供给槽与选择，数量0/1不是无限供应的真实堆栈。
- `inventory_transfer(source,destination,value,count)`：玩家与登记容器、容器之间；真实库存完成时守恒。炉子等原生变化导致比较失配时拒绝，不停止原生处理。家具物品验证现有内容依赖；未知 Mod 库存或资源拒绝。
- `interact_block(position)`：登记门56/57/58、活板门83/84、开关141、按钮142、容器27/45/64/216。实际选定玩家当前位置、相机、原生射线和距离，遮挡或 detached camera 拒绝。pending 等待原生完成，10秒没有结果为 UNKNOWN_RESULT，不重复触发。容器仅打开原生界面，无 GUI 点击自动化。

## 事件

`event_subscribe(kinds)`、`event_poll(subscription_id,limit=64)`、`event_unsubscribe`、`event_history(after=0,limit=64,boot?)`。订阅从创建时刻开始，每个客户端/订阅独立游标，轮询不会消费其他订阅。内存4096条，溢出 `gap` 明确报告；世界重载与主机重启不恢复订阅。

事件族：block_click、longpress_start/end、item_use、eat、wear、capture。生物点击不在事件订阅范围；客户端、MCP schema和主机均拒绝creature_click，主机不再为此执行生物射线观察。序号须连同 boot 使用；字段包含 UTC 时间、世界身份、可确认玩家/目标/完整物品值、outcome、source、operation_id。source 为 user/agent/system/unknown；当前只在原生输入路径确认用户，在 Agent 操作上下文确认 Agent，其余不猜测。截图不能确认玩家时为 null。无法证明完成阶段时报告 unknown，不把尝试当成功。

原生钩子与限定 Harmony 观察钩子不改变原行为，不消费命令方块短时缓存。方块交互对实际行为方法补充观察，避免原生内联遗漏；pending 完成另行报告。穿戴同时观察原生处理及状态变化；这两种阶段不能当成两次消费。

日志按 boot/会话保存，单文件16 MiB，最多8份；纯文件写入/轮转在后台。日志故障、队列积压溢出、保留缺口和坏行明确报告。历史查询只读，最多64条，重启后可按旧 boot 查询，不恢复订阅，也不触发动作。

用户已裁决避免生物点击，取消该实测和订阅路径；生物属性改变通过闭集命令或原生API直接设置，不以点击间接触发。不提供生物主动交互 MCP 工具。日志故障测试使用显式 LAB 注入；压力填充为合成存储夹具，不能作为真实用户事件证据。

## 中断与部署

operation_id 为持久去重键。同 ID 的完成/失败/中断记录只返回已有结果，旧启动的 ready 计划拒绝再次提交。超时/响应丢失先查询记录；不可恢复操作不自动重试、继续或补扣物品。记录包含已执行步骤、补偿结果及未知阶段。

世界会话变化会清理覆盖启用态和订阅；维护操作成功后记录重绑的新会话。恢复也必须绑定当前目标并比较旧操作后值，不能跨世界、覆盖外部变化或只凭名称授权。

构建：`python -m sc_bridge --config <LAB配置> build`。安装：`deploy-native`；先保存卸载并关闭明确登记实例，部署入口备份原件、摘要、目标和回退记录，禁止同包名双版本。回退：`restore-native <deployment.json>`，比较当前文件与部署后摘要，变化则拒绝覆盖。源码、运行队列、证据、备份分别归属项目、runtime、artifacts、backups；冻结0.2.0–0.4.0原件不覆盖。

## 生物属性

entity_query仅提供观察ID；creature_inspect(native_id)重新核验并发放120秒目标句柄，绑定当前主机、世界会话、客户端及实际实体。creature_patch(target_id,fields)与通用creature/patch均进入非建筑预检/提交框架。只支持非玩家生物的非致死health .001–1、walk_speed 0–64、attack_power 0–10000、attack_resilience .001–10000，均为接口范围。防御表示有效攻击抗性，按原生倍率换算直接字段并比较倍率。未知Mod组件、死亡/移除/未加载目标、跨客户端/会话或过期句柄拒绝。

一次性修改，风险side_effects，恢复direct_fields；不回退后续伤害、移动、生态和自然健康变化。恢复仅在原启动/会话中保持实际实体引用并比较操作后字段；重载后旧句柄不能用于恢复。实测health和attack_power随原生保存，walk_speed和attack_resilience加载恢复原生值；不增加持续覆盖。响应丢失后查询持久操作ID，相同ID不重复触发；重启不重放未完成操作。
