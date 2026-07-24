# Arthra 编排器

主 Agent 运行时，负责 Checkpointer、主图与 Agent 插件装配。

## 维护规则

- 负责 LangGraph 运行时、checkpoint 和受控节点装配。
- 不直接保存业务数据。
- 不把 RAG 加载、Embedding 或向量库逻辑写进 Orchestrator。
