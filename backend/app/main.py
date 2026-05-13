from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .config import Settings, get_settings
from .state import build_services


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    services = build_services(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services
        try:
            yield
        finally:
            services.qr_jobs.close()

    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.services = services

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()
