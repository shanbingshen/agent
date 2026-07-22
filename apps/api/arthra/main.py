import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres import PostgresSaver

from arthra.agent import (
    agent_checkpoint_serializer,
    build_graph,
)
from arthra.api import router
from arthra.config import get_settings
from arthra.daily_summary import daily_summary_scheduler
from arthra.db import SessionLocal
from arthra.observability import TraceMiddleware, configure_structured_logging
from arthra.security import bootstrap_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    checkpoint_context = None
    checkpointer = None
    if settings.langgraph_database_url:
        checkpoint_context = PostgresSaver.from_conn_string(settings.langgraph_database_url)
        checkpointer = checkpoint_context.__enter__()
        checkpointer.serde = agent_checkpoint_serializer()
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
configure_structured_logging()
app = FastAPI(title="Arthra 能碳大脑 API", version="0.1.0", description="LangGraph 多专家与 ThingsBoard 能源设备协同平台", lifespan=lifespan)
app.add_middleware(TraceMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
