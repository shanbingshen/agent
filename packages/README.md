# Packages 架构说明

`packages/` 保存可被 API、Agent、调度器、MCP Server 复用的共享能力。这里不是业务入口，也不是临时脚本目录。

## 分层

- `core`：领域契约、共享模型、异常和跨模块事件。
- `rag`：知识加载、切分、Embedding、向量库、检索和评测。
- `tools`：可被 Agent 或 MCP 暴露的领域工具适配层。
- `mcp-client`：对应目标架构中的 `mcp/client`，负责 MCP 客户端和注册表能力。
- `memory`：对应目标架构中的 `context/memory`，负责上下文记忆和压缩策略。
- `observability`：链路追踪、运行指标、评测结果和可观测性辅助。
- `evaluation`：跨 Agent 或跨包的评测入口，保留为兼容包。

## 规则

- 共享契约优先放在 `core`，不要在 Agent、API 或前端重复定义冲突类型。
- RAG 的加载、切分、Embedding、Milvus 查询和重排逻辑只放在 `rag`，不要写入 Agent 目录。
- 工具包只暴露受控、可测试、可授权的能力；不得绕过 API 的权限和控制审批。
- 包内代码不得直接读取全局环境变量，配置应通过上层 `Settings` 或明确参数传入。
- 新增跨模块数据结构必须使用严格 Pydantic 模型或明确协议，避免 `dict[str, Any]` 作为业务契约。
