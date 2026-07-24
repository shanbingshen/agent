# Arthra 网关

Arthra 的外部 FastAPI、认证、租户授权与 SSE 边界。当前通过同进程方式调用 Orchestrator，保持 `/api/v1` 兼容。

## 维护规则

- 外部 HTTP、SSE、认证和租户授权优先在这里收敛。
- 不把专家确定性计算写入 Gateway。
- 不绕过 API 权限校验直接访问底层数据源。
