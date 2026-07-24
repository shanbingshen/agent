# Evaluation

该目录保留现有 RAG 评测能力。新的评测入口优先放入 `evaluator/`，本目录可继续承载兼容代码。

## 规则

- 不读取生产密钥。
- 不修改线上 Milvus collection。
- 评测数据来自 `dataset/` 或测试夹具。
