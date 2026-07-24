# Tools 包

`packages/tools` 保存可被 Agent、MCP Server 或 Orchestrator 包装的领域工具能力。

## 可以放

- 能源、碳、设备等领域工具的纯适配层。
- 对受控服务的轻量封装。

## 不可以放

- 未授权的控制写入。
- 绕过 API 权限、审计或审批状态机的操作。
- 大段 Agent prompt 或 LLM 合成逻辑。
