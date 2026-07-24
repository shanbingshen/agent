# MCP Servers 目录

`mcp-servers/` 保存对外暴露给 Agent 的 MCP Server。

## 子目录

- `energy-data`：只读工业数据 MCP Server。
- `carbon`：碳相关 MCP 预留目录。
- `iot-control`：控制计划 MCP 预留目录。
- `prediction`：预测能力 MCP 预留目录。

## 规则

- 默认只读，控制能力必须走审批和审计。
- Server 不得绕过租户、工厂和设备授权。
- MCP 工具输入输出必须有稳定契约。
