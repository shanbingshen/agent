# Device Tools

设备工具目录用于沉淀设备只读查询和设备语义归一化能力。

## 规则

- 默认只读。
- 控制类操作必须走 `ControlService` 的 proposed/审批/审计状态机。
- 不直接拼接第三方管理 API 请求。
