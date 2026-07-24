# Splitter

切分器负责把规范文本切成可检索 chunk。

## 规则

- 保持切分结果稳定、可测试。
- 不调用 Embedding 模型。
- 不写入 Postgres 或 Milvus。
