from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, Request, status

from database.store import get_user_by_api_key, record_usage, usage_this_month


@dataclass
class AuthUser:
    id: int
    email: str
    name: Optional[str]
    plan: str
    monthly_credit_limit: int

    @property
    def usage(self) -> int:
        return usage_this_month(self.id)


def _extract_api_key(authorization: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> AuthUser:
    api_key = _extract_api_key(authorization, x_api_key)
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key. Use X-API-Key or Authorization: Bearer <key>.")
    user = get_user_by_api_key(api_key)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive API key.")
    auth_user = AuthUser(
        id=int(user["id"]),
        email=user["email"],
        name=user.get("name"),
        plan=user["plan"],
        monthly_credit_limit=int(user["monthly_credit_limit"]),
    )
    request.state.user_id = auth_user.id
    return auth_user


def require_credits(endpoint: str, credits: int) -> Callable:
    def dependency(request: Request, user: AuthUser = Depends(get_current_user)) -> AuthUser:
        current = usage_this_month(user.id)
        if current + credits > user.monthly_credit_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": "Monthly API credit limit exceeded.",
                    "plan": user.plan,
                    "used": current,
                    "limit": user.monthly_credit_limit,
                    "credits_required": credits,
                    "upgrade_hint": "Upgrade plan or buy extra credits.",
                },
            )
        # Mark for middleware/handlers and debit immediately so failed expensive calls are still metered.
        request.state.credit_endpoint = endpoint
        request.state.credits_used = credits
        record_usage(user.id, endpoint, credits, getattr(request.state, "request_id", None))
        request.state.usage_after = usage_this_month(user.id)
        return user

    return dependency
