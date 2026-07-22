import json
import logging

from arthra.observability import JsonLogFormatter, MetricsRegistry, trace_id_context


def test_metrics_registry_exports_counters_and_latency():
    registry = MetricsRegistry()
    registry.increment("agent_runs_total", labels={"status": "completed"})
    registry.observe("agent_run_duration_ms", 12.5)

    rendered = registry.render_prometheus()
    assert 'agent_runs_total{status="completed"} 1.0' in rendered
    assert "agent_run_duration_ms_count 1" in rendered
    assert "agent_run_duration_ms_max 12.5" in rendered


def test_json_logs_include_trace_id():
    token = trace_id_context.set("trace-test")
    try:
        record = logging.LogRecord("arthra.test", logging.INFO, __file__, 1, "hello", (), None)
        payload = json.loads(JsonLogFormatter().format(record))
    finally:
        trace_id_context.reset(token)

    assert payload["trace_id"] == "trace-test"
    assert payload["message"] == "hello"
