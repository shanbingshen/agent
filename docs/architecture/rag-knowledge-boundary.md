# RAG 与知识资产边界

## 结论

`knowledge` 是知识资产目录，放原始文件、解析产物、人工元数据和入库记录。`packages/rag` 是代码目录，负责加载、切分、Embedding、检索、重排、引用组装和评测。向量数据库是运行时基础设施，不放在 `knowledge`。

## 目录

```text
knowledge/
  raw/
    shared/
    ems/
    power/
    compressor/
    carbon/
    customer/
  processed/
    documents.jsonl
    chunks.jsonl
  metadata/
    equipment.yaml
    standards.yaml
    customer.yaml
  manifests/
    ingestion.json
    versions.json

dataset/
  agent-eval/
  rag-eval/
  regression/

packages/rag/src/arthra_rag/
  loaders/
  splitter/
  embeddings/
  vectorstore/
  retriever/
  reranker/
  pipeline.py
  evaluation/
```

## 调用规则

Agent 不直接读取 `knowledge`，也不直接访问 Milvus。Agent 通过 `arthra_rag.retrieve(...)` 或 Orchestrator 提供的 RAG Tool 检索知识。

每个 Agent 通过 `config.yaml` 绑定知识域：

```yaml
knowledge_sources:
  - shared
  - compressor
```

检索必须带租户和工厂边界：

```python
from arthra_rag import KnowledgeFilters, RetrievalRequest, retrieve

citations = retrieve(
    db,
    RetrievalRequest(
        query="GA75 E104 故障原因",
        filters=KnowledgeFilters(
            tenant_id=tenant_id,
            factory_id=factory_id,
            knowledge_sources=["shared", "compressor"],
            device="compressor",
            model="GA75",
        ),
    ),
)
```

当前实现使用 Postgres 保存知识文档、分片正文、租户/工厂权限和列表元数据，使用 Milvus 保存 chunk 向量、过滤字段和向量索引。`knowledge_sources`、`device` 和 `model` 已进入稳定契约，后续替换向量库或调整元数据过滤时只修改 `packages/rag` 内部实现。
