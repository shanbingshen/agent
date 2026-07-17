from datetime import datetime

from langchain_core.tools import tool

from arthra.compressor.analysis import CompressorAnalysisService
from arthra.compressor.schemas import CompressorAnalysisRequest, CompressorAnalysisResult


@tool("analyze_compressor_system")
def analyze_compressor_system_tool(
    message: str,
    device_scope: list[str],
    start_at: str,
    end_at: str,
    capabilities: list[str],
    interval_seconds: int = 180,
) -> CompressorAnalysisResult:
    """Run read-only deterministic compressed-air analysis over ThingsBoard history."""
    request = CompressorAnalysisRequest(
        message=message,
        device_scope=device_scope,
        start_at=datetime.fromisoformat(start_at),
        end_at=datetime.fromisoformat(end_at),
        capabilities=capabilities,
        interval_seconds=interval_seconds,
    )
    return CompressorAnalysisService().analyze(request)
