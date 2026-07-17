FROM python:3.12.13-slim-bookworm
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.26
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev || uv sync --no-dev
COPY apps/api ./apps/api
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/apps/api"
EXPOSE 8000
CMD ["sh", "-c", "alembic -c apps/api/alembic.ini upgrade head && uvicorn arthra.main:app --host 0.0.0.0 --port 8000"]
