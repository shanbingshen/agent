# Arthra 知识资产

`knowledge/` 保存业务知识资产。RAG 引擎代码位于 `packages/rag`；Agent 必须调用 RAG API 或受控 RAG Tool，不能直接读取文件或向量库。

## 目录结构

```text
raw/          人工维护的源文件，例如 PDF、DOCX、Markdown 和 TXT。
processed/    入库任务生成的解析文档和分片。
metadata/     人工维护的知识来源元数据。
manifests/    入库批次、版本和索引血缘记录。
```

## 领域范围

知识按 Agent 领域拆分。每个 Agent 的 `config.yaml` 声明自己允许检索的知识域。

```text
raw/shared/       共享标准和能源基础知识。
raw/ems/          EMS 运行与优化知识。
raw/power/        变压器、电能质量和需量知识。
raw/compressor/   空压机手册、故障和维护知识。
raw/carbon/       碳核算和排放因子知识。
raw/customer/     客户专属私有知识。
```

客户知识不得与共享或公开领域知识混放。客户身份、设备台账和运行遥测应进入 PostgreSQL 或时序存储；合同、报告和操作规程可通过 RAG 入库，并必须携带租户和工厂过滤条件。
