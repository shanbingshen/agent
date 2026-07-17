FROM python:3.12.13-slim-bookworm
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.26
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev || uv sync --no-dev
COPY services/simulator ./services/simulator
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/services/simulator"
CMD ["python", "services/simulator/main.py"]
