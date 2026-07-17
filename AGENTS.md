# Arthra Agent 开发约定

本文件适用于整个仓库。任何开发者或编码 Agent 在修改代码前必须阅读并遵守。

## 系统边界

- `apps/api/arthra/agent.py` 只负责能力路由、专家状态和语言解释；确定性计算不得交给 LLM。
- `apps/api/arthra/thingsboard.py` 是唯一允许持有 ThingsBoard 管理凭据的模块。
- `apps/api/arthra/control.py` 是唯一允许调用 `send_rpc` 的业务模块。
- Agent 工具只能读取设备数据或创建 `proposed` 控制计划，禁止直接执行 RPC、属性写入或绕过审批。
- 前端权限提示不是安全措施；所有权限与状态转换必须由 API 再次验证。
- 不得添加删除或覆盖 `audit_events` 的 API、迁移或后台任务。

## 开发命令

```powershell
uv sync --dev
uv run pytest
uv run ruff check apps services tests
uv run alembic -c apps/api/alembic.ini upgrade head
pnpm --dir apps/web install
pnpm --dir apps/web lint
pnpm --dir apps/web build
docker compose up -d --build
```

改动后至少运行受影响模块测试；修改公共 API、控制状态机、迁移或前端类型时运行完整测试和前端构建。

## Python 规范

- 使用 Python 3.12 类型注解、Pydantic v2 和 SQLAlchemy 2.0 风格。
- 所有跨模块、入库前、出 API、进入 LLM 或离开外部适配器的数据必须使用 `StrictModel` 或明确的 Pydantic `RootModel`；禁止新增 `dict[str, Any]` 业务契约。
- ThingsBoard 原始 JSON 只能在适配器解析语句内短暂存在，返回业务层前必须转换为 `thingsboard_schemas.py` 中的模型。
- SQLAlchemy 模型只承担持久化；JSON 列写入前必须由 Pydantic 模型 `model_dump(mode="json")` 生成，API 读取必须经过 `OrmReadModel` DTO。
- 新模型默认 `extra="forbid"`。确需兼容第三方多余字段时，只能在外部投影模型使用 `extra="ignore"`，并在进入领域层前收敛字段。
- 业务配置只能来自 `Settings`；禁止散落读取环境变量或硬编码凭据。
- 对外异常使用明确的 FastAPI HTTP 状态；日志和响应不得包含 token、密码或模型密钥。
- 设备数值计算必须可复现、可单测，并保留单位；LLM 输出不得作为控制数值的唯一来源。
- 外部 HTTP 调用设置超时并转换为领域异常；RPC 失败不得自动无限重试。
- 新专家必须声明输入数据、确定性分析步骤、输出结构和允许调用的只读工具。

## TypeScript 规范

- 开启 strict；API 类型集中在 `src/api.ts`，不要在组件间复制冲突类型。
- 所有受保护请求经统一 `api` 函数发送；SSE 流必须处理错误事件与中断。
- 页面必须保留加载、空数据和失败状态，并兼容 320px 以上视口。
- 不在浏览器存储 ThingsBoard 或模型凭据；JWT 仅用于当前 MVP，生产认证升级需单独威胁建模。

## 数据库迁移

- 禁止依赖应用启动时 `create_all`；任何 schema 修改都创建新的 Alembic revision。
- 迁移必须同时给出 upgrade 和安全可行的 downgrade；涉及数据丢失的 downgrade 要明确阻止或记录。
- pgvector 维度必须与 `EMBEDDING_DIMENSIONS`、模型字段和迁移一致。
- 控制状态已有审计含义，修改枚举或转换前必须补充迁移与状态机测试。

## ThingsBoard 适配

- 仅通过 `ThingsBoardClient` 使用 REST/RPC，不在路由、Agent 节点或前端拼接 ThingsBoard 管理请求。
- 保持一次 401 后重新认证的有限重试；其他错误立即转为 `ThingsBoardError`。
- 新控制方法默认拒绝。启用时必须同时更新环境白名单、`ControlPolicy` 参数校验、测试和 README。
- 模拟器设备类型保持 `ems`、`meter`、`compressor`，遥测 key 变更必须同步 API 示例和前端。

## 测试与验收

- 路由：五类专家关键词与默认路由。
- 安全：角色限制、计划过期、重复审批、方法白名单、参数限幅和密钥不泄漏。
- 集成：ThingsBoard 登录刷新、设备查询、时序/告警、RPC 成功与失败。
- E2E：模拟器上报 → Agent 分析 → 创建计划 → 人工审批 → RPC → 审计。
- 不允许通过删除或弱化测试来使构建通过；修复原因并补回归测试。

## 提交前检查

1. 查看 `git diff`，确认没有 `.env`、token、密码或无关文件进入提交。
2. 运行 Ruff、Pytest、TypeScript 检查和 Vite build。
3. 若改动 Compose，执行 `docker compose config`；若改动运行链路，执行完整 smoke test。
4. 在交付说明中列出运行结果、未验证项和任何兼容性风险。
