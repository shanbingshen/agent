# Core 包

`packages/core` 保存 Arthra 平台的共享领域基础设施。它应该保持轻量、稳定、无具体数据源依赖。

## 可以放

- 跨 API、Agent、MCP 和后台任务共享的领域概念。
- 稳定 Pydantic 契约、事件模型和轻量值对象。
- 可被多个包复用的领域异常基类。

## 不可以放

- FastAPI 路由、数据库 Session、ThingsBoard 客户端或 Milvus 客户端。
- 某个专家独有的大段分析逻辑。
- 需要读取 `.env` 或外部服务的运行时配置。

## 边界

`core` 可以被其他包依赖，但不反向依赖 `apps/`、`agents/`、`services/` 或 `mcp-servers/`。
