# sc-mcp 0.5.0

Windows 本地单人 MCP stdio 服务，依赖 sc-bridge>=0.5.0,<0.6.0、桥接协议 3。stdout 仅输出 JSON-RPC，无网络监听。生命周期版本 2025-03-26，提供初始化、ping、工具发现和调用。

0.5.0新增操作预检/风险提交/状态/恢复、独立事件游标及环境、玩家、物品和原生方块交互。接口见 [0.5说明](docs/operations-0.5.md)。当前为未冻结候选版，生物点击实测待裁决，pending能力不用于生产。

0.3.0增加 environment_info、player_state、inventory_read、lighting_query、condition_query；只读条件也可通过登记的 command 入口查询。命令数值范围使用 range_minimum/range_maximum，建筑坐标仍使用 minimum/maximum。接口详见 sc-bridge/docs/nonbuilding.md。

    runtime/tooling/venv/Scripts/python -m sc_mcp --config workspace/config/mcp-lab.local.json

六个基础用途保留，新增发现、建筑、复杂资源、模板、观测、异步任务、取消、显式继续及比较恢复。清单与严格 schema 位于 sc_mcp/server.py；执行全部复用桥接包。

建筑工具返回预检任务，ready 后显式 submit。百万格数据分页／文件引用。通用 command 仅接受登记名称、子类型和结构化参数，不接受脚本、命令文本、递归命令、任意文件操作和世界删除。

参数错误为 JSON-RPC 参数错误；游戏错误为 isError=true 并保留错误码。超时不重发修改，先查任务和中断记录。身份、会话、路径、玩家与启动均校验，拒绝多人、分屏及未知网络状态。

接口见 sc-bridge/docs/api.md，边界见 docs/coverage.md，实测见 workspace/reports/scapi-mcp-0.2.md。测试仅使用 SC MCP LAB，不自动转向 SSGC。

0.4.0新增 entity_query 与 pickable_query：仅活动对象，短时不可变快照分页，游标绑定客户端和世界会话。不得用观察编号授权修改；接口见 sc-bridge/docs/entities.md。
