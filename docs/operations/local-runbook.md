# 本地运行手册

本文承接 README 中的长配置说明，覆盖轻量启动、Docker 完整栈、模型配置、Ollama、本地排障和常用 API 示例。

## 环境要求

- Docker Desktop 与 Docker Compose v2。
- 本地开发可选：Python 3.12、uv 0.11+、Node.js 24、pnpm 11。
- 建议至少 8 GB 可用内存；ThingsBoard 首次初始化需要数分钟。

## 轻量启动

轻量脚本使用 LR Python 环境、SQLite 临时库和 mock 工业数据，不需要 Docker、PostgreSQL 或 ThingsBoard。

首次准备：

```zsh
pnpm --dir apps/web install
cp .env.example .env
```

macOS：

```zsh
chmod +x ./start-lr.command
./start-lr.command
```

Windows：

```powershell
.\start-lr-windows.cmd
```

脚本行为：

- 默认使用脚本所在目录作为项目根目录。
- 可用 `ARTHRA_ROOT`、`LR_PY`、`PNPM`、`NODE_BIN` 覆盖工具路径。
- 临时覆盖 `DATABASE_URL` 为 SQLite，`INDUSTRIAL_DATA_PROVIDER` 为 `mock`。
- 同步运行时 `CORS_ORIGINS` 和 `VITE_API_BASE_URL`。
- 默认 API 端口 `18089`，Web 端口 `18090`。
- 启动成功后自动打开前端。
- macOS 下会在 Vite/esbuild 因本地签名问题无法执行时尝试自动修复。

访问：

- 控制台：[http://127.0.0.1:18090](http://127.0.0.1:18090)
- API/Swagger：[http://127.0.0.1:18089/docs](http://127.0.0.1:18089/docs)
- Health：[http://127.0.0.1:18089/api/v1/health](http://127.0.0.1:18089/api/v1/health)

## Docker 完整栈

```powershell
Copy-Item .env.example .env
# 修改 .env 中的密钥、管理员密码和可选模型配置
docker compose up -d --build
docker compose ps
```

启动完成后访问：

- Arthra 控制台：[http://localhost:18090](http://localhost:18090)
- Arthra API/Swagger：[http://localhost:18089/docs](http://localhost:18089/docs)
- ThingsBoard：[http://localhost:9090](http://localhost:9090)

默认演示账号：

| 系统 | 账号 | 密码 |
| --- | --- | --- |
| Arthra | `admin@arthra.local` | `Arthra@123456` |
| ThingsBoard Tenant | `tenant@thingsboard.org` | `tenant` |

查看日志或停止：

```powershell
docker compose logs -f api simulator thingsboard
docker compose down
```

清空演示数据：

```powershell
docker compose down -v
```

该命令会删除本项目 Compose 卷中的 Arthra、Milvus 与 ThingsBoard 数据，不可恢复。

## 关键环境变量

`.env.example` 复制为 `.env` 后至少检查：

- `APP_SECRET_KEY`：必须换成新的长随机值，不能使用模板值。
- `BOOTSTRAP_ADMIN_EMAIL`、`BOOTSTRAP_ADMIN_PASSWORD`：本地可沿用演示账号，共享环境必须修改。
- `CORS_ORIGINS`：必须包含前端实际地址。
- `VITE_API_BASE_URL`：必须指向浏览器可访问的 API。
- `DATABASE_URL`、`LANGGRAPH_DATABASE_URL`：Docker 使用 Compose 服务名；LR 轻量脚本会临时覆盖为 SQLite。
- `INDUSTRIAL_DATA_PROVIDER`：完整栈默认 `thingsboard`；轻量脚本临时覆盖为 `mock`。
- `THINGSBOARD_URL`、`THINGSBOARD_USERNAME`、`THINGSBOARD_PASSWORD`：仅在使用 ThingsBoard 或完整 Docker 栈时需要可用。
- `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`：需要真实语义路由和专家解释时配置。
- `EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSIONS`：生产 RAG 应配置正式嵌入模型并保持维度与 Milvus collection 一致。
- `MILVUS_URI`、`MILVUS_TOKEN`、`MILVUS_COLLECTION`：RAG 向量库配置。
- `DAILY_SUMMARY_ENABLED`：完整栈需要日报时保持 `true` 并确认时区与时间。

## 模型配置

对话模型与嵌入模型独立配置。两者都遵循 OpenAI-compatible API：

```dotenv
LLM_API_KEY=your-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

SUPERVISOR_SEMANTIC_ROUTING_ENABLED=true
SUPERVISOR_LLM_MODEL=
SUPERVISOR_ROUTE_CONFIDENCE_THRESHOLD=0.65

COMPRESSOR_EXPERT_LLM_ENABLED=true
COMPRESSOR_EXPERT_LLM_MODEL=
POWER_EXPERT_LLM_ENABLED=true
POWER_EXPERT_LLM_MODEL=

EMBEDDING_API_KEY=your-embedding-key
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=384

RAG_RETRIEVAL_ENABLED=true
RAG_TOP_K=4
RAG_MIN_SCORE=0.2
VECTORSTORE_PROVIDER=milvus
MILVUS_URI=http://localhost:19530
MILVUS_TOKEN=
MILVUS_COLLECTION=arthra_knowledge_chunks
```

未配置 `LLM_API_KEY` 时，平台、设备、路由和知识解释的内置安全回退仍可运行；未配置 embedding API 时使用确定性的本地演示向量，生产环境应配置正式嵌入模型。

## 切换到本地 Ollama

先确认本机已启动 Ollama，并且已拉取模型：

```powershell
ollama list
curl http://127.0.0.1:11434/v1/models
```

本机直接运行 LR 脚本时：

```dotenv
LLM_API_KEY=ollama
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen3.5:9b-q4_K_M
NO_PROXY=127.0.0.1,localhost

EMBEDDING_API_KEY=ollama
EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
EMBEDDING_MODEL=qwen3-embedding:0.6b
EMBEDDING_DIMENSIONS=384
```

如果 API 跑在 Docker 容器里，而 Ollama 跑在宿主机上：

```dotenv
LLM_BASE_URL=http://host.docker.internal:11434/v1
EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
```

`EMBEDDING_API_KEY` 必须填写任意非空值，例如 `ollama`，否则系统会走本地演示向量而不会调用 Ollama。修改 `.env` 后需要重启 API。

## API 示例

登录：

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://localhost:18089/api/v1/auth/login `
  -ContentType application/json `
  -Body '{"email":"admin@arthra.local","password":"Arthra@123456"}'
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod http://localhost:18089/api/v1/devices -Headers $headers
```

调用空压系统上下文分析：

```powershell
$body = @{
  message = "分析加载率、空载、频繁启停、压力波动和比功率"
  device_scope = @("ThingsBoard-compressor-device-uuid")
  capabilities = @("load_rate", "idle_running", "frequent_start", "pressure_fluctuation", "specific_power")
} | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:18089/api/v1/compressor-analysis `
  -Headers $headers -ContentType application/json -Body $body
```

创建待审批控制计划：

```powershell
$body = @{
  device_id = "ThingsBoard-device-uuid"
  device_name = "Arthra-EMS-01"
  device_type = "ems"
  method = "setPowerLimit"
  params = @{ value = 300 }
  reason = "需量控制建议"
  risk_level = "medium"
} | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:18089/api/v1/control-plans `
  -Headers $headers -ContentType application/json -Body $body
```

只有 `admin` 或 `approver` 能调用 `/control-plans/{id}/approve`。批准时系统会再次校验设备类型、方法、参数范围和有效期，之后才发送 RPC。

## 常见问题

**ThingsBoard 长时间未就绪？** 首次启动会初始化内部 PostgreSQL。运行 `docker compose logs -f thingsboard`，等待 Web 服务监听 9090 后模拟器会自动重试。

**设备列表为空？** 检查 `simulator` 日志。它会使用 Tenant 账号创建三台设备并通过设备 token 上报数据。

**登录页出现 `Failed to fetch`？** 优先打开 `/api/v1/health`，再查看 `.local-dev/logs/api-lr*.log` 和 `.local-dev/logs/web-lr*.log`。

**批准后显示 failed？** 检查模拟器是否连接 1883 端口并订阅 RPC；失败会写入计划结果和审计记录，不会静默重试控制。
