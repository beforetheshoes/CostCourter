from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_session, require_admin
from app.models import User
from app.schemas import DashboardMetricsResponse
from app.services.dashboard_metrics import build_dashboard_metrics

router = APIRouter()


@router.get("/dashboard", response_model=DashboardMetricsResponse)
def get_dashboard_metrics(
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> DashboardMetricsResponse:
    return build_dashboard_metrics(session, current_user)


__all__ = ["router"]
