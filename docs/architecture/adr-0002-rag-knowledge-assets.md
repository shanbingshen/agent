# ADR-0002: 分离 RAG 引擎与知识资产

## Status

Accepted

## Context

迁移初期曾使用 `data/knowledge` 和 `data/datasets`，边界清楚但日常维护路径过深。生产级多 Agent RAG 仍需要按领域限制检索范围，并保证客户私有知识与公共知识隔离。

## Decision

- 将知识资产放在根目录 `knowledge`。
- 将评测数据放在根目录 `dataset`。
- `packages/rag` 只放 RAG 引擎代码。
- Agent 通过 `config.yaml` 声明 `knowledge_sources`，并通过 `arthra_rag.retrieve(...)` 或受控 RAG Tool 检索。
- 向量数据库作为基础设施管理，本地 Qdrant Compose 片段放在 `deployments/docker/qdrant.yml`。

## Compatibility

现有上传、切分、Embedding 和 pgvector 检索逻辑继续由兼容适配层调用，不修改公开 API、数据库 schema 或前端协议。

## Verification

本 ADR 对应的结构测试位于 `tests/test_architecture_migration.py`。迁移后需运行受影响测试、全量 Pytest 和 Ruff。
