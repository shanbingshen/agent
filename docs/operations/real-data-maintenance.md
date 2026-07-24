# 演示/Mock 到真实系统维护地图

本文说明当前哪些能力仍是演示数据、mock 或占位实现，以及后续替换为真实生产能力时应维护的位置和顺序。

## 总览

| 项 | 当前位置 | 当前状态 | 替换维护方式 |
| --- | --- | --- | --- |
| 工业 mock 数据 | `apps/api/arthra/industrial_data/adapters/mock_file.py` | 内置生成最近 24 小时 EMS、电表、空压机确定性数据 | 过渡期用 `INDUSTRIAL_DATA_MOCK_FILE` 指向 JSON；生产切到 `thingsboard` 或 `timeseries_api` |
| 统一工业数据接口 | `apps/api/arthra/industrial_data/` | 所有 Agent 和分析工具只读这一层 | 新数据源实现 `IndustrialDataAdapter` 或接入统一时序 API，不让 Agent 依赖具体 provider |
| AI 负荷预测 mock | `GET /api/v1/load-forecast/mock`、`apps/web/src/App.tsx` | 静态预测曲线，前端标注 mock 服务占位 | 新增真实预测服务/API 后替换前端调用和 DTO，保留只读预警语义 |
| 工厂能耗分析 / 每日摘要 | `apps/api/arthra/daily_summary.py` | 读取统一工业数据接口；轻量模式下底层是 mock | 真实化优先切换工业数据源，摘要算法不直接读时序库或外部数据库 |
| 能量风险预警 | `apps/api/arthra/power/*`、首页洞察卡片 | 15 分钟需量和电能质量来自确定性工具；预测风险仍依赖 mock forecast | 先接真实需量/功率点位，再接真实负荷预测服务 |
| 空压机确定性算法 | `apps/api/arthra/compressor/*` | Python 计算指标、阈值、数据质量，LLM 只解释结果 | 阈值优先改 `COMPRESSOR_*` 配置；点位映射在适配器边界完成 |
| 电力确定性算法 | `apps/api/arthra/power/*` | Python 计算需量、电能质量、异常持续时间 | 阈值优先改 `POWER_*` 配置；需量越限只用 15 分钟滚动需量 |
| RAG 知识资产 | `knowledge/raw`、`knowledge/metadata` | 人工维护的源文件和元数据，不是运行时向量库 | 按领域维护原始资产，通过知识 API 入库到当前租户和工厂 |
| RAG 运行时数据 | Postgres + Milvus | Postgres 保存文档元数据和分片正文；Milvus 保存 chunk 向量和索引 | 生产备份必须同时覆盖 Postgres 与 Milvus；embedding 维度必须与 collection 一致 |
| 后端 API 集成 | `/api/v1`、`/openapi.json`、`apps/api/arthra/api.py` | 外部界面集成契约 | 对外提供 OpenAPI、JWT 登录方式和租户/工厂/角色约束 |

## 推荐替换顺序

1. **先替换工业数据源**：从 `mock` 切到 `timeseries_api` 或 `thingsboard`。此时日报、首页、对话工具、空压和电力分析都会自动读取真实数据。
2. **再替换 AI 负荷预测**：新增真实预测服务，替换 `/load-forecast/mock` 和前端 `LoadForecastMockResponse` 调用。
3. **再维护真实 RAG**：配置正式 embedding 和 Milvus，按租户/工厂上传真实规程、报告、设备说明和客户知识。
4. **最后校准算法**：根据现场合同、点表、单位和工艺习惯调整 `POWER_*`、`COMPRESSOR_*` 阈值和 pointCode 映射。

## 工业数据替换

轻量脚本会临时设置：

```dotenv
INDUSTRIAL_DATA_PROVIDER=mock
```

内置 mock 数据包含 `mock-ems-01`、`mock-meter-01`、`mock-compressor-01`。如果只是临时演示真实历史样本，可准备符合 `MockIndustrialDataSet` 的 JSON 文件：

```dotenv
INDUSTRIAL_DATA_PROVIDER=mock
INDUSTRIAL_DATA_MOCK_FILE=/absolute/path/to/industrial-data.json
```

生产更推荐接统一时序 API：

```dotenv
INDUSTRIAL_DATA_PROVIDER=timeseries_api
TIMESERIES_API_URL=http://timeseries-service:8080/api/v1
TIMESERIES_API_TOKEN=replace-me
```

统一时序 API 至少实现：

| 方法 | 端点 | 返回模型 |
| --- | --- | --- |
| GET | `/devices` | `IndustrialDevicePage` |
| GET | `/devices/{id}/telemetry/latest` | `IndustrialTelemetryHistory` |
| GET | `/devices/{id}/telemetry/history` | `IndustrialTelemetryHistory` |
| GET | `/devices/{id}/attributes` | `AttributeValues` |
| GET | `/devices/{id}/alarms` | `IndustrialAlarmPage` |

历史时序标准 JSON 示例：

```json
{
  "meter_TotW": [
    { "ts": 1784700000000, "value": 95.15 }
  ]
}
```

底层字段名、单位、聚合策略必须在时序 API 或适配器边界收敛为 Arthra pointCode；例如 `active_power_kw -> meter_TotW`。不要在 Agent、LLM prompt 或前端中做点位映射。

## AI 负荷预测替换

当前首页“AI 负荷预测”调用：

```text
GET /api/v1/load-forecast/mock
```

该接口返回固定 `source="mock"` 的曲线，只用于 UI 占位。真实化时建议新增预测服务和后端聚合接口，最小要求是返回：

- 单位：MW 或 kW，必须明确。
- 实际历史曲线、AI 预测曲线、基线曲线、限值曲线。
- 峰值预测、风险时段、置信度。
- 模型或数据状态，不向客户展示内部模型名。

替换前端时，移除“mock 服务占位”文案，并保留“只读预警，不直接下发控制动作”的安全边界。

## 每日摘要和风险洞察

每日摘要入口是 `/api/v1/daily-summaries/generate` 和 `/api/v1/daily-summaries`。实现位于 `apps/api/arthra/daily_summary.py`。

摘要中的最小值、最大值、平均值、用电增量、规则提醒由 Python 确定性计算；LLM 只负责组织中文报告。模型不可用时仍保存确定性摘要。

注意：

- `meter_SupWh` 用电增量会与同窗口 `meter_TotW × 有效观测时长` 交叉校验。
- 若累计电量与功率积分明显不一致，摘要会标记 `invalid` 并拒绝输出错误电量。
- 首页“能量风险预警”同时使用确定性需量指标和当前 mock 预测；真实预测接入前不要把它包装成生产预测结论。

## RAG 维护

`knowledge` 目录是资产源：

```text
knowledge/raw/          原始 PDF/DOCX/MD/TXT/CSV 等资料
knowledge/processed/    解析产物
knowledge/metadata/     设备、标准、客户元数据
knowledge/manifests/    入库记录、版本和索引血缘
```

运行时知识通过 API 入库：

- `POST /api/v1/knowledge/documents`
- `GET /api/v1/knowledge/documents`
- `DELETE /api/v1/knowledge/documents/{document_id}`
- `GET /api/v1/knowledge/search`

生产 RAG 应配置：

```dotenv
EMBEDDING_API_KEY=your-key
EMBEDDING_BASE_URL=...
EMBEDDING_MODEL=...
EMBEDDING_DIMENSIONS=384
VECTORSTORE_PROVIDER=milvus
MILVUS_URI=http://milvus-standalone:19530
MILVUS_TOKEN=
MILVUS_COLLECTION=arthra_knowledge_chunks
```

Postgres 与 Milvus 是一组运行时数据：Postgres 保存文档列表、正文分片、租户/工厂权限；Milvus 保存向量、过滤字段和索引。备份、恢复、迁移和回填必须同时考虑两者。

## 后端 API 对外集成

给第三方界面集成时，优先提供：

- Swagger：`http://<host>:18089/docs`
- OpenAPI JSON：`http://<host>:18089/openapi.json`
- 登录：`POST /api/v1/auth/login`
- 当前用户：`GET /api/v1/auth/me`
- 工厂：`GET /api/v1/factories`
- 设备：`GET /api/v1/devices`
- 遥测：`GET /api/v1/devices/{device_id}/telemetry`
- 告警：`GET /api/v1/devices/{device_id}/alarms`
- Agent 对话：`POST /api/v1/chat`
- 控制计划：`/api/v1/control-plans...`

集成方必须保留 JWT、租户、工厂、角色权限和控制审批语义；不能绕过前端直接调用 ThingsBoard RPC。

## 禁止做法

- 不让 Agent 或 LLM 直接读取数据库、PDF、时序库或 Milvus。
- 不在前端硬编码真实业务指标。
- 不把单位换算、点位映射、阈值判断写入 prompt。
- 不用实时功率或未知周期寄存器替代 15 分钟滚动需量判断越限。
- 不只替换 UI 文案而不替换后端数据源。
- 不删除或绕过控制计划审批、审计和 RBAC。
