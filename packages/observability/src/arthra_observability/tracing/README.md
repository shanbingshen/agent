# Tracing

追踪目录用于记录 Agent、RAG、工具和 API 调用链路。

## 规则

- 不记录 token、密码或模型密钥。
- 客户模式不得泄漏内部设备 UUID 和原始点位键。
- trace id 应能串联用户请求、工具调用和外部服务调用。
