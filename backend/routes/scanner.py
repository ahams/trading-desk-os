from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.auth import AuthUser, require_credits
from backend.schemas import ScannerRequest
from services.analysis_service import scan_tickers
from services.response_formatter import compact_scanner

router = APIRouter(prefix="/api/v1", tags=["scanner"])


@router.post("/scanner")
def scanner(
    req: ScannerRequest,
    compact: bool = Query(False, description="Return compact scanner rows for UI/end-user display."),
    top_n: int = Query(20, ge=1, le=100),
    user: AuthUser = Depends(require_credits("scanner", 25)),
):
    result = scan_tickers(
        tickers=req.tickers,
        period=req.period,
        interval=req.interval,
        max_names=req.max_names,
        min_price=req.min_price,
        min_avg_dollar_volume=req.min_avg_dollar_volume,
        include_options=req.include_options,
    )
    data = compact_scanner(result, top_n=top_n) if (compact or req.compact) else result
    return {"user": {"email": user.email, "plan": user.plan}, "credits_used": 25, "compact": bool(compact or req.compact), "data": data}


@router.post("/scanner/compact")
def scanner_compact(
    req: ScannerRequest,
    top_n: int = Query(20, ge=1, le=100),
    user: AuthUser = Depends(require_credits("scanner_compact", 25)),
):
    result = scan_tickers(
        tickers=req.tickers,
        period=req.period,
        interval=req.interval,
        max_names=req.max_names,
        min_price=req.min_price,
        min_avg_dollar_volume=req.min_avg_dollar_volume,
        include_options=req.include_options,
    )
    return {"user": {"email": user.email, "plan": user.plan}, "credits_used": 25, "compact": True, "data": compact_scanner(result, top_n=top_n)}
