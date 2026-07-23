from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field

from arthra.contracts import StrictModel
from arthra.question_answering import (
    BusinessDomain,
    QueryTimeRange,
    QuestionIntent,
    QuestionMode,
)

type ContextRoute = Literal[
    "ems",
    "power",
    "compressor",
    "forecast",
    "report",
    "conversation",
]
type PageWorkspace = Literal[
    "overview",
    "demand",
    "quality",
    "compressor",
    "carbon",
    "events",
]
type ContextTimeScope = Literal[
    "realtime",
    "today",
    "yesterday",
    "last_24h",
    "last_7d",
    "current_month",
]


class ConversationTurn(StrictModel):
    turn_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)
    user_message: str = Field(min_length=1, max_length=10_000)
    assistant_summary: str = Field(default="", max_length=800)
    route: ContextRoute
    query_mode: QuestionMode = "conversation"
    domain: BusinessDomain = "general"
    intent: QuestionIntent = "UNKNOWN"
    subject: str = Field(default="", max_length=80)
    device_scope: list[str] = Field(default_factory=list, max_length=100)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    time_range: QueryTimeRange | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConversationContext(StrictModel):
    turns: list[ConversationTurn] = Field(default_factory=list, max_length=12)
    active_route: ContextRoute | None = None
    active_query_mode: QuestionMode = "conversation"
    active_domain: BusinessDomain = "general"
    active_intent: QuestionIntent = "UNKNOWN"
    active_subject: str = Field(default="", max_length=80)
    active_device_scope: list[str] = Field(default_factory=list, max_length=100)
    active_capabilities: list[str] = Field(default_factory=list, max_length=20)
    active_time_range: QueryTimeRange | None = None
    active_workspace: PageWorkspace | None = None
