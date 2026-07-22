import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from arthra.agent import (
    AgentState,
    CompressorToolCallPlan,
    PowerToolCallPlan,
    RouteDecision,
    build_graph,
)
from arthra.agent_schemas import ExpertAnalysis
from arthra.api import router
from arthra.compressor.schemas import CompressorAnalysisResult, CompressorSystemContext
from arthra.config import get_settings
from arthra.contracts import AnalysisWarning
from arthra.daily_summary import daily_summary_scheduler
from arthra.db import SessionLocal
from arthra.power.schemas import PowerAnalysisResult, PowerSystemContext
from arthra.security import bootstrap_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    checkpoint_context = None
    checkpointer = None
    if settings.langgraph_database_url:
        checkpoint_context = PostgresSaver.from_conn_string(settings.langgraph_database_url)
        checkpointer = checkpoint_context.__enter__()
        checkpointer.serde = JsonPlusSerializer(
            allowed_msgpack_modules=(
                AgentState,
                CompressorToolCallPlan,
                PowerToolCallPlan,
                RouteDecision,
                ExpertAnalysis,
                CompressorAnalysisResult,
                CompressorSystemContext,
                PowerAnalysisResult,
                PowerSystemContext,
                AnalysisWarning,
            )
        )
        checkpointer.setup()
    app.state.graph = build_graph(checkpointer)
    with SessionLocal() as db:
        bootstrap_admin(db)
    scheduler_task = asyncio.create_task(daily_summary_scheduler())
    yield
    scheduler_task.cancel()
    with suppress(asyncio.CancelledError):
        await scheduler_task
    if checkpoint_context:
        checkpoint_context.__exit__(None, None, None)


settings = get_settings()
app = FastAPI(title="Arthra 能碳大脑 API", version="0.1.0", description="LangGraph 多专家与 ThingsBoard 能源设备协同平台", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
