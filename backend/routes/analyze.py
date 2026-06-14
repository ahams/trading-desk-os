from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.auth import AuthUser, require_credits
from backend.schemas import AnalyzeRequest
from services.analysis_service import analyze_stock
from services.response_formatter import compact_analysis

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post("/analyze")
def analyze(
    req: AnalyzeRequest,
    compact: bool = Query(False, description="Return end-user friendly compact response instead of full raw engine payload."),
    user: AuthUser = Depends(require_credits("analyze", 1)),
):
    result = analyze_stock(
        ticker=req.ticker,
        period=req.period,
        interval=req.interval,
        account_size=req.account_size,
        risk_pct=req.risk_pct,
        persist_signal=req.persist_signal,
    )
    data = compact_analysis(result) if compact else result
    return {"user": {"email": user.email, "plan": user.plan}, "credits_used": 1, "compact": compact, "data": data}


@router.post("/analyze/compact")
def analyze_compact(req: AnalyzeRequest, user: AuthUser = Depends(require_credits("analyze_compact", 1))):
    result = analyze_stock(
        ticker=req.ticker,
        period=req.period,
        interval=req.interval,
        account_size=req.account_size,
        risk_pct=req.risk_pct,
        persist_signal=req.persist_signal,
    )
    return {"user": {"email": user.email, "plan": user.plan}, "credits_used": 1, "compact": True, "data": compact_analysis(result)}
