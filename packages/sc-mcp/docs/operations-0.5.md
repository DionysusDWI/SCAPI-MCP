# 0.5.0 MCP 接口

本地 Python stdio，依赖安装的 sc-bridge 0.5.0，协议3。stdout 仅 JSON-RPC。工具列表的 inputSchema 为闭集；无任意脚本、文件、世界删除、输入模拟、生物主动交互或任意物品使用入口。

新增专用预检：environment_patch、climate_patch、player_patch、player_override、inventory_edit、inventory_transfer、interact_block。新增公共流程：operation_preflight、operation_submit、operation_status、operation_restore、operation_cancel。新增事件：event_subscribe、event_poll、event_unsubscribe、event_history；climate_query 补充列气候观察。所有工具默认 player_index=0。

专用工具和通用登记命令共用预检，不执行自由文本。预检返回 operation_id 和精确风险；调用方提交 accept_risk 后才修改。查询结果完成后检查实际 after/error/steps，响应丢失或重启先查询持久 ID，不能重发新的操作去碰碰运气。

参数、单位、完整风险与恢复矩阵见 sc-bridge/docs/operations.md；接口发现以 capabilities 为准。0.5.0登记路径经过LAB验收，生物点击保持关闭；新增creature_inspect与creature_patch通过实际实体句柄执行一次性原生属性修改。未登记路径不能用于自主操作。

相关实测包含实际 stdio 初始化、发现、事件订阅/轮询/注销、环境预检/提交/状态/恢复与历史查询。建筑仍用原有 preflight/submit/job_status/restore_job，不混用非建筑 operation_id 与建筑 job_id。
