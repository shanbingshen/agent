from typing import Literal

from arthra.contracts import StrictModel
from pydantic import Field


class AgentPlugin(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    domain: Literal["ems", "power", "compressor", "carbon", "optimizer", "main"]
    allowed_tools: list[str] = Field(default_factory=list, max_length=40)
    deterministic_service: str = Field(min_length=1, max_length=200)


class AgentRunRequested(StrictModel):
    thread_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=64)
    factory_id: str = Field(min_length=1, max_length=64)
    device_scope: list[str] = Field(default_factory=list, max_length=1000)
    message: str = Field(min_length=1, max_length=10000)
