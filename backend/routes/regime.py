from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth import AuthUser, require_credits
from services.analysis_service import get_regime

router = APIRouter(prefix="/api/v1", tags=["regime"])


@router.get("/regime")
def regime(period: str = "1y", interval: str = "1d", user: AuthUser = Depends(require_credits("regime", 1))):
    return {"user": {"email": user.email, "plan": user.plan}, "credits_used": 1, "data": get_regime(period, interval)}
