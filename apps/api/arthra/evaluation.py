from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import Field

from arthra.contracts import StrictModel


class AgentEvalCase(StrictModel):
    case_id: str = Field(min_length=1, max_length=100)
    turns: list[str] = Field(min_length=1, max_length=8)
    device_scope: list[str] = Field(default_factory=list, max_length=20)
    expected_route: str = Field(min_length=1, max_length=64)
    required_phrases: list[str] = Field(default_factory=list, max_length=20)
    forbidden_phrases: list[str] = Field(default_factory=list, max_length=20)


class AgentEvalResult(StrictModel):
    case_id: str
    passed: bool
    actual_route: str | None = None
    failures: list[str] = Field(default_factory=list)


class AgentEvalReport(StrictModel):
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    results: list[AgentEvalResult]


def load_eval_cases(path: str | Path) -> list[AgentEvalCase]:
    cases: list[AgentEvalCase] = []
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            cases.append(AgentEvalCase.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"Agent 评测集第 {line_number} 行无效") from exc
    return cases


def evaluate_graph(
    graph: Any,
    cases: Iterable[AgentEvalCase],
    *,
    checkpoint_ns: str = "arthra-agent-eval-v1",
) -> AgentEvalReport:
    results: list[AgentEvalResult] = []
    for case in cases:
        final: dict[str, Any] = {}
        config = {
            "configurable": {
                "thread_id": f"eval:{case.case_id}",
                "checkpoint_ns": checkpoint_ns,
            }
        }
        for turn in case.turns:
            final = graph.invoke(
                {"message": turn, "device_scope": case.device_scope},
                config,
            )
        route = final.get("route")
        response = str(final.get("response", ""))
        failures: list[str] = []
        if route != case.expected_route:
            failures.append(f"期望路由 {case.expected_route}，实际为 {route}")
        for phrase in case.required_phrases:
            if phrase not in response:
                failures.append(f"回答缺少必要文本：{phrase}")
        for phrase in case.forbidden_phrases:
            if phrase in response:
                failures.append(f"回答包含禁止文本：{phrase}")
        results.append(
            AgentEvalResult(
                case_id=case.case_id,
                passed=not failures,
                actual_route=route,
                failures=failures,
            )
        )
    passed = sum(result.passed for result in results)
    return AgentEvalReport(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
    )
