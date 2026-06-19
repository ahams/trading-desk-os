from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from backend.schemas import CreateApiKeyRequest, CreateUserRequest, BillingEventRequest
from config.settings import settings
from database.store import connect, create_api_key_for_user, create_user, get_user_by_email, init_db, utc_now

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _require_admin(x_admin_key: Optional[str]):
    if x_admin_key != settings.admin_bootstrap_key:
        raise HTTPException(status_code=401, detail="Invalid admin key")


@router.post("/users")
def admin_create_user(req: CreateUserRequest, x_admin_key: Optional[str] = Header(default=None)):
    _require_admin(x_admin_key)
    return create_user(req.email, req.name, req.plan, req.monthly_credit_limit)


@router.post("/api-keys")
def admin_create_api_key(req: CreateApiKeyRequest, x_admin_key: Optional[str] = Header(default=None)):
    _require_admin(x_admin_key)
    return create_api_key_for_user(req.email, req.label)


@router.post("/billing-event")
def billing_event(req: BillingEventRequest, x_admin_key: Optional[str] = Header(default=None)):
    _require_admin(x_admin_key)
    init_db()
    user = get_user_by_email(req.email) if req.email else None
    with connect() as conn:
        conn.execute(
            "INSERT INTO billing_events(user_id, event_type, payload_json, created_at) VALUES(?,?,?,?)",
            (user["id"] if user else None, req.event_type, json.dumps(req.payload), utc_now()),
        )
    return {"ok": True, "user_id": user["id"] if user else None}

@router.get("/debug-admin")
def debug_admin():
    return {
        "admin_key_loaded": bool(settings.admin_bootstrap_key),
        "admin_key_length": len(settings.admin_bootstrap_key or ""),
        "admin_key_preview": (
            settings.admin_bootstrap_key[:3] + "***" + settings.admin_bootstrap_key[-3:]
            if settings.admin_bootstrap_key
            else None
        ),
    }