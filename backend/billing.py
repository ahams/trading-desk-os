"""Stripe-ready billing helpers.

This file intentionally avoids hard dependency on Stripe so the API runs locally.
When ready for production:
1. pip install stripe
2. set STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
3. wire webhook events to update users.plan/monthly_credit_limit.
"""
from __future__ import annotations

import os
from typing import Dict

PLAN_CREDITS = {
    "free": 100,
    "starter": 10_000,
    "pro": 100_000,
    "desk": 1_000_000,
}

PLAN_PRICES_USD = {
    "free": 0,
    "starter": 49,
    "pro": 149,
    "desk": 499,
}


def plan_limits() -> Dict[str, dict]:
    return {plan: {"monthly_credits": PLAN_CREDITS[plan], "price_usd": PLAN_PRICES_USD[plan]} for plan in PLAN_CREDITS}


def stripe_enabled() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY"))
