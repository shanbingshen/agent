# Apps 目录

`apps/` 保存面向用户、外部集成和运行时编排的应用入口。

## 子目录

- `api`：当前兼容 API，承载 `/api/v1`、认证、知识库、工业数据和控制审批入口。
- `web`：前端应用。
- `arthra-gateway`：目标架构的 HTTP/SSE、认证和租户边界。
- `arthra-orchestrator`：目标架构的 LangGraph 运行时。
- `arthra-scheduler`：日报和定时任务运行时。

## 规则

- API 边界必须再次校验权限，前端提示不是安全措施。
- 领域确定性计算应放在领域服务，不放在前端或 Gateway。
- 不在浏览器保存 ThingsBoard、模型密钥或其他管理凭据。
