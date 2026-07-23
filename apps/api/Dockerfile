FROM python:3.12.13-slim-bookworm
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.26
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev || uv sync --no-dev
COPY apps/api ./apps/api
COPY apps/arthra-gateway ./apps/arthra-gateway
COPY apps/arthra-orchestrator ./apps/arthra-orchestrator
COPY apps/arthra-scheduler ./apps/arthra-scheduler
COPY agents ./agents
COPY packages ./packages
COPY mcp-servers ./mcp-servers
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/apps/api:/app/apps/arthra-gateway/src:/app/apps/arthra-orchestrator/src:/app/apps/arthra-scheduler/src:/app/agents/main-agent/src:/app/agents/power-agent/src:/app/agents/compressor-agent/src:/app/packages/core/src:/app/packages/rag/src:/app/packages/memory/src:/app/packages/tools/src:/app/packages/mcp-client/src:/app/packages/evaluation/src:/app/packages/observability/src:/app/mcp-servers/energy-data/src"
EXPOSE 18089
CMD ["sh", "-c", "alembic -c apps/api/alembic.ini upgrade head && uvicorn arthra.main:app --host 0.0.0.0 --port 18089"]
