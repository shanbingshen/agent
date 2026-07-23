#!/bin/zsh
set -euo pipefail

ROOT="/Users/aethravolt007/AethraVolt/agent"
LR_PY="/Users/aethravolt007/miniforge3/envs/LR/bin/python"
PNPM="/Users/aethravolt007/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm"
NODE_BIN="/Users/aethravolt007/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-18089}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-18090}"
OPEN_BROWSER="${OPEN_BROWSER:-1}"
BROWSER_API_HOST="$API_HOST"
[[ "$BROWSER_API_HOST" == "0.0.0.0" ]] && BROWSER_API_HOST="localhost"
CORS_ORIGINS="${CORS_ORIGINS:-http://$WEB_HOST:$WEB_PORT,http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT}"
NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"

LOG_DIR="$ROOT/.local-dev/logs"
RUN_DIR="$ROOT/.local-dev/run"
DB_FILE="${DB_FILE:-$RUN_DIR/arthra-lr-$(date '+%Y%m%d-%H%M%S').db}"
API_LOG="$LOG_DIR/api-lr.log"
WEB_LOG="$LOG_DIR/web-lr.log"

mkdir -p "$LOG_DIR"
mkdir -p "$RUN_DIR"
cd "$ROOT"

say_step() {
  printf "\n[%s] %s\n" "$(date '+%H:%M:%S')" "$1"
}

fail() {
  printf "\n启动失败：%s\n" "$1" >&2
  printf "按回车关闭窗口。" >&2
  read -r _ || true
  exit 1
}

require_executable() {
  [[ -x "$1" ]] || fail "找不到可执行文件：$1"
}

port_in_use() {
  /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_url() {
  local url="$1"
  local name="$2"
  local log_file="$3"
  local attempts=60
  for _ in {1..60}; do
    if /usr/bin/curl -fsS "$url" >/dev/null 2>&1; then
      say_step "$name 已就绪：$url"
      return 0
    fi
    sleep 1
  done
  printf "\n%s 启动日志：\n" "$name" >&2
  /usr/bin/tail -n 80 "$log_file" >&2 || true
  fail "$name 未能在 $attempts 秒内就绪"
}

cleanup() {
  say_step "正在停止本次启动的服务..."
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" >/dev/null 2>&1 || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" >/dev/null 2>&1 || true
}
trap cleanup INT TERM

say_step "检查 LR 环境和前端工具链"
require_executable "$LR_PY"
require_executable "$PNPM"
require_executable "$NODE_BIN/node"

"$LR_PY" -c "import fastapi, sqlalchemy, langgraph, psycopg, uvicorn" \
  || fail "LR 环境缺少后端依赖。请先在 LR 环境安装 pyproject.toml 中的运行依赖。"

[[ -d "$ROOT/apps/web/node_modules" ]] \
  || fail "前端依赖未安装。请先执行：$PNPM --dir \"$ROOT/apps/web\" install"

if port_in_use "$API_PORT"; then
  fail "后端端口 $API_PORT 已被占用，请先关闭占用该端口的进程。"
fi
if port_in_use "$WEB_PORT"; then
  fail "前端端口 $WEB_PORT 已被占用，请先关闭占用该端口的进程。"
fi

say_step "初始化本地调试数据库：$DB_FILE"
DATABASE_URL="sqlite:///$DB_FILE" \
LANGGRAPH_DATABASE_URL="" \
INDUSTRIAL_DATA_PROVIDER="mock" \
DAILY_SUMMARY_ENABLED="false" \
CORS_ORIGINS="$CORS_ORIGINS" \
NO_PROXY="$NO_PROXY" \
no_proxy="$NO_PROXY" \
PYTHONPATH="$ROOT/apps/api:$ROOT/apps/arthra-gateway/src:$ROOT/apps/arthra-orchestrator/src:$ROOT/apps/arthra-scheduler/src:$ROOT/agents/main-agent/src:$ROOT/agents/power-agent/src:$ROOT/agents/compressor-agent/src:$ROOT/packages/core/src:$ROOT/packages/rag/src:$ROOT/packages/memory/src:$ROOT/packages/tools/src:$ROOT/packages/mcp-client/src:$ROOT/packages/evaluation/src:$ROOT/packages/observability/src:$ROOT/mcp-servers/energy-data/src" \
"$LR_PY" -c "from arthra.db import Base, engine; import arthra.models; Base.metadata.create_all(engine)"

say_step "启动后端 API：http://$API_HOST:$API_PORT"
DATABASE_URL="sqlite:///$DB_FILE" \
LANGGRAPH_DATABASE_URL="" \
INDUSTRIAL_DATA_PROVIDER="mock" \
DAILY_SUMMARY_ENABLED="false" \
SUPERVISOR_SEMANTIC_ROUTING_ENABLED="false" \
COMPRESSOR_EXPERT_LLM_ENABLED="false" \
POWER_EXPERT_LLM_ENABLED="false" \
CORS_ORIGINS="$CORS_ORIGINS" \
NO_PROXY="$NO_PROXY" \
no_proxy="$NO_PROXY" \
PYTHONPATH="$ROOT/apps/api:$ROOT/apps/arthra-gateway/src:$ROOT/apps/arthra-orchestrator/src:$ROOT/apps/arthra-scheduler/src:$ROOT/agents/main-agent/src:$ROOT/agents/power-agent/src:$ROOT/agents/compressor-agent/src:$ROOT/packages/core/src:$ROOT/packages/rag/src:$ROOT/packages/memory/src:$ROOT/packages/tools/src:$ROOT/packages/mcp-client/src:$ROOT/packages/evaluation/src:$ROOT/packages/observability/src:$ROOT/mcp-servers/energy-data/src" \
"$LR_PY" -m uvicorn arthra.main:app --host "$API_HOST" --port "$API_PORT" > "$API_LOG" 2>&1 &
API_PID=$!

wait_for_url "http://$API_HOST:$API_PORT/api/v1/health" "后端 API" "$API_LOG"

say_step "启动前端控制台：http://$WEB_HOST:$WEB_PORT"
PATH="$NODE_BIN:$PATH" \
VITE_API_BASE_URL="http://$BROWSER_API_HOST:$API_PORT/api/v1" \
"$PNPM" --dir "$ROOT/apps/web" exec vite --host "$WEB_HOST" --port "$WEB_PORT" > "$WEB_LOG" 2>&1 &
WEB_PID=$!

wait_for_url "http://$WEB_HOST:$WEB_PORT/" "前端控制台" "$WEB_LOG"

cat <<EOF

Arthra LR 本地调试环境已启动。

控制台： http://$WEB_HOST:$WEB_PORT
API：    http://$API_HOST:$API_PORT
账号：   admin@arthra.local
密码：   Arthra@123456

当前使用 mock 工业数据和 SQLite 临时库：
- 不需要 Docker / ThingsBoard / PostgreSQL
- 真实 ThingsBoard 设备、RPC 控制和完整容器栈未启用

日志：
- $API_LOG
- $WEB_LOG

关闭这个终端窗口或按 Ctrl+C 会停止本次启动的服务。
EOF

if [[ "$OPEN_BROWSER" == "1" ]]; then
  /usr/bin/open "http://$WEB_HOST:$WEB_PORT" >/dev/null 2>&1 || true
fi

wait
