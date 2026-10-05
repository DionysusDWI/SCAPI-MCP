# 活动对象观察 · 0.4.0

协议3，新增只读 MCP 工具 entity_query、pickable_query；通用入口分别为 observe/entity_query、observe/pickable_query。全部限定已登记世界、本地单人和选定玩家。

minimum/maximum 为三维整数方块范围，端点包含；对象连续位置采用 min ≤ position < max+1。此边界与命令方块旧 CubeArea 的外侧等号不同，避免相邻格重复归属。最大100万格、256区块列，所有列必须实际 Valid，不自动加载或生成地形。

entity_query 支持 kind=all|player|creature|body 和大小写敏感的 template 精确过滤；creature 排除玩家。返回模板、种类、位置、速度、健康及存在时的玩家信息。pickable_query 支持完整 packed value 过滤，返回物品值、contents、数量、位置及速度。只覆盖活动身体和活动掉落物，排除待移除掉落物；不表示全世界对象，也不涵盖休眠或 Mod 私有集合。

limit=1..64，cursor 默认为空。第一次查询在游戏线程采集纯数据快照；后续页沿用 snapshot_id、observed_at_utc_ms 和相同过滤范围。对象移动或消失不改变该快照。有效期30秒，每客户端最多8份、主机最多32份；扫描源集合上限4096个活动对象，超限明确报错而非截断。游标绑定客户端、操作、过滤参数和完整目标身份；重载与重启失效。观察编号与 native_id 均不能作为持久身份或写入授权。

REGION_NOT_LOADED 表示不能判断有无对象；SNAPSHOT_EXPIRED 需重新查询；CURSOR_MISMATCH 表示客户端、目标或过滤不一致；OBSERVATION_CAPACITY 需等待快照过期。均不重放写入。

验收：tests/test_entities.py 7项通过，其中5项为 LAB 游戏实测；MCP tests 9项通过，包含两个实际 stdio 会话。实验 Wolf 和4个掉落物只按夹具登记引用清理，保存重载后确认无残留。事件条件、实体修改、掉落物修改及 entityexist/dropexist 条件尚未开放。
