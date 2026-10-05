# 非建筑只读能力 · 0.3.0

协议仍为3，主机、桥接和 MCP 均需0.3.0。建筑0.2.0已冻结在工作区 `artifacts/sc-bridge/releases/0.2.0/`，其完整验收报告独立保留。新增路径复用身份校验和游戏线程，不调用命令方块的全局玩家缓存。

| 工具 | 参数 | 返回 |
|---|---|---|
| environment_info | player_index=0 | 模式、环境开关、时间模式、日周期、已加载Mod数量 |
| player_state | player_index=0 | 指定玩家的位置、速度、等级、健康及生理属性，原生值与单位 |
| lighting_query | position、player_index=0 | 现有有效区块的0..15原生光照 |
| inventory_read | offset=0、limit=64、player_index=0 | 至多64槽、完整物品值、内容编号、报告数量、下一页 |
| condition_query | name、subtype=default、minimum/maximum 或 mode、player_index=0 | 观察值、单位、原始值、系数、包含端点的判定 |

创造库存使用 creative_supply 标志；非空创造槽的 count_kind 为 creative_supply，数量是游戏报告的虚拟供给，并非可恢复的实物库存。分页读取不是跨帧事务快照；若玩家同时更换物品，调用方需重新读取。未知物品值可以观察，但这不授予复制或写入能力。

## 登记条件

- levelrange/default：等级向零截断；原始浮点等级另返回。
- heightrange/default：玩家实际Y高度，世界方块单位。
- timerange/default：TimeOfDay乘4096后向零截断；不开放 system/worldrun 缓存路径。
- modcount/default：已加载Mod数量，包含端点的范围。
- blocklight/default：指定position光照范围；要求区块为Valid。area子类型未接入，未加载及计算中不是光照0。
- gamemode/default：精确枚举 Creative、Harmless、Survival、Challenging、Cruel、Adventure；使用 mode，无范围参数。
- statsrange/health、food、stamina、sleep、wetness：原生值乘100。
- statsrange/speed：原生步行速度乘10。
- statsrange/attack、defense、temperature：原生攻击、抗伤与温度尺度，系数1。

属性缩放按官方4.1.8浮点计算规则。native_value、scale 与 observed 在同一游戏线程调用中采集。湿度和温度会随帧变化，不能用不同时间的 player_state 强求精确相等。observed_at_utc_ms 标记观察时刻，错误以错误返回，不当作 matches=false。

通用 command 对上述条件接受真实命令名和子类型；数值范围参数使用 range_minimum/range_maximum，避免与建筑区域的 minimum/maximum 坐标混淆。观察路径为 observe/environment_info、observe/player_state、observe/inventory_read、observe/lighting_query。示例：

```json
{"name":"statsrange","subtype":"health","parameters":{"range_minimum":50,"range_maximum":100}}
```

blockchange、creaturedie、点击等事件条件可能写缓存或消费事件，尚未接入；文件访问、世界切换删除、任意脚本及递归文本保持关闭。环境、属性与库存修改尚未实现，也没有借用方块恢复等级作承诺。

## 验证与后续

tests/test_nonbuilding.py 包含闭集输入与通用等价单元检查，以及实验世界单位、分页、身份、双客户端和菜单重载实测；sc-mcp/tests/test_live_stdio.py 通过真实stdio调用新增工具。证据为 artifacts/sc-bridge/mcp-lab/nonbuilding-live.json、nonbuilding-mcp-stdio.json。仅在这些夹具范围内标记 lab_verified，不外推为多人验收。

后续优先级待用户问卷裁决；未答复时继续只读生物、掉落物和光照调查。任何修改能力需另建属性／资源快照、比较写入和冲突恢复契约，实验仍限定SC MCP LAB及独立副本。

上游入口清单为 upstream-command-inventory.json，由 tools/reference_inventory.py 从固定源码生成：67个执行入口、28个条件入口，记录源码行、注释和待审查类别。清单不授予通用入口访问权，子类型仍须逐项人工核对。

## 回退建筑基线

停止并保存登记开发实例后，可从冻结的0.2.0 source.zip加载旧部署模块，将冻结目录中的官方／适配器包作为 deploy_native 的包目录。这样会创建新的部署备份并移除同包名0.3包，无需绕过比较恢复去覆盖多个旧记录。Python桥接和MCP也必须使用同一份冻结0.2源码安装，不能只换游戏包；恢复到0.3同样经当前部署入口并保存原件。不得在游戏运行时替换包。
