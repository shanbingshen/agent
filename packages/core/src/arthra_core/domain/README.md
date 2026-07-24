# Domain

领域层保存跨模块共享的业务概念和纯领域规则。

## 可以放

- 不依赖数据库、HTTP 客户端或外部 SDK 的领域对象。
- 可复用的枚举、值对象和确定性规则。

## 不可以放

- SQLAlchemy 模型。
- FastAPI 请求/响应模型。
- Agent prompt、LLM 调用或工具执行逻辑。
