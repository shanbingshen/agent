# Arthra 数据集

`dataset/` 保存评测和回归数据，不保存生产客户数据。

```text
agent-eval/     Agent 路由与回答质量评测用例。
rag-eval/       检索、引用和有依据回答的评测用例。
regression/     稳定回归测试夹具。
```

## 维护规则

- 样本应脱敏，不能包含真实 token、密码或客户敏感原文。
- 新增评测数据时同步说明来源、适用场景和预期结果。
- 生产知识资产放在 `knowledge/`，不要混入 `dataset/`。
