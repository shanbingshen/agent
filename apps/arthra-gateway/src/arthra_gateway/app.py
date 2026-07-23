"""Gateway 应用工厂，保持现有外部 API 与 SSE 合约。"""

import asyncio
from contextlib import asynccontextmanager, suppress

from arthra.api import router
from arthra.config import get_settings
from arthra.db import SessionLocal
from arthra.observability import TraceMiddleware, configure_structured_logging
from arthra.security import bootstrap_admin
from arthra_orchestrator import create_agent_runtime
from arthra_scheduler import run_scheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = create_agent_runtime(settings)
        app.state.graph = runtime.graph
        with SessionLocal() as db:
            bootstrap_admin(db)
        scheduler_task = asyncio.create_task(run_scheduler())
        try:
            yield
        finally:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
            runtime.close()

    configure_structured_logging()
    app = FastAPI(
        title="Arthra 能碳大脑 API",
        version="0.1.0",
        description="Gateway for Arthra LangGraph agents",
        lifespan=lifespan,
    )
    app.add_middleware(TraceMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app
