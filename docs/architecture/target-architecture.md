# Arthra 渐进式目标架构

当前迁移采用 Gateway、Orchestrator、Scheduler 的逻辑分层。Gateway 保持 `/api/v1` 和 SSE 合约，完成认证、租户设备范围和线程归属校验；Orchestrator 负责 LangGraph 图与 Agent 插件；Scheduler 负责日报与定时工作流。

```text
Web -> arthra-gateway -> arthra-orchestrator -> agents/main-agent
                                       |-> agents/power-agent
                                       |-> agents/compressor-agent
                                       |-> packages/rag
                                       |-> mcp-servers/energy-data
Scheduler -> daily summary -> daily insight workflow
```

第一阶段仍允许 Gateway 和 Orchestrator 同进程装配，避免改变既有 API、SSE、数据库和 checkpoint 行为。后续独立部署时，Gateway 只向 Orchestrator 传递已经授权的内部请求；终端 JWT 不会传入 Agent 或 MCP Server。

`energy-data` 使用 JSON-RPC stdio 的 MCP 最小能力集，只暴露读取设备、遥测、属性与告警的工具和 provider resource。它不包含控制工具，ThingsBoard 凭据仍只位于现有适配器边界。

## Knowledge And RAG Boundary

`knowledge` 保存知识资产，`packages/rag` 保存 RAG 引擎代码，向量数据库是独立基础设施。三者不能混为一个目录。

```text
用户问题
  -> Main Agent
  -> Expert Agent
  -> RAG Tool / packages/rag
  -> Vector DB
  -> citations

knowledge/raw
  -> packages/rag loaders
  -> splitter
  -> embeddings
  -> vectorstore
  -> knowledge/manifests
```

知识资产按 Agent 领域拆分：

```text
knowledge/raw/shared/
knowledge/raw/ems/
knowledge/raw/power/
knowledge/raw/compressor/
knowledge/raw/carbon/
knowledge/raw/customer/
```

Agent 只能检索自身 `config.yaml` 允许的知识域。客户私有知识必须与公共知识分开，并在入库、检索和引用组装时绑定 `tenant_id` 与 `factory_id`。当前运行时使用 Postgres 保存知识文档、分片正文和权限元数据，使用 Milvus 保存 chunk 向量、租户/工厂过滤字段和向量索引；后续替换向量库时只修改 `packages/rag/src/arthra_rag/vectorstore/` 内部实现。
