# Vectorstore

向量库层封装 Milvus 等向量索引实现。

## 规则

- 外部调用方不得直接依赖具体 Milvus SDK。
- collection schema、metric、过滤字段和写入删除逻辑在这里集中维护。
- 检索分数保持“越高越相关”。
