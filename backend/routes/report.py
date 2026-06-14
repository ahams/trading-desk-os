from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth import AuthUser, require_credits
from backend.schemas import DailyReportRequest
from services.analysis_service import build_daily_report, recent_signals

router = APIRouter(prefix="/api/v1", tags=["reports"])


@router.post("/report/daily")
def daily_report(req: DailyReportRequest, user: AuthUser = Depends(require_credits("daily_report", 50))):
    result = build_daily_report(
        tickers=req.tickers,
        title=req.title,
        max_names=req.max_names,
        include_signal_records=req.include_signal_records,
    )
    return {"user": {"email": user.email, "plan": user.plan}, "credits_used": 50, "data": result}


@router.get("/signals/recent")
def get_recent_signals(limit: int = 100, user: AuthUser = Depends(require_credits("signals_recent", 1))):
    return {"user": {"email": user.email, "plan": user.plan}, "credits_used": 1, "data": recent_signals(limit)}
