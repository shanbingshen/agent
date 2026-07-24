# Services 目录

`services/` 保存辅助运行服务。

## 子目录

- `simulator`：ThingsBoard/工业数据模拟器，用于本地开发和 E2E 验证。

## 规则

- 模拟数据必须与 API 示例和前端展示保持一致。
- 不把生产数据或真实设备凭据写入服务目录。
- 变更遥测 key 时同步测试、README 和前端类型。
