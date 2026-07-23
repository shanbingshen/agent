from arthra.contracts import StrictModel
from pydantic import Field


class CheckpointConfig(StrictModel):
    thread_id: str = Field(min_length=1, max_length=255)
    checkpoint_ns: str = Field(min_length=1, max_length=128)

    def langgraph_config(self) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": self.thread_id, "checkpoint_ns": self.checkpoint_ns}}
