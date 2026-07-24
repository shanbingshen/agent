# Loaders

加载器负责把 Markdown、PDF、DOCX 等知识资产解析为规范文本。

## 规则

- 只做读取和解析，不做权限判断。
- 输出应交给 splitter 或 ingestion pipeline。
- 不在 Agent 目录重复实现 `load_pdf()`、`load_docx()` 或类似逻辑。
