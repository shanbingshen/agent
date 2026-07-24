# Memory 包

`packages/memory` 对应目标架构中的 `packages/context/memory`。当前保留现有包名以避免破坏 import 路径。

## 可以放

- 会话记忆配置。
- checkpoint 命名空间契约。
- 上下文压缩策略。

## 不可以放

- 直接数据库查询。
- Agent 专属业务分析。
- 未脱敏的长期敏感信息。
