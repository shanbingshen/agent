# Docs 目录

`docs/` 保存架构、运行手册、工具说明和设计决策文档。

## 子目录

- `architecture`：目标架构、ADR 和边界说明。
- `operations`：迁移、部署、真实数据维护和本地运行手册。
- `tools`：MCP、领域确定性工具和外部集成说明。
- `agents`：Agent 插件、契约、协作规范和 Codex 提示词。

## 常用文档

- [本地运行手册](operations/local-runbook.md)
- [演示/Mock 到真实系统维护地图](operations/real-data-maintenance.md)
- [领域确定性工具说明](tools/domain-analysis-tools.md)
- [Codex 协作提示词](agents/codex-prompts.md)
- [RAG 与知识资产边界](architecture/rag-knowledge-boundary.md)

## 规则

- 文档应与当前代码和启动方式同步。
- 涉及日期、版本、端口和 API 路径时写具体值。
- 不在文档中记录真实密钥。
