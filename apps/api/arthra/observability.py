import contextvars
import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from arthra.models import AgentTrace

trace_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = trace_id_context.get()
        if trace_id:
            payload["trace_id"] = trace_id
        for field in ("operation", "tenant_id", "factory_id", "user_id", "route", "status"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = str(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_structured_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


class TraceMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        candidate = headers.get(b"x-trace-id", b"").decode("ascii", errors="ignore")
        trace_id = candidate if candidate and len(candidate) <= 64 else uuid.uuid4().hex
        token = trace_id_context.set(trace_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_trace(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-trace-id", trace_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            METRICS.increment("http_requests_total", labels={"status": str(status_code)})
            METRICS.observe("http_request_duration_ms", duration_ms)
            logging.getLogger("arthra.http").info(
                "%s %s %s %.2fms",
                scope.get("method", ""),
                scope.get("path", ""),
                status_code,
                duration_ms,
                extra={"operation": "http_request", "status": status_code},
            )
            trace_id_context.reset(token)


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._observations: dict[str, tuple[int, float, float]] = {}

    def increment(
        self,
        name: str,
        value: float = 1,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            count, total, maximum = self._observations.get(name, (0, 0.0, 0.0))
            self._observations[name] = (count + 1, total + value, max(maximum, value))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters = [
                {"name": name, "labels": dict(labels), "value": value}
                for (name, labels), value in sorted(self._counters.items())
            ]
            observations = {
                name: {"count": count, "sum": total, "max": maximum}
                for name, (count, total, maximum) in sorted(self._observations.items())
            }
        return {"counters": counters, "observations": observations}

    def render_prometheus(self) -> str:
        snapshot = self.snapshot()
        lines: list[str] = []
        for counter in snapshot["counters"]:  # type: ignore[index]
            labels = counter["labels"]  # type: ignore[index]
            suffix = ""
            if labels:
                values = ",".join(f'{key}="{value}"' for key, value in labels.items())
                suffix = "{" + values + "}"
            lines.append(f'{counter["name"]}{suffix} {counter["value"]}')  # type: ignore[index]
        for name, values in snapshot["observations"].items():  # type: ignore[union-attr]
            lines.append(f'{name}_count {values["count"]}')
            lines.append(f'{name}_sum {values["sum"]}')
            lines.append(f'{name}_max {values["max"]}')
        return "\n".join(lines) + "\n"


METRICS = MetricsRegistry()


def current_trace_id() -> str:
    return trace_id_context.get() or uuid.uuid4().hex


def persist_agent_trace(
    db: Session,
    *,
    trace_id: str,
    request_id: str,
    tenant_id: uuid.UUID,
    factory_id: uuid.UUID,
    user_id: uuid.UUID | None,
    thread_id: str | None,
    operation: str,
    status: str,
    duration_ms: float,
    route: str | None = None,
    intent: str | None = None,
    node_timings: dict[str, float] | None = None,
    tool_names: list[str] | None = None,
    error_code: str | None = None,
) -> AgentTrace:
    trace = AgentTrace(
        trace_id=trace_id,
        request_id=request_id,
        tenant_id=tenant_id,
        factory_id=factory_id,
        user_id=user_id,
        thread_id=thread_id,
        operation=operation,
        route=route,
        intent=intent,
        status=status,
        duration_ms=round(duration_ms, 3),
        node_timings={key: round(value, 3) for key, value in (node_timings or {}).items()},
        tool_names=list(dict.fromkeys(tool_names or [])),
        error_code=error_code,
    )
    db.add(trace)
    return trace
