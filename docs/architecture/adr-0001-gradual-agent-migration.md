# ADR-0001：渐进式 Agent 迁移

## 决策

以兼容门面的方式建立 `main-agent`、Gateway、Orchestrator、Scheduler、RAG 与 MCP 包，先保留原业务实现作为委托目标，再逐节点迁移。

## 后果

- 公开 REST、SSE、数据库 schema、checkpoint namespace 和确定性领域计算不变。
- 每个新包可单独测试；现有 `arthra.*` 导入在迁移期间继续可用。
- 只读 MCP 先采用本地回退客户端；控制能力保持现有审批链，不进入首期 MCP。
