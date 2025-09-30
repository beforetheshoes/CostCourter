from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .core.config import settings
from .core.logging import configure_logging
from .models import ensure_core_model_mappings


def create_application() -> FastAPI:
    configure_logging()
    ensure_core_model_mappings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS for local dev / docker overlay
    origins = settings.cors_origins or []
    if settings.debug and not origins:
        origins = [
            "http://localhost:5173",
            "http://localhost:4173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:4173",
            "http://frontend:4173",
        ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router, prefix="/api")
    return app


app = create_application()
