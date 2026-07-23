# energy-data MCP

可用 tools：`energy.list_devices`、`energy.latest_telemetry`、`energy.telemetry_history`、`energy.attributes`、`energy.alarms`。每次调用都必须提供 `scope.allowed_device_ids`，服务会拒绝范围外设备。

该 Server 只读，不提供 `send_rpc`、属性写入或控制计划审批能力。生产 transport 切换到 Streamable HTTP 前，必须补充工作负载认证、请求签名、超时、审计和集成测试。
