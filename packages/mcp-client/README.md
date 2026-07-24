# MCP Client 包

`packages/mcp-client` 对应目标架构中的 `packages/mcp/client`。当前保留现有包名以避免破坏 import 路径。

## 可以放

- MCP 客户端。
- MCP 工具或资源注册表。
- 与 MCP Server 通信的稳定适配。

## 不可以放

- 具体领域控制逻辑。
- 绕过权限系统的工具调用。
- Agent 私有 prompt。
