# sc-mcp

依赖已安装 sc-bridge，禁止复制桥接源码。stdout 仅输出 MCP JSON-RPC，诊断到 stderr。工具必须声明输入 schema，拒绝非法坐标、未知参数和任意脚本；桥接错误明确返回工具错误。
