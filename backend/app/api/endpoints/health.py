from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.config import settings
from app.core.database import get_session
from app.services.health import (
    build_metrics_payload,
    build_readiness_report,
)

router = APIRouter()


@router.get("", summary="Health probe")
def healthcheck() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/readiness", summary="Readiness health probe")
def readiness_check(session: Session = Depends(get_session)) -> dict[str, Any]:
    return build_readiness_report(session, settings)


@router.get("/metrics", summary="Operational metrics snapshot")
def health_metrics(session: Session = Depends(get_session)) -> dict[str, Any]:
    return build_metrics_payload(session, settings)
