from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth import AuthUser, get_current_user, require_credits
from database.store import list_usage, usage_this_month

router = APIRouter(prefix="/api/v1", tags=["account"])


@router.get("/account")
def account(user: AuthUser = Depends(get_current_user)):
    used = usage_this_month(user.id)
    return {
        "email": user.email,
        "plan": user.plan,
        "monthly_credit_limit": user.monthly_credit_limit,
        "monthly_credits_used": used,
        "monthly_credits_remaining": max(0, user.monthly_credit_limit - used),
    }


@router.get("/usage")
def usage(limit: int = 200, user: AuthUser = Depends(get_current_user)):
    return {"summary": account(user), "items": list_usage(user.id, limit)}
