# Arthra Platform

## 全局规则

- 使用 Python 3.12。
- 使用 LangGraph 编排 Agent。
- 所有 Agent 通过明确契约通信，不共享隐式状态。
- Agent 不得直接访问数据库。
- Agent 不得直接访问 ThingsBoard 管理接口。
- Agent 使用 MCP/tools 获取受控能力。
- 确定性计算由领域服务完成，LLM 只能解释已经校验的结果。
- 控制动作必须经过 proposed、人工审批和审计链路。

## 代码边界

- 主 Agent 负责路由、会话状态和专家选择。
- 专家 Agent 负责领域解释和调用允许工具。
- 工业数据读取通过统一工业数据接口完成。
- RAG 检索通过 `arthra_rag.retrieve(...)` 或受控 RAG Tool 完成。
- 不允许一个 Agent 修改其他 Agent 的源码、prompt 或配置。
