# Schemas

共享 Schema 层保存稳定的 Pydantic 契约。

## 可以放

- API、Agent、MCP、RAG 之间共享的输入输出契约。
- 需要严格校验的跨模块 DTO。

## 不可以放

- 前端临时展示模型。
- 第三方原始 JSON 的长期业务契约。
- 与某个路由强绑定且不会被复用的请求体。
