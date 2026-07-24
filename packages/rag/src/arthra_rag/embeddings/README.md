# Embeddings

Embedding 层负责把文本转换为固定维度向量。

## 规则

- 维度必须与 Milvus collection 配置一致。
- 模型调用失败要显式抛出领域可理解的错误。
- 不在这里做租户权限判断。
