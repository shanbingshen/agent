from pathlib import Path

from arthra.agent import build_graph
from arthra.config import Settings
from arthra.evaluation import evaluate_graph, load_eval_cases


def test_agent_regression_evaluation_set(monkeypatch):
    monkeypatch.setattr("arthra.agent.get_settings", lambda: Settings(llm_api_key=""))

    def loader(ids):
        if not ids:
            return []
        device_id = ids[0]
        is_meter = device_id.startswith("meter")
        return [
            {
                "id": device_id,
                "name": "Meter 1" if is_meter else "Compressor 1",
                "type": "meter" if is_meter else "compressor",
                "telemetry": {"meter_TotW": 100.0} if is_meter else {"running": True},
                "timestamps": {},
            }
        ]

    cases = load_eval_cases(Path(__file__).parent / "evals" / "agent_regression.jsonl")
    report = evaluate_graph(build_graph(telemetry_loader=loader), cases)

    assert report.failed == 0, [result.model_dump() for result in report.results if not result.passed]
