from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.api.routes.creatures import router as creatures_router
from backend.api.routes.fights import router as fights_router
from backend.api.routes.health import router as health_router
from backend.api.routes.analytics import router as analytics_router
from backend.api.routes.betting import router as betting_router
from backend.api.routes.simulation import router as simulation_router
from backend.api.routes.ws import router as ws_router
from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.db import models  # noqa: F401
from backend.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    logger.info("Application startup complete")
    try:
        yield
    finally:
        logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(creatures_router)
    app.include_router(fights_router)
    app.include_router(health_router)
    app.include_router(analytics_router)
    app.include_router(betting_router)
    app.include_router(simulation_router)
    app.include_router(ws_router)

    audio_dir = Path(settings.audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/audio", StaticFiles(directory=str(audio_dir)), name="audio")

    @app.get("/")
    def root() -> dict[str, str]:
        return {"message": "Survival of the Fittest backend online"}

    return app


app = create_app()
